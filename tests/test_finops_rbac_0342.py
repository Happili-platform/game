# SPDX-License-Identifier: AGPL-3.0-only
"""Financial authorization, local permission editing and separation of duties."""
import pytest
from fastapi.testclient import TestClient
from game import rbac
from game.db import connection
from game.main import app
from game.local_accounts import create_user

TOKEN='collector-token-for-finops-rbac-0342-0123456789'
PASS='CorrectHorseBatteryStaple5342!'

@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setenv('GAME_DB_PATH',str(tmp_path/'db.sqlite'))
    monkeypatch.setenv('GAME_VAULT_KEY_PATH',str(tmp_path/'master.key'))
    monkeypatch.setenv('GAME_AUTH_MODE','password')
    monkeypatch.setenv('GAME_RUNTIME_INGEST_TOKEN',TOKEN)
    with TestClient(app) as admin, TestClient(app) as viewer, TestClient(app) as owner, TestClient(app) as auditor:
        admin_user=create_user('admin',PASS,'admin',scope={'kind':'all'},must_change=False)
        viewer_user=create_user('viewer',PASS,'viewer',scope={'kind':'all'},must_change=False)
        owner_user=create_user('business',PASS,'business_owner',scope={'kind':'selected','agent_ids':[],'connection_ids':[]},must_change=False)
        auditor_user=create_user('auditor',PASS,'auditor',scope={'kind':'all'},must_change=False)
        cs={}
        for client,name in ((admin,'admin'),(viewer,'viewer'),(owner,'business'),(auditor,'auditor')):
            r=client.post('/api/auth/login',json={'username':name,'password':PASS})
            assert r.status_code==200,r.text
            cs[name]={'x-csrf-token':r.json()['csrf_token']}
        yield {'admin':admin,'viewer':viewer,'business':owner,'auditor':auditor,'csrf':cs,'ids':(admin_user['id'],viewer_user['id'],owner_user['id'],auditor_user['id'])}


def test_split_financial_permissions_and_navigation_data(setup):
    admin,viewer,business,auditor=[setup[k] for k in ('admin','viewer','business','auditor')]
    assert viewer.get('/api/runtime/runs').status_code==403
    assert viewer.get('/api/finops/summary').status_code==403
    assert viewer.get('/api/finops/azure-costs').status_code==403
    assert business.get('/api/finops/summary').status_code==200
    assert business.get('/api/finops/azure-costs').status_code==403
    assert auditor.get('/api/finops/azure-costs').status_code==200
    assert admin.get('/api/finops/azure-costs').status_code==200
    a=admin.post('/api/agents',headers=setup['csrf']['admin'],json={'name':'Finance operations','provider':'azure_foundry_logs','budget_usd':55}).json()
    assert viewer.get('/api/agents').json()[0]['monthly_spend_usd'] is None
    assert viewer.get('/api/overview').json()['totals']['monthly_spend_usd'] is None
    assert viewer.get('/api/agents/'+a['id']).json()['budget_usd'] is None


def test_local_edit_permissions_enforces_dependency_and_role_ceiling(setup):
    admin=setup['admin']; viewer=setup['viewer']; vid=setup['ids'][1]
    csrf=setup['csrf']['admin']
    # The existing user can be elevated by selecting a higher role.
    role_caps=sorted(rbac.effective_capabilities('agent_owner'))
    response=admin.patch('/api/local-users/'+vid,headers=csrf,json={'role':'agent_owner','scope':{'kind':'all'},'capabilities':role_caps})
    assert response.status_code==200,response.text
    assert viewer.get('/api/runtime/summary').status_code==200
    assert viewer.get('/api/finops/summary').status_code==200
    assert viewer.get('/api/finops/azure-costs').status_code==403
    # Custom selection cannot grant permission outside selected primary role.
    bad=admin.patch('/api/local-users/'+vid,headers=csrf,json={'capabilities':role_caps+['finops.billing.view']})
    assert bad.status_code==422
    # A dependent grant must include all lower prerequisites; API refuses invalid checkbox sets.
    bad=admin.patch('/api/local-users/'+vid,headers=csrf,json={'capabilities':['finops.estimates.view']})
    assert bad.status_code==422
    # Valid selective removal immediately affects an already authenticated session.
    subset=sorted(rbac.effective_capabilities('agent_owner')-{'finops.estimates.view','finops.usage.view','runtime.view'})
    ok=admin.patch('/api/local-users/'+vid,headers=csrf,json={'capabilities':subset})
    assert ok.status_code==200,ok.text
    assert viewer.get('/api/finops/summary').status_code==403
    assert viewer.get('/api/runtime/summary').status_code==403
    assert set(viewer.get('/api/me').json()['capabilities'])==set(subset)
    assert set(next(x for x in admin.get('/api/local-users').json() if x['id']==vid)['capabilities'])==set(subset)


def test_technical_admin_cannot_gain_business_approval_or_remove_last_admin_permission(setup):
    admin=setup['admin']; csrf=setup['csrf']['admin']; aid=setup['ids'][0]
    assert 'agents.approve' not in admin.get('/api/me').json()['capabilities']
    assert 'agents.approve' not in rbac.effective_capabilities('admin')
    caps=sorted(rbac.effective_capabilities('admin'))
    response=admin.patch('/api/local-users/'+aid,headers=csrf,json={'capabilities':caps+['agents.approve']})
    assert response.status_code==422
    response=admin.patch('/api/local-users/'+aid,headers=csrf,json={'capabilities':[x for x in caps if x!='members.manage']})
    assert response.status_code==422
