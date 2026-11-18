# SPDX-License-Identifier: AGPL-3.0-only
"""Multi-provider encrypted credential tests; no cloud calls and no real keys."""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from game import connectors
from game.main import app

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('GAME_VAULT_KEY_PATH', str(tmp_path / 'vault' / 'master.key'))
    monkeypatch.setenv('GAME_DB_PATH', str(tmp_path / 'v023.db'))
    monkeypatch.setenv('GAME_DEMO_DATA', 'false')
    monkeypatch.setenv('GAME_TESTING', 'true')
    with TestClient(app) as tc:
        yield tc


def add(client, provider):
    scopes = {
       'microsoft_foundry': {'project_endpoint': 'https://sample.services.ai.azure.com/api/projects/game'},
       'aws_agentcore': {'region': 'us-west-2'},
       'aws_bedrock_classic': {'region': 'us-west-2'},
       'google_agent_engine': {'project_id': 'game-test-2026', 'location': 'us-central1'},
    }
    response=client.post('/api/connections', json={
        'provider':provider,'label':'Local test','env_prefix':'AC_AWS' if provider.startswith('aws_') else 'AC_GOOGLE',
        'scope':scopes[provider],
    })
    assert response.status_code == 201, response.text
    return response.json()


def aws_payload():
    return {'access_key_id':'ASIAEXAMPLE00000000','secret_access_key':'not-real-secret-123',
            'session_token':'not-real-session-token-456'}


def google_payload():
    key={'type':'service_account','client_email':'dev@project.iam.gserviceaccount.com',
         'client_id':'12345','private_key_id':'abc123',
         'private_key':'-----BEGIN PRIVATE KEY-----\nNOT_A_REAL_PRIVATE_KEY\n-----END PRIVATE KEY-----\n',
         'token_uri':'https://oauth2.googleapis.com/token'}
    return {'service_account_json':json.dumps(key)}


@pytest.mark.parametrize('provider,creds_key,payload', [
    ('aws_agentcore','aws_credentials',aws_payload()),
    ('aws_bedrock_classic','aws_credentials',aws_payload()),
    ('google_agent_engine','google_credentials',google_payload()),
])
def test_provider_ui_secrets_encrypted_and_support_discovery(client, monkeypatch, provider, creds_key, payload):
    conn=add(client,provider)
    uri=f'/api/connections/{conn["id"]}'
    resp=client.put(uri+'/credentials', json=payload)
    assert resp.status_code==200, resp.text
    listed=client.get('/api/connections').json()[0]
    assert listed['credential_source']=='encrypted'
    for token in ('not-real-secret','not-real-session-token','NOT_A_REAL_PRIVATE_KEY'):
        assert token not in str(listed)
        with sqlite3.connect(__import__('os').environ['GAME_DB_PATH']) as db:
            assert token not in str(db.execute('SELECT * FROM provider_connections').fetchall()) + str(db.execute('SELECT * FROM provider_credentials').fetchall())
    seen=[]
    def fake_discover(connection, **kwargs):
        seen.append(kwargs)
        return [connectors.DiscoveredAgent('x1','Sample agent','Test Provider')]
    monkeypatch.setattr(connectors,'discover',fake_discover)
    tested=client.post(uri+'/test')
    assert tested.status_code==200
    assert tested.json()['visible_agents']==1
    assert client.get('/api/agents').json()==[], 'Test Connection must not change inventory'
    assert client.post(uri+'/discover').status_code==200
    assert len(client.get('/api/agents').json())==1
    assert creds_key in seen[0]
    assert client.delete(uri+'/credentials').status_code==200
    assert client.get('/api/connections').json()[0]['credential_source'] != 'encrypted'
    assert client.post(uri+'/test').status_code==200
    assert creds_key not in seen[-1]


def test_bad_credentials_rejected_without_echo(client):
    google=add(client,'google_agent_engine')
    url=f'/api/connections/{google["id"]}/credentials'
    malicious_key=google_payload()
    obj=json.loads(malicious_key['service_account_json'])
    obj['token_uri']='https://example.evil.net/steal'
    payload={'service_account_json':json.dumps(obj)}
    bad=client.put(url,json=payload)
    assert bad.status_code==422
    assert 'example.evil.net' not in bad.text
    assert bad.status_code==422
    aws=add(client,'aws_agentcore')
    url=f'/api/connections/{aws["id"]}/credentials'
    incomplete={'access_key_id':'ASIAEXAMPLE','secret_access_key':'private'}
    assert client.put(url,json=incomplete).status_code==422
    blocked=client.put(url,json=aws_payload(),headers={'Origin':'https://evil.example'})
    assert blocked.status_code==403


def test_scope_change_clears_encrypted_credentials(client):
    from game import main
    conn=add(client,'aws_agentcore')
    url=f'/api/connections/{conn["id"]}'
    assert client.put(url+'/credentials', json=aws_payload()).status_code==200
    assert client.get('/api/connections').json()[0]['credential_source'] == 'encrypted'
    new=client.patch(url, json={ 'label':'Different region', 'env_prefix':'AC_AWS', 'scope':{'region':'us-east-1'}})
    assert new.status_code==200
    assert client.get('/api/connections').json()[0]['credential_source'] != 'encrypted'
    assert new.json()['credential_source'] != 'encrypted'


def test_credentials_are_provider_specific(client):
    aws=add(client,'aws_agentcore')
    google=add(client,'google_agent_engine')
    assert client.put(f'/api/connections/{aws["id"]}/credentials',json=google_payload()).status_code==422
    assert client.put(f'/api/connections/{google["id"]}/credentials',json=aws_payload()).status_code==422
    assert client.get('/api/connections/'+aws['id']+'/credentials').status_code==405
