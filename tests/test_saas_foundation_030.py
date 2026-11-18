# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant isolation, identity boundaries and renewable cloud adapter contracts."""
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

from game import auth, connectors
from game.db import connection, initialize, iso, utc_now
from game.main import app

ISSUER = 'https://login.example.test/tenant'


@pytest.fixture
def multi_client(tmp_path, monkeypatch):
    monkeypatch.setenv('GAME_DB_PATH', str(tmp_path / 'tenants.db'))
    monkeypatch.setenv('GAME_VAULT_KEY_PATH', str(tmp_path / 'vault' / 'key'))
    monkeypatch.setenv('GAME_DEMO_DATA', 'false')
    monkeypatch.setenv('GAME_AUTH_MODE', 'oidc')
    monkeypatch.setenv('GAME_OIDC_ISSUER', ISSUER)
    monkeypatch.setattr(auth, '_oidc_claims', lambda request: (ISSUER, request.headers.get('x-test-subject', 'nobody')))
    with TestClient(app) as client:
        with connection() as db:
            for tenant in ('company-a', 'company-b'):
                db.execute('INSERT INTO tenants(id,name,created_at) VALUES(?,?,?)', (tenant, tenant, iso(utc_now())))
            for tenant, subject, role in (
                ('company-a', 'admin-a', 'tenant_admin'),
                ('company-a', 'analyst-a', 'analyst'),
                ('company-a', 'read-a', 'viewer'),
                ('company-b', 'admin-b', 'tenant_admin'),
                ('company-b', 'read-b', 'viewer'),
                ('company-a', 'shared', 'viewer'),
                ('company-b', 'shared', 'analyst'),
            ):
                db.execute('INSERT INTO tenant_memberships(tenant_id,issuer,subject,role) VALUES(?,?,?,?)',
                           (tenant, ISSUER, subject, role))
        yield client


def authheaders(sub, tenant=None):
    result = {'x-test-subject': sub}
    if tenant:
        result['x-game-tenant'] = tenant
    return result


def agent_data(name):
    return {'name': name, 'provider': 'Custom / Python', 'environment': 'production'}


def aws_connection(label='AWS customer', account='123456789012'):
    return {'provider': 'aws_agentcore', 'label': label, 'env_prefix': 'AC_AWS',
            'scope': {'region': 'us-west-2'}, 'auth_mode': 'aws_assume_role',
            'auth_config': {'role_arn': f'arn:aws:iam::{account}:role/GAMEDiscoveryRole'}}


def test_migrated_local_records_are_in_local_tenant(tmp_path, monkeypatch):
    monkeypatch.setenv('GAME_DB_PATH', str(tmp_path / 'migration.db'))
    monkeypatch.setenv('GAME_DEMO_DATA', 'false')
    # Old v0.2 schema without tenant_id; ensure idempotent in-place migration.
    with sqlite3.connect(os.environ['GAME_DB_PATH']) as raw:
        raw.execute('''CREATE TABLE provider_connections(id TEXT PRIMARY KEY, provider TEXT, label TEXT,
            scope_json TEXT, env_prefix TEXT, created_at TEXT, last_synced_at TEXT, last_error TEXT)''')
        raw.execute('''CREATE TABLE discovered_agents(id TEXT PRIMARY KEY, connection_id TEXT, external_id TEXT,
            name TEXT, provider TEXT, description TEXT, provider_status TEXT, owner_email TEXT,
            environment TEXT, approval_status TEXT, lifecycle_status TEXT, cost_center TEXT,
            budget_usd REAL, sensitive_access INTEGER, last_seen TEXT, discovered_at TEXT,
            discovery_last_seen TEXT, source TEXT, created_at TEXT)''')
        raw.execute('''CREATE TABLE provider_credentials(connection_id TEXT PRIMARY KEY, encrypted_json TEXT,
            saved_at TEXT, rotated_at TEXT, expires_at TEXT)''')
        raw.execute('''CREATE TABLE agents(id TEXT PRIMARY KEY, name TEXT, provider TEXT, description TEXT,
            owner_email TEXT, environment TEXT, approval_status TEXT, lifecycle_status TEXT,
            cost_center TEXT, budget_usd REAL, sensitive_access INTEGER, last_seen TEXT, source TEXT,
            created_at TEXT)''')
        raw.execute('''CREATE TABLE usage_events(id TEXT PRIMARY KEY,agent_id TEXT, occurred_at TEXT,
            cost_usd REAL,input_tokens INTEGER,output_tokens INTEGER,outcome TEXT,source TEXT)''')
        raw.execute("INSERT INTO provider_connections(id,provider,label,scope_json,env_prefix,created_at) VALUES (?,?,?,?,?,?)",
                    ('conn-old', 'aws_agentcore','My AWS','{"region":"us-west-2"}','AC_AWS','2026-11-03'))
    initialize()
    initialize()
    with connection() as db:
        row = db.execute("SELECT tenant_id,auth_mode FROM provider_connections WHERE id='conn-old'").fetchone()
        assert tuple(row) == ('local-dev', 'legacy')
        assert db.execute('SELECT COUNT(*) FROM tenants WHERE id=?', ('local-dev',)).fetchone()[0] == 1


def test_cross_tenant_registry_and_provider_isolation(multi_client, monkeypatch):
    c = multi_client
    a = authheaders('admin-a')
    b = authheaders('admin-b')
    other = c.post('/api/agents', json=agent_data('Company A private agent'), headers=a)
    assert other.status_code == 201, other.text
    agent = other.json()['id']
    other = c.post('/api/connections', json=aws_connection(), headers=a)
    assert other.status_code == 201, other.text
    conn_a = other.json()['id']
    assert len(other.json()['auth_config']['external_id']) >= 30
    assert c.get('/api/agents', headers=b).json() == []
    assert c.get('/api/connections', headers=b).json() == []
    assert c.get('/api/agents/' + agent, headers=b).status_code == 404
    assert c.patch('/api/connections/' + conn_a, json={
        'label': 'Changed', 'env_prefix': 'AC_AWS', 'scope': {'region':'us-west-2'},
        'auth_mode': 'aws_assume_role', 'auth_config': {'role_arn': aws_connection()['auth_config']['role_arn']}},
        headers=b).status_code == 404
    assert c.post('/api/connections/'+conn_a+'/discover', headers=b).status_code == 404
    assert c.post('/api/connections/'+conn_a+'/test', headers=b).status_code == 404
    assert c.delete('/api/connections/'+conn_a, headers=b).status_code == 404
    assert c.post('/api/usage', json={'agent_id': agent, 'cost_usd': 2}, headers=b).status_code == 404
    # Tenant A still sees all its data.
    assert len(c.get('/api/agents', headers=a).json()) == 1
    assert len(c.get('/api/connections', headers=a).json()) == 1
    assert c.get('/api/audit', headers=a).status_code == 200
    assert c.get('/api/audit', headers=b).json() == []


def test_role_permissions_and_multiple_memberships(multi_client):
    c = multi_client
    a = authheaders('admin-a')
    viewer = authheaders('read-a')
    analyst = authheaders('analyst-a')
    assert c.post('/api/agents', json=agent_data('Not allowed'), headers=viewer).status_code == 403
    assert c.post('/api/connections', json=aws_connection(), headers=viewer).status_code == 403
    assert c.post('/api/connections', json=aws_connection(), headers=analyst).status_code == 403
    assert c.get('/api/audit', headers=viewer).status_code == 403
    assert c.post('/api/agents', json=agent_data('Analyst permitted'), headers=analyst).status_code == 201
    assert c.get('/api/me', headers=authheaders('nobody')).status_code == 403
    assert c.get('/api/me', headers=authheaders('shared')).status_code == 400
    assert c.get('/api/me', headers=authheaders('shared','company-b')).json()['role'] == 'analyst'
    assert c.get('/api/me', headers=authheaders('admin-a', 'company-b')).status_code == 403
    assert c.post('/api/members', headers=a, json={'issuer': ISSUER, 'subject':'staff', 'role':'viewer'}).status_code == 201
    assert c.get('/api/me', headers=authheaders('staff')).json()['tenant_id'] == 'company-a'


def test_external_id_is_generated_isolated_and_stable_on_edit(multi_client):
    c=multi_client
    a=authheaders('admin-a'); b=authheaders('admin-b')
    one=c.post('/api/connections', headers=a, json=aws_connection('First')).json()
    two=c.post('/api/connections', headers=b, json=aws_connection('Second')).json()
    ext1=one['auth_config']['external_id']; ext2=two['auth_config']['external_id']
    assert ext1 and ext2 and ext1 != ext2
    body={'label':'First edited','scope':{'region':'us-west-2'},'env_prefix':'AC_AWS',
          'auth_mode':'aws_assume_role', 'auth_config':{'role_arn':aws_connection()['auth_config']['role_arn']}}
    changed=c.patch('/api/connections/'+one['id'], headers=a, json=body)
    assert changed.status_code==200,changed.text
    assert changed.json()['auth_config']['external_id']==ext1
    body['auth_config']['external_id']='malicious-fixed-id'
    assert c.patch('/api/connections/'+one['id'], headers=a, json=body).status_code==422
    assert c.put('/api/connections/'+one['id']+'/credentials', headers=a,
                 json={'access_key_id':'X','secret_access_key':'Y','session_token':'Z'}).status_code==403  # OIDC mode disallows local secret paste


def test_aws_sts_assumed_anew_each_discovery(monkeypatch):
    import boto3
    class FakeSts:
        def assume_role(self, **kwargs):
            calls.append(kwargs)
            return {'Credentials': {'AccessKeyId':'TMP', 'SecretAccessKey':'TMP-SECRET','SessionToken':'TMP-TOKEN'}}
        def close(self): pass
    class FakeRuntime:
        def list_agent_runtimes(self, **kwargs): return {'agentRuntimes': [{'agentRuntimeName':'smoke', 'agentRuntimeArn':'arn:runtime'}]}
        def close(self): pass
    calls=[]
    def session(*a, **kw):
        if 'aws_access_key_id' in kw:
            assert kw['aws_access_key_id']=='TMP'
        class Client:
            def client(self, name):
                return FakeSts() if name=='sts' else FakeRuntime()
        return Client()
    monkeypatch.setattr(boto3, 'Session', session)
    conn={'id':'conn-test-sts', 'provider':'aws_agentcore','env_prefix':'AC_AWS',
          'scope':{'region':'us-west-2'}, 'auth_mode':'aws_assume_role',
          'auth_config':{'role_arn':'arn:aws:iam::123456789012:role/Reader','external_id':'random-generated-external-id'}}
    assert len(connectors.discover(conn))==1
    assert len(connectors.discover(conn))==1
    assert len(calls)==2
    assert all(x['ExternalId']=='random-generated-external-id' for x in calls)
    assert all(x['DurationSeconds']==900 for x in calls)


def test_provider_auth_modes_validate_target_only():
    assert connectors.validate_auth_config('microsoft_foundry','entra_shared_app',
        {'tenant_id':'00000000-0000-0000-0000-000000000000'})[0] == 'entra_shared_app'
    assert connectors.validate_auth_config('google_agent_engine','google_impersonate',
        {'service_account_email':'discovery-bot@project-123456.iam.gserviceaccount.com'})[0] == 'google_impersonate'
    with pytest.raises(ValueError):
        connectors.validate_auth_config('google_agent_engine','google_impersonate',
            {'service_account_email':'test@evil.org', 'credential_source':'http://localhost/metadata'})


def test_private_registry_ingestion_is_tenant_scoped(multi_client):
    client=multi_client
    a=authheaders('admin-a'); b=authheaders('admin-b')
    created=client.post('/api/connections', headers=a, json={
        'provider':'custom_registry', 'label':'Self-hosted agents',
        'scope':{'registry_name':'internal-platform'}, 'env_prefix':'AC_PRIVATE',
        'auth_mode':'push_oidc','auth_config':{}
    })
    assert created.status_code==201,created.text
    connection_id=created.json()['id']
    url=f'/api/connections/{connection_id}/ingest'
    payload={'agents':[{'external_id':'hosted/internal-agent-1', 'name':'Internal Ops Agent',
                        'owner_email':'platform@example.test','provider_status':'running'}]}
    assert client.post(url, headers=b, json=payload).status_code==404
    ingested=client.post(url, headers=a, json=payload)
    assert ingested.status_code==200,ingested.text
    assert ingested.json()['ingested']==1
    assert client.post(url, headers=a, json=payload).status_code==200
    assert len(client.get('/api/agents',headers=a).json())==1
    assert client.get('/api/agents',headers=b).json()==[]
    assert client.get('/api/connections',headers=b).json()==[]
    assert client.post(url, headers=a, json={'agents':[payload['agents'][0], payload['agents'][0]]}).status_code==422
    assert client.post(f'/api/connections/{connection_id}/discover', headers=a).status_code==409
    assert client.post(f'/api/connections/{connection_id}/test', headers=a).status_code==409


def test_member_revoke_restricts_access(multi_client):
    c=multi_client
    admin=authheaders('admin-a')
    viewer=authheaders('read-a')
    assert c.get('/api/me',headers=viewer).status_code==200
    assert c.post('/api/members/revoke',headers=admin,json={'issuer':ISSUER,'subject':'read-a'}).status_code==200
    assert c.get('/api/me',headers=viewer).status_code==403
    assert c.post('/api/members/revoke',headers=admin,json={'issuer':ISSUER,'subject':'admin-a'}).status_code==409


def test_oidc_signature_issuer_audience_and_expiry(monkeypatch, tmp_path):
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from fastapi import Request
    from datetime import datetime, timezone, timedelta
    from types import SimpleNamespace

    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    class FakeJWKS:
        def get_signing_key_from_jwt(self, token):
            return SimpleNamespace(key=key.public_key())
    monkeypatch.setattr(auth, '_get_jwk_client', lambda url: FakeJWKS())
    monkeypatch.setenv('GAME_OIDC_ISSUER', ISSUER)
    monkeypatch.setenv('GAME_OIDC_AUDIENCE', 'game-test-api')
    monkeypatch.setenv('GAME_OIDC_JWKS_URL', 'https://keys.example.test/jwks')

    def check(claims):
        token=jwt.encode(claims,key,algorithm='RS256',headers={'kid':'test-key'})
        req=Request({'type':'http','method':'GET','scheme':'https','path':'/api/me',
            'headers':[(b'authorization',f'Bearer {token}'.encode())],
            'client':('10.0.0.2',10000),'server':('game.example.test',443)})
        return auth._oidc_claims(req)
    now=datetime.now(timezone.utc)
    good={'iss':ISSUER,'sub':'real-user-sub','aud':'game-test-api',
          'iat':int(now.timestamp()),'exp':int((now+timedelta(minutes=5)).timestamp())}
    assert check(good)==(ISSUER,'real-user-sub')
    for bad in [dict(good,aud='other-api'),dict(good,iss='https://evil.example.test'),
                dict(good,exp=int((now-timedelta(minutes=4)).timestamp()))]:
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            check(bad)
        assert e.value.status_code==401


def test_google_impersonation_uses_host_adc(monkeypatch):
    import io
    import json
    from urllib import request as urllib_request
    import sys, types
    google = types.ModuleType('google');google.__path__=[]
    ga = types.ModuleType('google.auth');ga.__path__=[]
    transport=types.ModuleType('google.auth.transport');transport.__path__=[]
    requests=types.ModuleType('google.auth.transport.requests');requests.Request=lambda:object()
    oauth2=types.ModuleType('google.oauth2');oauth2.__path__=[]
    service_account=types.ModuleType('google.oauth2.service_account')
    impersonated_credentials=types.ModuleType('google.auth.impersonated_credentials')
    google.auth=ga;ga.transport=transport;ga.impersonated_credentials=impersonated_credentials
    transport.requests=requests;google.oauth2=oauth2;oauth2.service_account=service_account
    for name,module in {'google':google,'google.auth':ga,'google.auth.transport':transport,
        'google.auth.transport.requests':requests,'google.oauth2':oauth2,
        'google.oauth2.service_account':service_account,
        'google.auth.impersonated_credentials':impersonated_credentials}.items():
        monkeypatch.setitem(sys.modules,name,module)
    targets=[]
    class FakeCred:
        token='SHORT-LIVED-TEST-TOKEN'
        def refresh(self, request): pass
    monkeypatch.setattr(ga, 'default', lambda scopes: (object(), 'host-project'), raising=False)
    def impersonate(**kwargs):
        targets.append(kwargs)
        return FakeCred()
    monkeypatch.setattr(impersonated_credentials, 'Credentials', impersonate, raising=False)
    class Resp:
        def __enter__(self): return io.BytesIO(json.dumps({'reasoningEngines': [{'name':'projects/google-project-123/locations/us-central1/reasoningEngines/7','displayName':'Demo'}]}).encode())
        def __exit__(self, *args): return False
    monkeypatch.setattr(urllib_request, 'urlopen', lambda req,timeout: Resp())
    conn={'id':'conn-gcp','provider':'google_agent_engine', 'scope':{'project_id':'google-project-123','location':'us-central1'},
          'auth_mode':'google_impersonate',
          'auth_config':{'service_account_email':'agent-discovery@google-project-123.iam.gserviceaccount.com'}}
    found=connectors.discover(conn)
    assert len(found)==1 and found[0].name=='Demo'
    assert targets[0]['target_principal']=='agent-discovery@google-project-123.iam.gserviceaccount.com'
    assert targets[0]['lifetime']==1800


def test_entra_shared_app_uses_customer_tenant_and_host_credential(monkeypatch):
    import sys, types
    import httpx
    azure = types.ModuleType('azure');azure.__path__=[]
    identity = types.ModuleType('azure.identity')
    azure.identity=identity
    monkeypatch.setitem(sys.modules,'azure',azure)
    monkeypatch.setitem(sys.modules,'azure.identity',identity)
    calls=[]
    class Cred:
        def __init__(self, tenant, client, secret): calls.append((tenant, client, secret))
        def get_token(self, scope):
            assert scope=='https://ai.azure.com/.default'
            class Token: token='TEST-AZURE-TOKEN'
            return Token()
        def close(self): pass
    class Resp:
        def raise_for_status(self): pass
        def json(self): return {'data':[{'id':'agent-1','name':'foundry-probe'}]}
    class Http:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def get(self, url, params, headers):
            assert headers['Authorization']=='Bearer TEST-AZURE-TOKEN'
            return Resp()
    monkeypatch.setattr(identity, 'ClientSecretCredential', Cred, raising=False)
    monkeypatch.setattr(identity, 'ManagedIdentityCredential', Cred, raising=False)
    monkeypatch.setattr(httpx, 'Client', Http)
    monkeypatch.setenv('GAME_AZURE_CLIENT_ID','host-application-id')
    monkeypatch.setenv('GAME_AZURE_CLIENT_SECRET','host-managed-secret')
    conn={'id':'conn-azure', 'provider':'microsoft_foundry',
          'scope':{'project_endpoint':'https://resource.services.ai.azure.com/api/projects/dev'},
          'env_prefix':'AC_FOUNDRY','auth_mode':'entra_shared_app',
          'auth_config':{'tenant_id':'11111111-2222-3333-4444-555555555555'}}
    found=connectors.discover(conn)
    assert len(found)==1 and found[0].name=='foundry-probe'
    assert calls==[('11111111-2222-3333-4444-555555555555','host-application-id','host-managed-secret')]
