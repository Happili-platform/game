# SPDX-License-Identifier: AGPL-3.0-only
"""Local encrypted storage and restart regression tests; all credentials are synthetic."""
import base64
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from game import connectors, vault
from game.main import app


@pytest.fixture
def paths(tmp_path, monkeypatch):
    db = tmp_path / 'existing-023.db'
    key = tmp_path / 'private-key-dir' / 'master.key'
    monkeypatch.setenv('GAME_DB_PATH', str(db))
    monkeypatch.setenv('GAME_VAULT_KEY_PATH', str(key))
    monkeypatch.delenv('GAME_MASTER_KEY', raising=False)
    monkeypatch.setenv('GAME_TESTING', 'true')
    monkeypatch.setenv('GAME_DEMO_DATA', 'false')
    return db, key


SCOPE = {
    'microsoft_foundry': {'project_endpoint': 'https://probe.services.ai.azure.com/api/projects/lab'},
    'google_agent_engine': {'project_id': 'game-lab-123', 'location': 'us-central1'},
    'aws_agentcore': {'region': 'us-west-2'},
}
CREDENTIALS = {
    'microsoft_foundry': {
        'tenant_id': '11111111-1111-1111-1111-111111111111',
        'client_id': '22222222-2222-2222-2222-222222222222',
        'client_secret': 'dummy-azure-secret-ALPHA',
    },
    'aws_agentcore': {
        'access_key_id': 'ASIAFAKEKEY', 'secret_access_key': 'dummy-aws-secret-BETA',
        'session_token': 'dummy-aws-session-GAMMA',
    },
    'google_agent_engine': {
        'service_account_json': json.dumps({
            'type':'service_account','client_email':'dev@project.iam.gserviceaccount.com',
            'client_id':'12345','private_key_id':'fake-key-id',
            'private_key':'-----BEGIN PRIVATE KEY-----\nFAKE-GOOGLE-KEY-DELTA\n-----END PRIVATE KEY-----\n',
            'token_uri':'https://oauth2.googleapis.com/token'
        })
    },
}


def add(tc, provider):
    r = tc.post('/api/connections', json={
        'provider':provider,'label':provider, 'scope':SCOPE[provider],
        'env_prefix': {'microsoft_foundry':'AC_FOUNDRY','aws_agentcore':'AC_AWS','google_agent_engine':'AC_GOOGLE'}[provider]
    })
    assert r.status_code == 201, r.text
    return r.json()['id']


def test_all_three_providers_encrypted_and_decrypted_after_restart(paths, monkeypatch):
    db, key = paths
    ids = {}
    with TestClient(app) as tc:
        for provider in SCOPE:
            id_ = add(tc, provider); ids[provider] = id_
            response=tc.put(f'/api/connections/{id_}/credentials', json=CREDENTIALS[provider])
            assert response.status_code == 200, response.text
            assert response.json()['credential_source'] == 'encrypted'
        assert key.exists()
        assert key.stat().st_mode & 0o077 == 0
        text = db.read_bytes().decode('latin1')
        for marker in ('dummy-azure-secret-ALPHA','dummy-aws-secret-BETA','FAKE-GOOGLE-KEY-DELTA'):
            assert marker not in text
        response = tc.get('/api/connections')
        assert response.status_code == 200
        assert all(c['credential_source'] == 'encrypted' for c in response.json())
        assert all('dummy-' not in str(c) for c in response.json())
    # A brand-new application lifespan simulates a server restart without memory sessions.
    calls = {}
    def fake_discover(config, **kwargs):
        calls[config['provider']] = kwargs
        return [connectors.DiscoveredAgent(f"id-{config['provider']}", config['provider'], 'Test')]
    monkeypatch.setattr(connectors, 'discover', fake_discover)
    with TestClient(app) as restarted:
        assert len(restarted.get('/api/connections').json()) == 3
        for provider, id_ in ids.items():
            assert restarted.post(f'/api/connections/{id_}/test').json()['visible_agents'] == 1
            assert restarted.post(f'/api/connections/{id_}/discover').json()['discovered'] == 1
        assert calls['microsoft_foundry']['azure_credentials'] == CREDENTIALS['microsoft_foundry']
        assert calls['aws_agentcore']['aws_credentials'] == CREDENTIALS['aws_agentcore']
        assert calls['google_agent_engine']['google_credentials']['client_email'].endswith('.gserviceaccount.com')
        assert len(restarted.get('/api/agents').json()) == 3


def test_rotate_and_remove_credentials(paths):
    db,key=paths
    with TestClient(app) as tc:
        id_=add(tc,'microsoft_foundry')
        uri=f'/api/connections/{id_}/credentials'
        assert tc.put(uri,json=CREDENTIALS['microsoft_foundry']).status_code==200
        fresh={**CREDENTIALS['microsoft_foundry'],'client_secret':'new-dummy-azure-secret-OMEGA'}
        assert tc.put(uri,json=fresh).status_code==200
        with sqlite3.connect(db) as sql:
            record=sql.execute('SELECT encrypted_json FROM provider_credentials').fetchone()[0]
            assert vault.decrypt(id_,'microsoft_foundry',record)==fresh
        assert tc.delete(uri).status_code==200
        with sqlite3.connect(db) as sql:
            assert sql.execute('SELECT COUNT(*) FROM provider_credentials').fetchone()[0]==0


def test_missing_master_key_fails_closed_and_recovers(paths, monkeypatch):
    db,key=paths
    with TestClient(app) as tc:
        id_=add(tc,'aws_agentcore')
        uri=f'/api/connections/{id_}'
        assert tc.put(uri+'/credentials', json=CREDENTIALS['aws_agentcore']).status_code==200
        saved_key=key.read_bytes()
        key.unlink()
        listed=tc.get('/api/connections').json()[0]
        assert listed['credential_source']=='vault_unavailable'
        assert listed['credential_status']=='unavailable'
        assert tc.post(uri+'/test').status_code==502
        assert tc.put(uri+'/credentials', json=CREDENTIALS['aws_agentcore']).status_code==503
        assert not key.exists(), 'Never silently replace a lost key while encrypted records exist'
        key.write_bytes(saved_key); key.chmod(0o600)
        assert tc.get('/api/connections').json()[0]['credential_source']=='encrypted'


def test_expiry_explicitly_reported_and_blocks_auth_before_network(paths, monkeypatch):
    db,key=paths
    with TestClient(app) as tc:
        id_=add(tc,'aws_agentcore')
        expired=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        payload={**CREDENTIALS['aws_agentcore'], 'expires_at':expired}
        assert tc.put(f'/api/connections/{id_}/credentials',json=payload).status_code==200
        c=tc.get('/api/connections').json()[0]
        assert c['credential_status']=='expired'
        monkeypatch.setattr(connectors, 'discover', lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError('Never call provider with known-expired credentials')))
        failed=tc.post(f'/api/connections/{id_}/test')
        assert failed.status_code==502
        assert 'expired' in failed.json()['detail']


def test_aad_prevents_swapping_other_connection_ciphertexts(paths):
    db,key=paths
    with TestClient(app) as tc:
        first=add(tc,'aws_agentcore'); second=add(tc,'aws_agentcore')
        for id_ in (first,second):
            assert tc.put(f'/api/connections/{id_}/credentials',json=CREDENTIALS['aws_agentcore']).status_code==200
        with sqlite3.connect(db) as sql:
            encrypted=sql.execute('SELECT encrypted_json FROM provider_credentials WHERE connection_id=?',(first,)).fetchone()[0]
            sql.execute('UPDATE provider_credentials SET encrypted_json=? WHERE connection_id=?',(encrypted,second))
            sql.commit()
        details={x['id']:x for x in tc.get('/api/connections').json()}
        assert details[first]['credential_source']=='encrypted'
        assert details[second]['credential_source']=='vault_unavailable'


def test_existing_023_schema_is_upgraded_without_dropping_data(paths):
    db,key=paths
    # Minimal v0.2.3 connection table, with an existing cloud connection.
    with sqlite3.connect(db) as sql:
        sql.execute('CREATE TABLE provider_connections(id TEXT PRIMARY KEY,provider TEXT NOT NULL,label TEXT NOT NULL,scope_json TEXT NOT NULL,env_prefix TEXT NOT NULL,created_at TEXT NOT NULL,last_synced_at TEXT,last_error TEXT)')
        sql.execute("INSERT INTO provider_connections(id,provider,label,scope_json,env_prefix,created_at) VALUES(?,?,?,?,?,?)",
                    ('conn-existing','aws_agentcore','Existing AWS','{"region":"us-west-2"}','AC_AWS','2026-11-02T00:00:00Z'))
    with TestClient(app) as tc:
        connections=tc.get('/api/connections').json()
        assert len(connections)==1 and connections[0]['id']=='conn-existing'
        assert tc.put('/api/connections/conn-existing/credentials',json=CREDENTIALS['aws_agentcore']).status_code==200
        assert tc.get('/api/connections').json()[0]['credential_source']=='encrypted'


def test_replaced_wrong_master_key_cannot_overwrite_existing_secrets(paths):
    db,key=paths
    with TestClient(app) as tc:
        id_=add(tc,'aws_agentcore')
        uri=f'/api/connections/{id_}/credentials'
        assert tc.put(uri,json=CREDENTIALS['aws_agentcore']).status_code==200
        previous=key.read_bytes()
        key.write_bytes(base64.urlsafe_b64encode(os.urandom(32))+b'\n')
        key.chmod(0o600)
        assert tc.get('/api/connections').json()[0]['credential_source']=='vault_unavailable'
        rejected=tc.put(uri,json=CREDENTIALS['aws_agentcore'])
        assert rejected.status_code==503
        key.write_bytes(previous)
        assert tc.get('/api/connections').json()[0]['credential_source']=='encrypted'


def test_delete_connection_cascades_encrypted_record(paths):
    db,key=paths
    with TestClient(app) as tc:
        id_=add(tc,'google_agent_engine')
        assert tc.put(f'/api/connections/{id_}/credentials',json=CREDENTIALS['google_agent_engine']).status_code==200
        assert tc.delete(f'/api/connections/{id_}').status_code==200
        with sqlite3.connect(db) as sql:
            assert sql.execute('SELECT COUNT(*) FROM provider_credentials').fetchone()[0]==0
