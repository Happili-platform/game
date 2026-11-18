# SPDX-License-Identifier: AGPL-3.0-only
"""Business cost approvals must never be performed by technical administrators."""
import json
import pytest
from fastapi.testclient import TestClient
from game.main import app
from game import rbac, local_accounts
from game.db import connection

PW = 'Strong-Local-Testing-Password-2026!'

@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv('GAME_DB_PATH', str(tmp_path/'company.db'))
    monkeypatch.setenv('GAME_VAULT_KEY_PATH', str(tmp_path/'key'))
    monkeypatch.setenv('GAME_AUTH_MODE', 'password')
    with TestClient(app) as admin, TestClient(app) as owner, TestClient(app) as other:
        admin_user=local_accounts.create_user('admin', PW,'admin', must_change=False)
        owner_user=local_accounts.create_user('business', PW,'business_owner', must_change=False)
        other_user=local_accounts.create_user('another', PW,'business_owner', must_change=False)
        for c,username in ((admin,'admin'),(owner,'business'),(other,'another')):
            login=c.post('/api/auth/login',json={'username':username,'password':PW})
            assert login.status_code==200, login.text
            c.headers['X-CSRF-Token']=login.json()['csrf_token']
        yield admin,owner,other,admin_user,owner_user,other_user


def test_business_owner_exclusive_signoff_and_audit(environment):
    admin,owner,other,_,owner_u,_=environment
    # A technical admin cannot mark an agent approved during registration.
    assert admin.post('/api/agents',json={'name':'Billing Bot','provider':'Custom',
                        'approval_status':'approved'}).status_code==422
    response=admin.post('/api/agents',json={'name':'Billing Bot','provider':'Custom',
        'environment':'production','budget_usd':180,'cost_center':'FIN-001'})
    assert response.status_code==201,response.text
    agent_id=response.json()['id']
    assert response.json()['approval_status']=='not_reviewed'
    assert admin.post(f'/api/agents/{agent_id}/approval-decision',json={
        'decision':'approved','reason':'Approved from technical user'}).status_code==403
    assert admin.post(f'/api/agents/{agent_id}/approval-request',json={
        'justification':'Proposed to automate invoices','requested_budget_usd':180,'cost_center':'FIN-001'}).status_code==409
    set_owner=admin.post(f'/api/agents/{agent_id}/business-owner',json={'owner_user_id':owner_u['id']})
    assert set_owner.status_code==200,set_owner.text
    assert [a['id'] for a in owner.get('/api/agents').json()]==[agent_id]
    submitted=admin.post(f'/api/agents/{agent_id}/approval-request',json={
        'justification':'Automate monthly financial invoice triage.','requested_budget_usd':180,'cost_center':'FIN-001'})
    assert submitted.status_code==200,submitted.text
    assert submitted.json()['approval_status']=='pending'
    assert other.post(f'/api/agents/{agent_id}/approval-decision',json={
        'decision':'approved','reason':'Not authorized for this agent'}).status_code==404
    resp=owner.post(f'/api/agents/{agent_id}/approval-decision',json={
        'decision':'approved','reason':'Authorized for FIN-001 within 180 USD budget'})
    assert resp.status_code==200,resp.text
    detail=admin.get('/api/agents/'+agent_id).json()
    assert detail['approval_status']=='approved'
    assert detail['approved_budget_usd']==180
    assert detail['approval_requested_cost_center']=='FIN-001'
    assert detail['business_owner_name']=='business'
    assert 'PRODUCTION_NOT_APPROVED' not in {f['code'] for f in detail['findings']}
    assert owner.get('/api/audit').status_code==403
    audit=admin.get('/api/audit').json()
    kinds={e['operation'] for e in audit}
    assert {'agent.business_owner.assign','agent.approval.submit','agent.approval.approved'} <= kinds
    decision=next(e for e in audit if e['operation']=='agent.approval.approved')
    assert json.loads(decision['details_json'])['requested_budget_usd']==180
    assert 'secret_access_key' not in json.dumps(audit)


def test_reject_and_reassign_revokes_old_owner_scope(environment):
    admin,owner,other,_,owner_u,other_u=environment
    id=admin.post('/api/agents',json={'name':'Support agent','provider':'Custom'}).json()['id']
    admin.post(f'/api/agents/{id}/business-owner',json={'owner_user_id':owner_u['id']})
    admin.post(f'/api/agents/{id}/approval-request',json={'justification':'Needed for staff support requests','requested_budget_usd':0,'cost_center':'OPS-001'})
    assert owner.post(f'/api/agents/{id}/approval-decision',json={
        'decision':'rejected','reason':'Costs and business benefits are not justified'}).status_code==200
    assert admin.get('/api/agents/'+id).json()['approval_status']=='rejected'
    assert admin.post(f'/api/agents/{id}/business-owner',json={'owner_user_id':other_u['id']}).status_code==200
    assert owner.get(f'/api/agents/{id}').status_code==404
    assert other.get(f'/api/agents/{id}').status_code==200
    assert admin.get('/api/agents/'+id).json()['approval_status']=='not_reviewed'


def test_role_inheritance_excludes_business_signoff_for_admin():
    assert 'agents.approve' not in rbac.effective_capabilities('admin')
    assert 'agents.approve' in rbac.effective_capabilities('business_owner')
    assert 'members.manage' not in rbac.effective_capabilities('business_owner')
    assert 'connections.manage' not in rbac.effective_capabilities('business_owner')
    assert 'audit.view' in rbac.effective_capabilities('auditor')


def test_user_records_and_sessions_migration(tmp_path, monkeypatch):
    # Simulate a pre-upgrade database whose local_users CHECK excludes business_owner.
    from game.db import initialize, db_path, connection
    import sqlite3
    path=tmp_path/'old.db'
    monkeypatch.setenv('GAME_DB_PATH',str(path))
    initialize()
    # Recreate old user CHECK for this test, leaving actual sessions and IDs in place.
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('''CREATE TABLE local_users_old (
          id TEXT PRIMARY KEY,username TEXT NOT NULL UNIQUE COLLATE NOCASE,
          display_name TEXT NOT NULL DEFAULT '',email TEXT NOT NULL DEFAULT '',password_hash TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('admin','provider_admin','agent_owner','auditor','viewer')),
          scope_json TEXT NOT NULL DEFAULT '{"kind":"all"}',active INTEGER NOT NULL DEFAULT 1,
          must_change_password INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,
          password_changed_at TEXT,last_login_at TEXT)''')
        db.execute('DROP TABLE local_users')
        db.execute('ALTER TABLE local_users_old RENAME TO local_users')
        db.commit()
    admin=local_accounts.create_user('oldadmin',PW,'admin',must_change=False)
    token,csrf=local_accounts.start_session(admin['id'])
    initialize()
    with connection() as db:
        row=db.execute('SELECT id,role FROM local_users WHERE id=?',(admin['id'],)).fetchone()
        assert row['role']=='admin'
        assert db.execute('SELECT count(*) FROM local_sessions WHERE user_id=?',(admin['id'],)).fetchone()[0]==1
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert local_accounts.create_user('financeowner',PW,'business_owner')['role']=='business_owner'
    initialize()  # repeat migration must be safe


def test_recorded_spend_uses_business_approved_budget(environment):
    admin,owner,_,_,owner_u,_=environment
    a=admin.post('/api/agents',json={'name':'Spending check','provider':'Custom',
        'owner_email':'tech@example.com','budget_usd':100}).json()
    aid=a['id']
    admin.post(f'/api/agents/{aid}/business-owner',json={'owner_user_id':owner_u['id']})
    admin.post(f'/api/agents/{aid}/approval-request',json={
        'justification':'Keep customer agent monthly operational cost controlled',
        'requested_budget_usd':5,'cost_center':'FIN-005'})
    owner.post(f'/api/agents/{aid}/approval-decision',json={
        'decision':'approved','reason':'Approved for small monthly cost only'})
    admin.post('/api/usage',json={'agent_id':aid,'cost_usd':7})
    detail=admin.get(f'/api/agents/{aid}').json()
    assert detail['approved_budget_usd']==5
    assert 'OVER_BUDGET' in {f['code'] for f in detail['findings']}
