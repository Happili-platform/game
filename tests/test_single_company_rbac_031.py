# SPDX-License-Identifier: AGPL-3.0-only
"""Role inheritance is automatic; scopes and permissions must be checked server-side."""
import pytest
from fastapi.testclient import TestClient
from game import auth, rbac
from game.db import connection, initialize, iso, utc_now
from game.main import app

ISSUER = 'https://identity.example.test/tenant'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('GAME_DB_PATH', str(tmp_path/'company.db'))
    monkeypatch.setenv('GAME_VAULT_KEY_PATH', str(tmp_path/'key'))
    monkeypatch.setenv('GAME_DEMO_DATA', 'false')
    monkeypatch.setenv('GAME_AUTH_MODE', 'oidc')
    monkeypatch.setenv('GAME_OIDC_ISSUER', ISSUER)
    monkeypatch.setattr(auth, '_oidc_claims', lambda request: (ISSUER, request.headers.get('x-test-user','none')))
    with TestClient(app) as c:
        with connection() as db:
            db.execute('INSERT OR IGNORE INTO tenants(id,name,created_at) VALUES (?,?,?)', ('test-company','Test Company',iso(utc_now())))
            db.execute("INSERT INTO tenant_memberships (tenant_id,issuer,subject,role,scope_json) VALUES (?,?,?,?,?)",
                       ('test-company',ISSUER,'admin','admin','{"kind":"all"}'))
        yield c


def h(who):
    return {'x-test-user':who}


def aws(label):
    return {'provider':'aws_agentcore','label':label,'scope':{'region':'us-west-2'},
            'env_prefix':'AC_AWS','auth_mode':'aws_assume_role',
            'auth_config':{'role_arn':'arn:aws:iam::123456789012:role/Discovery'}}


def grant(c, name, role, scope):
    resp=c.post('/api/members',headers=h('admin'),json={
        'issuer':ISSUER,'subject':name,'role':role,'scope':scope})
    assert resp.status_code==201,resp.text


def test_role_inheritance_capability_closure():
    assert rbac.inherited_roles('admin') == {'admin','provider_admin','agent_owner','viewer','auditor'}
    assert rbac.inherited_roles('provider_admin') == {'provider_admin','agent_owner','viewer'}
    assert rbac.inherited_roles('auditor') == {'auditor','viewer'}
    assert rbac.inherited_roles('agent_owner') == {'agent_owner','viewer'}
    admin=rbac.effective_capabilities('admin')
    assert set(rbac.CAPABILITIES)-{'agents.approve','costs.view'}==admin
    assert 'agents.approve' not in admin  # Business Owner sign-off must remain separate
    assert {'connections.manage','connections.discover','connections.view','agents.view'} <= admin
    assert 'connections.manage' not in rbac.effective_capabilities('agent_owner')
    assert 'agents.register' not in rbac.effective_capabilities('auditor')
    assert 'audit.view' not in rbac.effective_capabilities('provider_admin')
    assert rbac.effective_capabilities('tenant_admin')==admin  # v0.3 migration alias


def test_scope_restricts_inventory_connections_and_agent_updates(client):
    c=client
    a=c.post('/api/connections',headers=h('admin'),json=aws('Finance AWS')).json()
    b=c.post('/api/connections',headers=h('admin'),json=aws('Operations AWS')).json()
    a1=c.post('/api/agents',headers=h('admin'),json={
        'name':'Finance agent','provider':'aws_agentcore','connection_id':a['id']}).json()
    b1=c.post('/api/agents',headers=h('admin'),json={
        'name':'Operations agent','provider':'aws_agentcore','connection_id':b['id']}).json()
    grant(c,'viewer-finance','viewer',{'kind':'selected','connection_ids':[a['id']],'agent_ids':[]})
    assert [x['id'] for x in c.get('/api/connections',headers=h('viewer-finance')).json()]==[a['id']]
    assert [x['id'] for x in c.get('/api/agents',headers=h('viewer-finance')).json()]==[a1['id']]
    assert c.get('/api/agents/'+b1['id'],headers=h('viewer-finance')).status_code==404
    assert c.post('/api/agents',headers=h('viewer-finance'),json={'name':'No edit','provider':'aws_agentcore'}).status_code==403
    assert c.post('/api/connections/'+b['id']+'/test',headers=h('viewer-finance')).status_code==403
    grant(c,'owner-finance','agent_owner',{'kind':'selected','connection_ids':[a['id']],'agent_ids':[]})
    assert c.post('/api/agents',headers=h('owner-finance'),json={
        'name':'Another finance agent','provider':'aws_agentcore','connection_id':a['id']}).status_code==201
    assert c.post('/api/agents',headers=h('owner-finance'),json={
        'name':'Forbidden operations agent','provider':'aws_agentcore','connection_id':b['id']}).status_code==404
    assert c.post('/api/agents',headers=h('owner-finance'),json={
        'name':'Orphan record','provider':'aws_agentcore'}).status_code==403
    assert c.post('/api/usage',headers=h('owner-finance'),json={'agent_id':b1['id'],'cost_usd':1}).status_code==404


def test_provider_admin_scope_and_auditor_read_only(client):
    c=client
    a=c.post('/api/connections',headers=h('admin'),json=aws('Finance')).json()
    b=c.post('/api/connections',headers=h('admin'),json=aws('Marketing')).json()
    grant(c,'padmin','provider_admin',{'kind':'selected','connection_ids':[a['id']],'agent_ids':[]})
    assert c.post('/api/connections',headers=h('padmin'),json=aws('Extra')).status_code==403
    assert c.get('/api/connections',headers=h('padmin')).status_code==200
    assert c.patch('/api/connections/'+b['id'],headers=h('padmin'),json={
        'label':'Nope','scope':{'region':'us-west-2'},'env_prefix':'AC_AWS',
        'auth_mode':'aws_assume_role','auth_config':{'role_arn':'arn:aws:iam::123456789012:role/Discovery'}}).status_code==404
    grant(c,'auditor','auditor',{'kind':'all'})
    assert c.get('/api/audit',headers=h('auditor')).status_code==200
    assert c.get('/api/agents',headers=h('auditor')).status_code==200
    assert c.post('/api/agents',headers=h('auditor'),json={'name':'Not allowed','provider':'aws_agentcore'}).status_code==403
    assert c.post('/api/connections',headers=h('auditor'),json=aws('Not allowed')).status_code==403
    assert c.get('/api/members',headers=h('auditor')).status_code==403


def test_admin_and_auditor_must_be_company_wide_and_last_admin_protected(client):
    c=client
    restricted={'kind':'selected','connection_ids':[],'agent_ids':[]}
    for role in ('admin','auditor'):
        assert c.post('/api/members',headers=h('admin'),json={
            'issuer':ISSUER,'subject':'invalid-'+role,'role':role,'scope':restricted}).status_code==422
    assert c.post('/api/members',headers=h('admin'),json={
        'issuer':ISSUER,'subject':'admin','role':'viewer','scope':restricted}).status_code==409
    assert c.post('/api/members/revoke',headers=h('admin'),json={'issuer':ISSUER,'subject':'admin'}).status_code==409
    assert c.post('/api/members',headers=h('admin'),json={
        'issuer':ISSUER,'subject':'bad-scope','role':'viewer',
        'scope':{'kind':'selected','connection_ids':['conn-foreign'],'agent_ids':[]}}).status_code==422


def test_empty_install_role_catalog_and_frontend(client):
    c=client
    assert c.get('/api/agents',headers=h('admin')).json()==[]
    assert c.get('/api/connections',headers=h('admin')).json()==[]
    catalog=c.get('/api/rbac/catalog',headers=h('admin')).json()
    assert len(catalog['roles'])==6
    admin=next(r for r in catalog['roles'] if r['id']=='admin')
    assert 'viewer' in admin['effective_roles']
    assert 'connections.discover' in admin['capabilities']
    assert 'users' in c.get('/').text.lower()
    assert 'renderInheritedPermissions' in c.get('/static/app.js').text


def test_legacy_members_survive_schema_migration(client):
    c=client
    with connection() as db:
        schema=db.execute("SELECT sql FROM sqlite_master WHERE name='tenant_memberships'").fetchone()[0]
    assert "'provider_admin'" in schema
    assert c.get('/api/me',headers=h('admin')).json()['role']=='admin'
    assert 'members.manage' in c.get('/api/me',headers=h('admin')).json()['capabilities']
