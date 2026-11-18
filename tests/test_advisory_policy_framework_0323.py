# SPDX-License-Identifier: AGPL-3.0-only
"""Advisory policy controls: explainability, RBAC, history and safe migration."""
import json
from fastapi.testclient import TestClient
import pytest
from game.db import connection, initialize
from game.main import app
from game import local_accounts, rbac
from game.core import enrich_agent

PASSWORD = 'PolicyAdmin-Testing-Passphrase-2026!'

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('GAME_DB_PATH',str(tmp_path/'policy.sqlite'))
    monkeypatch.setenv('GAME_VAULT_KEY_PATH',str(tmp_path/'key'))
    with TestClient(app) as c:
        yield c


def test_default_policy_catalog_and_empty_company_evaluation(client):
    result=client.get('/api/policies')
    assert result.status_code == 200
    catalog=result.json()
    assert len(catalog['rules']) == 10
    assert all(r['enabled'] for r in catalog['rules'])
    assert catalog['last_recorded_evaluation'] is None
    assert client.get('/api/policies/findings').json() == []
    run=client.post('/api/policies/evaluate')
    assert run.status_code==200
    assert run.json()['agents_evaluated']==0
    assert run.json()['open_findings']==0
    assert client.get('/api/policies/runs').json()[0]['id']==run.json()['id']
    initialize()  # idempotent seed, not artificial agents
    assert len(client.get('/api/policies').json()['rules'])==10
    assert client.get('/api/agents').json()==[]


def test_rules_are_configurable_and_findings_resolve(client):
    created=client.post('/api/agents',json={'name':'Unowned Build Agent','provider':'Python','environment':'development'})
    assert created.status_code==201
    agent_id=created.json()['id']
    run1=client.post('/api/policies/evaluate').json()
    assert run1['open_findings']>=2  # Missing owner, no recorded activity
    findings=client.get('/api/policies/findings').json()
    owner=next(f for f in findings if f['agent_id']==agent_id and f['policy_code']=='MISSING_OWNER')
    assert owner['status']=='open'
    assert owner['evidence']=={'business_owner_assigned':False,'technical_owner_recorded':False}
    updated=client.patch('/api/policies/MISSING_OWNER',json={'enabled':False})
    assert updated.status_code==200
    assert updated.json()['enabled'] is False
    assert 'MISSING_OWNER' not in {r['code'] for r in client.get('/api/agents/'+agent_id).json()['findings']}
    run2=client.post('/api/policies/evaluate').json()
    assert run2['resolved_in_run']>=1
    row=next(f for f in client.get('/api/policies/findings').json() if f['policy_code']=='MISSING_OWNER')
    assert row['status']=='resolved' and row['resolved_at']
    old_version=updated.json()['version']
    initialize()
    again=next(r for r in client.get('/api/policies').json()['rules'] if r['code']=='MISSING_OWNER')
    assert not again['enabled'] and again['version']==old_version
    logs=client.get('/api/audit').json()
    assert {'policy.rule.update','policy.evaluate'} <= {e['operation'] for e in logs}


def test_severity_and_threshold_changes_live_risk(client):
    a=client.post('/api/agents',json={'name':'Stale Agent','provider':'Custom','owner_email':'dev@example.org'}).json()
    code='STALE_AGENT'
    response=client.patch(f'/api/policies/{code}',json={'severity':'low','stale_after_days':7})
    assert response.status_code==200,response.text
    out=client.get('/api/agents/'+a['id']).json()
    stale=next(f for f in out['findings'] if f['code']==code)
    assert stale['severity']=='low'
    assert stale['evidence']['threshold_days']==7
    assert out['risk_level']=='medium'  # Business Owner is also unassigned
    assert client.patch('/api/policies/BUSINESS_OWNER_NOT_ASSIGNED',json={'enabled':False}).status_code==200
    assert client.get('/api/agents/'+a['id']).json()['risk_level']=='low'
    assert client.patch('/api/policies/OVER_BUDGET',json={'stale_after_days':8}).status_code==422
    assert client.patch('/api/policies/STALE_AGENT',json={'stale_after_days':0}).status_code==422
    assert client.patch('/api/policies/MISSING_OWNER',json={'severity':'critical'}).status_code==422
    assert client.patch('/api/policies/UNKNOWN',json={'enabled':False}).status_code==404


def test_discovered_agent_has_unknown_coverage_and_not_false_zero_cost():
    item={'id':'d1','source':'discovered','lifecycle_status':'unknown','environment':'unknown',
          'approval_status':'not_reviewed','sensitive_access':0,'budget_usd':10,
          'business_owner_user_id':None,'owner_email':None,'last_seen':None}
    out=enrich_agent(item,0)
    assert out['spend_observed'] is False
    assert out['coverage_notes']
    codes={r['code'] for r in out['findings']}
    assert 'UNKNOWN_ENVIRONMENT' in codes
    assert 'OVER_BUDGET' not in codes
    assert 'STALE_AGENT' not in codes


def test_technical_admin_only_manage_auditor_can_read_password_mode(tmp_path,monkeypatch):
    monkeypatch.setenv('GAME_AUTH_MODE','password')
    monkeypatch.setenv('GAME_DB_PATH',str(tmp_path/'password.db'))
    monkeypatch.setenv('GAME_VAULT_KEY_PATH',str(tmp_path/'secret.key'))
    with TestClient(app) as admin, TestClient(app) as viewer, TestClient(app) as auditor:
        for username,role in [('admin','admin'),('viewer','viewer'),('auditor','auditor')]:
            local_accounts.create_user(username,PASSWORD,role,must_change=False)
        for c,username in ((admin,'admin'),(viewer,'viewer'),(auditor,'auditor')):
            r=c.post('/api/auth/login',json={'username':username,'password':PASSWORD})
            assert r.status_code==200,r.text
            c.headers['X-CSRF-Token']=r.json()['csrf_token']
        assert admin.patch('/api/policies/STALE_AGENT',json={'enabled':False}).status_code==200
        assert admin.post('/api/policies/evaluate').status_code==200
        assert viewer.get('/api/policies').status_code==200
        assert auditor.get('/api/policies').status_code==200
        assert auditor.get('/api/policies/findings').status_code==200
        assert auditor.get('/api/policies/runs').status_code==200
        assert viewer.post('/api/policies/evaluate').status_code==403
        assert viewer.patch('/api/policies/STALE_AGENT',json={'enabled':True}).status_code==403
        assert auditor.patch('/api/policies/STALE_AGENT',json={'severity':'high'}).status_code==403
        assert auditor.post('/api/policies/evaluate').status_code==403
        assert 'governance.manage' not in rbac.effective_capabilities('business_owner')
        assert 'governance.remediate' not in rbac.effective_capabilities('auditor')
        assert 'agents.approve' not in rbac.effective_capabilities('admin')


def test_remediation_notes_do_not_suppress_findings(client):
    agent=client.post('/api/agents',json={'name':'Remediation Candidate','provider':'Custom'}).json()
    aid=agent['id']
    assert client.post('/api/policies/evaluate').status_code==200
    path=f'/api/policies/findings/{aid}/MISSING_OWNER/remediation'
    assert client.patch(path,json={'note':'too short'}).status_code==422
    assert client.patch(path,json={'note':'Research owner assignment and update directory mapping',
                                   'due_date':'2026-99-99'}).status_code==422
    resp=client.patch(path,json={'note':'Research owner assignment and update directory mapping',
                                 'due_date':'2027-01-15'})
    assert resp.status_code==200,resp.text
    assert resp.json()['status']=='open'
    result=next(f for f in client.get('/api/policies/findings').json() if f['policy_code']=='MISSING_OWNER')
    assert result['status']=='open'
    assert result['remediation_due_date']=='2027-01-15'
    assert 'Research owner assignment' in result['remediation_note']
    client.post('/api/policies/evaluate')
    assert next(f for f in client.get('/api/policies/findings').json() if f['policy_code']=='MISSING_OWNER')['remediation_note']
    assert 'policy.finding.remediation.update' in {f['operation'] for f in client.get('/api/audit').json()}
