# SPDX-License-Identifier: AGPL-3.0-only
import pytest
from fastapi.testclient import TestClient

from game import connectors
from game.local_accounts import create_user
from game.main import app
from game.version import __version__


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('GAME_AUTH_MODE', 'password')
    monkeypatch.setenv('GAME_VAULT_KEY_PATH', str(tmp_path / 'vault' / 'master.key'))
    monkeypatch.setenv('GAME_DB_PATH', str(tmp_path / 'connector-test.db'))
    monkeypatch.setenv('GAME_DEMO_DATA', 'false')
    monkeypatch.setenv('GAME_TESTING', 'true')
    with TestClient(app) as test_client:
        password = 'Connector-Test-Admin-Password'
        create_user('connector-admin', password, 'admin', must_change=False)
        response = test_client.post('/api/auth/login', json={
            'username': 'connector-admin', 'password': password
        })
        assert response.status_code == 200, response.text
        test_client.headers['X-CSRF-Token'] = response.json()['csrf_token']
        yield test_client


def test_catalog_has_supported_and_planned(client):
    data = client.get('/api/providers').json()
    assert {p['id'] for p in data if p['status'] == 'implemented'} == {
        'microsoft_foundry', 'google_agent_engine', 'aws_agentcore', 'aws_bedrock_classic', 'custom_registry', 'github_inventory', 'atlassian_rovo_mcp'
    }
    assert any(p['id'] == 'salesforce_agentforce' and p['status'] == 'planned' for p in data)


def test_scope_and_secret_validation(client):
    payload = {'provider': 'microsoft_foundry', 'label': 'Test Foundry', 'env_prefix': 'AC_FOUNDRY',
               'scope': {'project_endpoint': 'https://example.services.ai.azure.com/api/projects/test'}}
    assert client.post('/api/connections', json=payload).status_code == 201
    bad = {**payload, 'scope': {'project_endpoint': 'http://localhost/admin'}}
    assert client.post('/api/connections', json=bad).status_code == 422
    bad = {**payload, 'scope': {'project_endpoint': 'https://other.example/api/projects/test'}}
    assert client.post('/api/connections', json=bad).status_code == 422
    bad = {**payload, 'scope': {**payload['scope'], 'api_key': 'dont-store-me'}}
    assert client.post('/api/connections', json=bad).status_code == 422
    bad = {**payload, 'provider': 'google_agent_engine', 'scope': {'project_id': 'my-sample-project', 'location': 'us-central1'}}
    assert client.post('/api/connections', json=bad).status_code == 201
    bad = {**payload, 'provider': 'salesforce_agentforce', 'scope': {}}
    assert client.post('/api/connections', json=bad).status_code == 422


def test_discover_idempotent_and_inventory_provenance(client, monkeypatch):
    first = client.post('/api/connections', json={
        'provider': 'microsoft_foundry', 'label': 'Foundry', 'env_prefix': 'AC_FOUNDRY',
        'scope': {'project_endpoint': 'https://example.services.ai.azure.com/api/projects/test'}
    }).json()
    second = client.post('/api/connections', json={
        'provider': 'google_agent_engine', 'label': 'Google', 'env_prefix': 'AC_GOOGLE',
        'scope': {'project_id': 'my-sample-project', 'location': 'us-central1'}
    }).json()
    def fake_discover(connection, azure_credentials=None):
        return [connectors.DiscoveredAgent('provider-id-1', 'Review Agent',
            'Microsoft Foundry' if connection['provider'] == 'microsoft_foundry' else 'Google Agent Engine',
            provider_status='READY')]
    monkeypatch.setattr(connectors, 'discover', fake_discover)
    for _ in range(2):
        assert client.post('/api/connections/' + first['id'] + '/discover').json()['discovered'] == 1
    assert client.post('/api/connections/' + second['id'] + '/discover').json()['discovered'] == 1
    agents = client.get('/api/agents').json()
    assert len(agents) == 2
    assert all(a['source'] == 'discovered' and a['last_seen'] is None for a in agents)
    assert all(a['discovery_last_seen'] and a['external_id'] == 'provider-id-1' for a in agents)
    assert agents[0]['id'] != agents[1]['id']
    assert all('STALE_AGENT' not in {f['code'] for f in a['findings']} for a in agents)
    assert all(a['environment'] == 'unknown' for a in agents)
    assert client.get('/api/overview').json()['totals']['agents'] == 2
    assert client.post('/api/usage', json={'agent_id': agents[0]['id'], 'cost_usd': 5}).status_code == 409


def test_discovery_error_is_safe_and_preserves_inventory(client, monkeypatch):
    conn = client.post('/api/connections', json={
        'provider': 'aws_agentcore', 'label': 'AWS', 'env_prefix': 'AC_AWS', 'scope': {'region': 'us-east-1'}
    }).json()
    monkeypatch.setattr(connectors, 'discover', lambda connection, azure_credentials=None: [
        connectors.DiscoveredAgent('arn:aws:agent:1','Agent One','AWS Bedrock AgentCore')])
    assert client.post('/api/connections/' + conn['id'] + '/discover').status_code == 200
    def fail(connection, azure_credentials=None):
        raise connectors.DiscoveryError('Check AWS permissions')
    monkeypatch.setattr(connectors, 'discover', fail)
    bad = client.post('/api/connections/' + conn['id'] + '/discover')
    assert bad.status_code == 502
    assert 'permissions' in bad.json()['detail']
    assert len(client.get('/api/agents').json()) == 1
    assert client.get('/api/connections').json()[0]['last_error'] == 'Check AWS permissions'


def test_edit_connection_without_secrets_and_provider_is_immutable(client):
    created = client.post('/api/connections', json={
        'provider': 'microsoft_foundry', 'label': 'First', 'env_prefix': 'AC_FOUNDRY',
        'scope': {'project_endpoint': 'https://sample.services.ai.azure.com/api/projects/initial'}
    }).json()
    changed = client.patch('/api/connections/' + created['id'], json={
        'label': 'Foundry Production', 'env_prefix': 'AC_FOUNDRY_PRD',
        'scope': created['scope']
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()['label'] == 'Foundry Production'
    assert changed.json()['env_prefix'] == 'AC_FOUNDRY_PRD'
    assert changed.json()['provider'] == 'microsoft_foundry'
    bad_provider = client.patch('/api/connections/' + created['id'], json={
        'label': 'Switched', 'env_prefix': 'AC_TEST', 'scope': created['scope'],
        'provider': 'google_agent_engine'
    })
    assert bad_provider.status_code == 422
    bad_secrets = client.patch('/api/connections/' + created['id'], json={
        'label': 'With secret', 'env_prefix': 'AC_TEST', 'scope': {**created['scope'], 'api_key':'secret'}
    })
    assert bad_secrets.status_code == 422
    assert client.patch('/api/connections/missing', json={
        'label': 'Missing', 'env_prefix': 'AC_TEST', 'scope': created['scope']
    }).status_code == 404


def test_scope_change_requires_clear_inventory_and_remove_is_explicit(
    client, monkeypatch
):
    from game.db import connection

    created = client.post('/api/connections', json={
        'provider': 'aws_agentcore',
        'label': 'AWS',
        'env_prefix': 'AC_AWS',
        'scope': {'region': 'us-east-1'},
    }).json()

    monkeypatch.setattr(
        connectors, 'discover',
        lambda connection, azure_credentials=None: [
            connectors.DiscoveredAgent(
                'agent-one', 'Agent One', 'AWS Bedrock AgentCore'
            )
        ],
    )

    url = '/api/connections/' + created['id']
    assert client.post(url + '/discover').status_code == 200

    with connection() as db:
        before = [
            tuple(row) for row in db.execute(
                """SELECT * FROM discovered_agents
                   WHERE connection_id=?""",
                (created['id'],),
            )
        ]

    changed = {
        'label': 'AWS West',
        'env_prefix': 'AC_AWS',
        'scope': {'region': 'us-west-2'},
    }

    assert client.patch(url, json=changed).status_code == 409
    assert client.patch(url, json={
        **changed,
        'clear_inventory_on_scope_change': True,
    }).status_code == 409

    assert client.delete(url).status_code == 409
    assert client.delete(
        url + '?remove_inventory=true'
    ).status_code == 409

    with connection() as db:
        after = [
            tuple(row) for row in db.execute(
                """SELECT * FROM discovered_agents
                   WHERE connection_id=?""",
                (created['id'],),
            )
        ]

    assert after == before
    assert len(after) == 1

    # The connection target must also remain unchanged.
    assert client.get('/api/connections').json()[0]['scope'] == {
        'region': 'us-east-1'
    }



def test_frontend_assets_cache_busted(client):
    assert client.get('/api/health').json()['version'] == __version__
    home = client.get('/')
    assert home.status_code == 200
    assert f'/static/app.js?v={__version__}' in home.text
    assert f'/static/style.css?v={__version__}' in home.text
    assert 'data-view="connections"' in home.text
    assert home.headers['cache-control'].startswith('no-store')
    script = client.get(f'/static/app.js?v={__version__}')
    assert script.status_code == 200
    assert 'beginConnectionEdit' in script.text
    assert script.headers['cache-control'].startswith('no-store')


def test_encrypted_credentials_persist_without_exposing_secrets(client, monkeypatch):
    from game import main as module
    created = client.post('/api/connections', json={
        'provider': 'microsoft_foundry', 'label': 'Foundry Test', 'env_prefix': 'AC_FOUNDRY',
        'scope': {'project_endpoint': 'https://example.services.ai.azure.com/api/projects/lab'}
    }).json()
    conn_id = created['id']
    payload = {'tenant_id': '11111111-1111-1111-1111-111111111111',
               'client_id': '22222222-2222-2222-2222-222222222222',
               'client_secret': 'ULTRA-SENSITIVE-DUMMY-SECRET'}
    assert client.put('/api/connections/'+conn_id+'/credentials', json=payload).status_code == 200
    fetched = client.get('/api/connections').json()[0]
    assert fetched['credential_source'] == 'encrypted'
    assert 'ULTRA-SENSITIVE' not in str(fetched)
    import sqlite3, os
    with sqlite3.connect(os.environ['GAME_DB_PATH']) as db:
        stored = str(db.execute('SELECT * FROM provider_connections').fetchall()) + str(db.execute('SELECT * FROM provider_credentials').fetchall())
    assert 'ULTRA-SENSITIVE' not in stored
    captured = []
    def fake_sync(connection, azure_credentials=None):
        captured.append(azure_credentials)
        return []
    monkeypatch.setattr(connectors, 'discover', fake_sync)
    synced = client.post('/api/connections/'+conn_id+'/discover')
    assert synced.status_code == 200
    assert captured[0] == payload
    assert client.delete('/api/connections/'+conn_id+'/credentials').status_code == 200
    assert client.get('/api/connections').json()[0]['credential_source'] == 'not_configured'
    assert client.get('/api/connections').json()[0]['credential_status'] == 'missing'

def test_credential_endpoint_restricted_and_rejects_secret_in_metadata(client, monkeypatch):
    created = client.post('/api/connections', json={
        'provider': 'microsoft_foundry', 'label': 'Foundry Test', 'env_prefix': 'AC_FOUNDRY',
        'scope': {'project_endpoint': 'https://example.services.ai.azure.com/api/projects/lab'}
    }).json()
    uri = '/api/connections/'+created['id']+'/credentials'
    bad = {'tenant_id': 'no', 'client_id': 'no', 'client_secret': 'fake'}
    assert client.put(uri, json=bad).status_code == 422
    good = {'tenant_id': '11111111-1111-1111-1111-111111111111',
            'client_id': '22222222-2222-2222-2222-222222222222',
            'client_secret': 'FAKE-TEST-SECRET'}
    assert client.put(uri, json=good, headers={'Origin':'https://malicious.example'}).status_code == 403
    monkeypatch.delenv('GAME_TESTING')
    assert client.put(uri, json=good).status_code == 403

def test_build_version_matches_file_and_health(client):
    from game.version import __version__
    from pathlib import Path
    assert Path(__file__).resolve().parents[1].joinpath('src/VERSION').read_text().strip() == __version__
    assert client.get('/api/health').json()['version'] == __version__


def test_f01_duplicate_discovery_preserves_inventory(client, monkeypatch):
    from game.db import connection

    created = client.post('/api/connections', json={
        'provider': 'microsoft_foundry',
        'label': 'F01 Foundry',
        'env_prefix': 'F01_FOUNDRY',
        'scope': {
            'project_endpoint':
                'https://example.services.ai.azure.com/api/projects/test'
        },
    })
    assert created.status_code == 201, created.text
    connection_id = created.json()['id']

    monkeypatch.setattr(
        connectors, 'discover',
        lambda configured, azure_credentials=None: [
            connectors.DiscoveredAgent(
                'provider-id-1', 'Original', 'Microsoft Foundry'
            )
        ],
    )

    first = client.post(
        f'/api/connections/{connection_id}/discover'
    )
    assert first.status_code == 200, first.text

    with connection() as db:
        before = [
            tuple(row) for row in db.execute(
                """SELECT id, external_id, name, discovery_last_seen
                   FROM discovered_agents
                   WHERE connection_id=?
                   ORDER BY id""",
                (connection_id,),
            )
        ]

    monkeypatch.setattr(
        connectors, 'discover',
        lambda configured, azure_credentials=None: [
            connectors.DiscoveredAgent(
                'provider-id-1', 'Changed', 'Microsoft Foundry'
            ),
            connectors.DiscoveredAgent(
                'provider-id-1', 'Duplicate', 'Microsoft Foundry'
            ),
        ],
    )

    rejected = client.post(
        f'/api/connections/{connection_id}/discover'
    )
    assert rejected.status_code == 409, rejected.text

    with connection() as db:
        after = [
            tuple(row) for row in db.execute(
                """SELECT id, external_id, name, discovery_last_seen
                   FROM discovered_agents
                   WHERE connection_id=?
                   ORDER BY id""",
                (connection_id,),
            )
        ]

    assert after == before


def test_f01_scope_change_cannot_delete_discovered_history(
    client, monkeypatch
):
    from game.db import connection

    created = client.post('/api/connections', json={
        'provider': 'aws_agentcore',
        'label': 'F01 AWS East',
        'env_prefix': 'F01_AWS',
        'scope': {'region': 'us-east-1'},
    })
    assert created.status_code == 201, created.text
    connection_id = created.json()['id']

    monkeypatch.setattr(
        connectors, 'discover',
        lambda configured, azure_credentials=None: [
            connectors.DiscoveredAgent(
                'agent-123', 'Historical Agent',
                'AWS Bedrock AgentCore'
            )
        ],
    )

    discovered = client.post(
        f'/api/connections/{connection_id}/discover'
    )
    assert discovered.status_code == 200, discovered.text

    with connection() as db:
        original = [
            tuple(r) for r in db.execute(
                """SELECT id, external_id, name
                   FROM discovered_agents
                   WHERE connection_id=?""",
                (connection_id,),
            )
        ]

    # Even explicit clearing must not silently erase history.
    changed = client.patch(
        f'/api/connections/{connection_id}',
        json={
            'label': 'F01 AWS West',
            'env_prefix': 'F01_AWS',
            'scope': {'region': 'us-west-2'},
            'clear_inventory_on_scope_change': True,
        },
    )

    assert changed.status_code == 409

    with connection() as db:
        remaining = [
            tuple(r) for r in db.execute(
                """SELECT id, external_id, name
                   FROM discovered_agents
                   WHERE connection_id=?""",
                (connection_id,),
            )
        ]

    assert remaining == original


def test_f01_connection_removal_preserves_discovered_history(
    client, monkeypatch
):
    from game.db import connection

    created = client.post('/api/connections', json={
        'provider': 'aws_agentcore',
        'label': 'F01 AWS',
        'env_prefix': 'F01_AWS',
        'scope': {'region': 'us-east-1'},
    })
    assert created.status_code == 201, created.text
    connection_id = created.json()['id']

    monkeypatch.setattr(
        connectors, 'discover',
        lambda configured, azure_credentials=None: [
            connectors.DiscoveredAgent(
                'agent-456', 'Protected Agent',
                'AWS Bedrock AgentCore'
            )
        ],
    )

    assert client.post(
        f'/api/connections/{connection_id}/discover'
    ).status_code == 200

    with connection() as db:
        original = db.execute(
            """SELECT id FROM discovered_agents
               WHERE connection_id=?""",
            (connection_id,),
        ).fetchone()['id']

    # Explicit inventory deletion is not sufficient authorization
    # to destroy historical identity records.
    removed = client.delete(
        f'/api/connections/{connection_id}?remove_inventory=true'
    )

    assert removed.status_code == 409

    with connection() as db:
        remaining = db.execute(
            """SELECT id FROM discovered_agents
               WHERE connection_id=?""",
            (connection_id,),
        ).fetchone()

        assert remaining is not None
        assert remaining['id'] == original

        assert db.execute(
            """SELECT COUNT(*) FROM provider_connections
               WHERE id=?""",
            (connection_id,),
        ).fetchone()[0] == 1


def test_f01_empty_connection_can_be_removed(client):
    created = client.post('/api/connections', json={
        'provider': 'aws_agentcore',
        'label': 'F01 Empty Connection',
        'env_prefix': 'F01_AWS',
        'scope': {'region': 'us-east-1'},
    })

    assert created.status_code == 201, created.text
    connection_id = created.json()['id']

    removed = client.delete(
        f'/api/connections/{connection_id}'
    )

    assert removed.status_code == 200, removed.text
