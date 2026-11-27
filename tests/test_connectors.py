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

    from game.db import connection
    from game.identity import initialize_identity_schema
    from game.discovery_provenance import _issue_connector_receipt

    with connection() as db:
        initialize_identity_schema(db)

    google_id = (
        'projects/my-sample-project/locations/'
        'us-central1/reasoningEngines/12345'
    )

    def verified_google(configured, google_credentials=None):
        agents = [
            connectors.DiscoveredAgent(
                google_id, 'Review Agent', 'Google Agent Engine',
                provider_status='READY',
            )
        ]
        return agents, _issue_connector_receipt(configured, agents)

    monkeypatch.setattr(
        connectors, 'discover_google_with_provenance',
        verified_google,
    )
    for _ in range(2):
        assert client.post('/api/connections/' + first['id'] + '/discover').json()['discovered'] == 1
    assert client.post('/api/connections/' + second['id'] + '/discover').json()['discovered'] == 1
    agents = client.get('/api/agents').json()
    assert len(agents) == 2
    assert all(a['source'] == 'discovered' and a['last_seen'] is None for a in agents)
    assert all(a['discovery_last_seen'] for a in agents)
    assert {a['external_id'] for a in agents} == {
        'provider-id-1', google_id
    }
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


@pytest.mark.parametrize(
    "resource_type",
    ["provider_inventory", "trust_tools", "trust_links"],
)
def test_f01_history_blocks_connection_removal(
    client, resource_type
):
    from game.db import connection

    created = client.post('/api/connections', json={
        'provider': 'github_inventory',
        'label': 'F01 Evidence',
        'env_prefix': 'F01_GITHUB',
        'scope': {'organization': 'Happili-platform'},
    })
    assert created.status_code == 201, created.text
    connection_id = created.json()['id']

    _seed_f01_evidence(connection_id, resource_type)

    removed = client.delete(
        f'/api/connections/{connection_id}?remove_inventory=true'
    )
    assert removed.status_code == 409, removed.text

    with connection() as db:
        assert _f01_evidence_exists(
            db, connection_id, resource_type
        )


@pytest.mark.parametrize(
    "resource_type",
    ["provider_inventory", "trust_tools", "trust_links"],
)
def test_f01_history_blocks_connection_scope_change(
    client, resource_type
):
    from game.db import connection

    created = client.post('/api/connections', json={
        'provider': 'github_inventory',
        'label': 'F01 Evidence',
        'env_prefix': 'F01_GITHUB',
        'scope': {'organization': 'Happili-platform'},
    })
    assert created.status_code == 201, created.text
    connection_id = created.json()['id']

    _seed_f01_evidence(connection_id, resource_type)

    changed = client.patch(
        f'/api/connections/{connection_id}',
        json={
            'label': 'Changed',
            'env_prefix': 'F01_GITHUB',
            'scope': {'organization': 'Other-platform'},
            'clear_inventory_on_scope_change': True,
        },
    )
    assert changed.status_code == 409, changed.text

    with connection() as db:
        assert _f01_evidence_exists(
            db, connection_id, resource_type
        )

    current = client.get('/api/connections').json()
    assert current[0]['scope'] == {
        'organization': 'Happili-platform'
    }


def _seed_f01_evidence(connection_id, resource_type):
    from game.db import connection

    with connection() as db:
        now = "2026-11-25T00:00:00Z"

        if resource_type == "provider_inventory":
            db.execute("""
                INSERT INTO provider_inventory
                (id, tenant_id, connection_id, kind,
                 external_id, name, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "f01-inventory", "local-dev", connection_id,
                "repository", "repo-123", "Example", now, now,
            ))
            return

        db.execute("""
            INSERT INTO trust_tools
            (id, tenant_id, connection_id, namespace,
             external_id, name, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "f01-tool", "local-dev", connection_id,
            "github", "read", "Read", now, now,
        ))

        if resource_type == "trust_links":
            db.execute("""
                INSERT INTO trust_links
                (id, tenant_id, agent_id, tool_id,
                 evidence_type, evidence_reference,
                 first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "f01-link", "local-dev", "agt-example",
                "f01-tool", "declared_configuration",
                "test:evidence", now, now,
            ))


def _f01_evidence_exists(db, connection_id, resource_type):
    if resource_type == "provider_inventory":
        return db.execute(
            "SELECT COUNT(*) FROM provider_inventory "
            "WHERE connection_id=?",
            (connection_id,),
        ).fetchone()[0] == 1

    tool_exists = db.execute(
        "SELECT COUNT(*) FROM trust_tools WHERE connection_id=?",
        (connection_id,),
    ).fetchone()[0] == 1

    if resource_type == "trust_tools":
        return tool_exists

    return tool_exists and db.execute(
        "SELECT COUNT(*) FROM trust_links "
        "WHERE id='f01-link' AND tool_id='f01-tool'"
    ).fetchone()[0] == 1


# F01.13.6: Verified Google API integration.
# These tests use simulated connector responses; no Google calls occur.

def _f01_google_connection(client, label):
    created = client.post('/api/connections', json={
        'provider': 'google_agent_engine',
        'label': label,
        'env_prefix': 'F01_GOOGLE',
        'scope': {
            'project_id': 'sample-project',
            'location': 'us-central1',
        },
    })
    assert created.status_code == 201, created.text
    return created.json()['id']


def _f01_google_agent(value):
    return connectors.DiscoveredAgent(
        'projects/sample-project/locations/'
        f'us-central1/reasoningEngines/{value}',
        f'Google Agent {value}',
        'Google Agent Engine',
    )


def _f01_mock_google_discovery(monkeypatch, agents, receipt_connection=None):
    from game import main as module
    from game.discovery_provenance import _issue_connector_receipt

    # Keep legacy path isolated from real provider credentials/network.
    monkeypatch.setattr(
        module,
        '_discover_with_connection',
        lambda configured: list(agents),
    )

    def verified(configured, google_credentials=None):
        source = dict(configured)
        if receipt_connection is not None:
            source['id'] = receipt_connection

        return (
            list(agents),
            _issue_connector_receipt(source, agents),
        )

    monkeypatch.setattr(
        connectors,
        'discover_google_with_provenance',
        verified,
    )


def test_f01_google_api_creates_and_reuses_canonical_mapping(
    client, monkeypatch
):
    from game.db import connection
    from game.identity import initialize_identity_schema

    cid = _f01_google_connection(client, 'F01 Google A')

    with connection() as db:
        initialize_identity_schema(db)

    _f01_mock_google_discovery(
        monkeypatch, [_f01_google_agent('123')]
    )

    url = f'/api/connections/{cid}/discover'

    first = client.post(url)
    assert first.status_code == 200, first.text

    with connection() as db:
        original = db.execute("""
            SELECT a.id, r.canonical_agent_id
            FROM discovered_agents a
            JOIN agent_legacy_references r
              ON r.legacy_agent_id=a.id
             AND r.tenant_id=a.tenant_id
             AND r.source_table='discovered_agents'
            WHERE a.connection_id=?
        """, (cid,)).fetchone()

        assert original is not None
        original_identity = tuple(original)

    second = client.post(url)
    assert second.status_code == 200, second.text

    with connection() as db:
        after = db.execute("""
            SELECT a.id, r.canonical_agent_id
            FROM discovered_agents a
            JOIN agent_legacy_references r
              ON r.legacy_agent_id=a.id
             AND r.tenant_id=a.tenant_id
             AND r.source_table='discovered_agents'
            WHERE a.connection_id=?
        """, (cid,)).fetchone()

        assert tuple(after) == original_identity

        assert db.execute(
            'SELECT COUNT(*) FROM agent_identity_mappings'
        ).fetchone()[0] == 1

        assert db.execute(
            'SELECT COUNT(*) FROM canonical_agents'
        ).fetchone()[0] == 1


def test_f01_google_api_reuses_verified_identity_across_connections(
    client, monkeypatch
):
    from game.db import connection
    from game.identity import initialize_identity_schema

    first_cid = _f01_google_connection(client, 'F01 Source A')
    second_cid = _f01_google_connection(client, 'F01 Source B')

    with connection() as db:
        initialize_identity_schema(db)

    _f01_mock_google_discovery(
        monkeypatch, [_f01_google_agent('123')]
    )

    first = client.post(
        f'/api/connections/{first_cid}/discover'
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f'/api/connections/{second_cid}/discover'
    )
    assert second.status_code == 200, second.text

    with connection() as db:
        associations = db.execute("""
            SELECT a.connection_id, r.canonical_agent_id
            FROM discovered_agents a
            JOIN agent_legacy_references r
              ON r.legacy_agent_id=a.id
             AND r.tenant_id=a.tenant_id
             AND r.source_table='discovered_agents'
            WHERE a.connection_id IN (?, ?)
            ORDER BY a.connection_id
        """, (first_cid, second_cid)).fetchall()

        assert len(associations) == 2
        assert {
            row['connection_id'] for row in associations
        } == {first_cid, second_cid}

        # Both inventory records refer to the same verified agent.
        assert len({
            row['canonical_agent_id']
            for row in associations
        }) == 1

        assert db.execute(
            "SELECT COUNT(*) FROM canonical_agents"
        ).fetchone()[0] == 1

        assert db.execute(
            "SELECT COUNT(*) FROM agent_identity_mappings"
        ).fetchone()[0] == 1

        assert db.execute(
            "SELECT COUNT(*) FROM agent_legacy_references"
        ).fetchone()[0] == 2

        assert db.execute(
            "SELECT COUNT(*) FROM discovered_agents"
        ).fetchone()[0] == 2



def test_f01_google_api_rejects_wrong_connection_receipt(
    client, monkeypatch
):
    from game.db import connection
    from game.identity import initialize_identity_schema

    cid = _f01_google_connection(client, 'F01 Receipt Test')

    with connection() as db:
        initialize_identity_schema(db)

    _f01_mock_google_discovery(
        monkeypatch,
        [_f01_google_agent('123')],
        receipt_connection='different-connection',
    )

    response = client.post(
        f'/api/connections/{cid}/discover'
    )
    assert response.status_code == 409, response.text

    with connection() as db:
        for table in (
            'discovered_agents',
            'canonical_agents',
            'agent_legacy_references',
            'agent_identity_mappings',
        ):
            assert db.execute(
                f'SELECT COUNT(*) FROM {table}'
            ).fetchone()[0] == 0


def test_f01_foundry_discovery_remains_inventory_only(
    client, monkeypatch
):
    from game import main as module
    from game.db import connection
    from game.identity import initialize_identity_schema

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
    cid = created.json()['id']

    with connection() as db:
        initialize_identity_schema(db)

    monkeypatch.setattr(
        module,
        '_discover_with_connection',
        lambda configured: [
            connectors.DiscoveredAgent(
                'foundry-agent-123',
                'Existing Foundry Agent',
                'Microsoft Foundry',
            )
        ],
    )

    result = client.post(
        f'/api/connections/{cid}/discover'
    )
    assert result.status_code == 200, result.text

    with connection() as db:
        assert db.execute("""
            SELECT COUNT(*) FROM discovered_agents
            WHERE connection_id=?
        """, (cid,)).fetchone()[0] == 1

        assert db.execute(
            'SELECT COUNT(*) FROM agent_identity_mappings'
        ).fetchone()[0] == 0


def test_f01_google_missing_schema_fails_before_provider_call(
    client, monkeypatch
):
    from game import main as module

    cid = _f01_google_connection(client, 'F01 No Schema')

    def forbidden_discovery(configured):
        raise AssertionError(
            "Provider discovery must not run without F01 schema"
        )

    monkeypatch.setattr(
        module,
        '_discover_verified_google_with_connection',
        forbidden_discovery,
    )

    result = client.post(
        f'/api/connections/{cid}/discover'
    )

    assert result.status_code == 503, result.text

    from game.db import connection
    with connection() as db:
        assert db.execute(
            'SELECT COUNT(*) FROM discovered_agents'
        ).fetchone()[0] == 0


def test_f01_google_rejects_stale_connection_configuration(
    client, monkeypatch
):
    import json

    from game import main as module
    from game.db import connection
    from game.identity import initialize_identity_schema
    from game.discovery_provenance import _issue_connector_receipt

    cid = _f01_google_connection(client, 'F01 Stale Target')

    with connection() as db:
        initialize_identity_schema(db)

    agent = _f01_google_agent('123')

    def change_target_during_discovery(configured):
        receipt = _issue_connector_receipt(
            configured, [agent]
        )

        # Simulate another administrator changing the target
        # while remote discovery is in progress.
        with connection() as db:
            db.execute("""
                UPDATE provider_connections
                SET scope_json=?
                WHERE id=?
            """, (
                json.dumps({
                    'project_id': 'other-project',
                    'location': 'us-central1',
                }),
                cid,
            ))

        return [agent], receipt

    monkeypatch.setattr(
        module,
        '_discover_verified_google_with_connection',
        change_target_during_discovery,
    )

    response = client.post(
        f'/api/connections/{cid}/discover'
    )

    assert response.status_code == 409, response.text

    with connection() as db:
        for table in (
            'discovered_agents',
            'canonical_agents',
            'agent_legacy_references',
            'agent_identity_mappings',
        ):
            assert db.execute(
                f'SELECT COUNT(*) FROM {table}'
            ).fetchone()[0] == 0


def test_f01_google_audit_failure_rolls_back_everything(
    client, monkeypatch
):
    from game import main as module
    from game.db import connection
    from game.identity import initialize_identity_schema

    cid = _f01_google_connection(client, 'F01 Audit Rollback')

    with connection() as db:
        initialize_identity_schema(db)

    _f01_mock_google_discovery(
        monkeypatch, [_f01_google_agent('123')]
    )

    with connection() as db:
        audit_before = db.execute(
            'SELECT COUNT(*) FROM audit_events'
        ).fetchone()[0]

    def fail_audit(db, actor, operation, resource_id):
        if operation == 'connection.discover':
            raise RuntimeError('simulated audit failure')

    monkeypatch.setattr(module, '_audit', fail_audit)

    with pytest.raises(
        RuntimeError, match='simulated audit failure'
    ):
        client.post(f'/api/connections/{cid}/discover')

    with connection() as db:
        for table in (
            'discovered_agents',
            'canonical_agents',
            'agent_legacy_references',
            'agent_identity_mappings',
        ):
            assert db.execute(
                f'SELECT COUNT(*) FROM {table}'
            ).fetchone()[0] == 0

        assert db.execute(
            'SELECT COUNT(*) FROM audit_events'
        ).fetchone()[0] == audit_before

        row = db.execute("""
            SELECT last_synced_at
            FROM provider_connections
            WHERE id=?
        """, (cid,)).fetchone()

        assert row['last_synced_at'] is None


def test_f01_google_rejects_credentials_rotated_during_discovery(
    client, monkeypatch
):
    from game import main as module
    from game.db import connection
    from game.identity import initialize_identity_schema
    from game.discovery_provenance import _issue_connector_receipt

    cid = _f01_google_connection(client, 'F01 Credential Rotation')

    with connection() as db:
        initialize_identity_schema(db)

        # Synthetic ciphertext is used only to exercise the
        # credential snapshot check. No decryption is attempted.
        db.execute("""
            INSERT INTO provider_credentials (
                connection_id, encrypted_json,
                saved_at, rotated_at, tenant_id
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            cid, 'synthetic-original-ciphertext',
            '2026-11-27T10:00:00Z',
            '2026-11-27T10:00:00Z',
            'local-dev',
        ))

    discovered = [_f01_google_agent('123')]

    def rotate_during_discovery(configured):
        receipt = _issue_connector_receipt(
            configured, discovered
        )

        with connection() as db:
            db.execute("""
                UPDATE provider_credentials
                SET encrypted_json=?, rotated_at=?
                WHERE connection_id=? AND tenant_id=?
            """, (
                'synthetic-rotated-ciphertext',
                '2026-11-27T11:00:00Z',
                cid, 'local-dev',
            ))

        return discovered, receipt

    monkeypatch.setattr(
        module,
        '_discover_verified_google_with_connection',
        rotate_during_discovery,
    )

    response = client.post(
        f'/api/connections/{cid}/discover'
    )

    assert response.status_code == 409, response.text
    assert 'credentials changed' in response.json()['detail']

    with connection() as db:
        for table in (
            'discovered_agents',
            'canonical_agents',
            'agent_legacy_references',
            'agent_identity_mappings',
        ):
            assert db.execute(
                f'SELECT COUNT(*) FROM {table}'
            ).fetchone()[0] == 0

        assert db.execute("""
            SELECT encrypted_json FROM provider_credentials
            WHERE connection_id=?
        """, (cid,)).fetchone()[0] == (
            'synthetic-rotated-ciphertext'
        )


def test_f01_google_rejects_credentials_added_during_discovery(
    client, monkeypatch
):
    from game import main as module
    from game.db import connection
    from game.identity import initialize_identity_schema
    from game.discovery_provenance import _issue_connector_receipt

    cid = _f01_google_connection(client, 'F01 Credentials Added')

    with connection() as db:
        initialize_identity_schema(db)

    discovered = [_f01_google_agent('456')]

    def add_credentials_during_discovery(configured):
        receipt = _issue_connector_receipt(
            configured, discovered
        )

        with connection() as db:
            db.execute("""
                INSERT INTO provider_credentials (
                    connection_id, encrypted_json,
                    saved_at, rotated_at, tenant_id
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                cid, 'synthetic-new-ciphertext',
                '2026-11-27T11:00:00Z',
                '2026-11-27T11:00:00Z',
                'local-dev',
            ))

        return discovered, receipt

    monkeypatch.setattr(
        module,
        '_discover_verified_google_with_connection',
        add_credentials_during_discovery,
    )

    response = client.post(
        f'/api/connections/{cid}/discover'
    )

    assert response.status_code == 409, response.text

    with connection() as db:
        for table in (
            'discovered_agents',
            'canonical_agents',
            'agent_legacy_references',
            'agent_identity_mappings',
        ):
            assert db.execute(
                f'SELECT COUNT(*) FROM {table}'
            ).fetchone()[0] == 0

        # Credential replacement is a separate committed operation.
        # Discovery rollback must not undo that legitimate change.
        assert db.execute("""
            SELECT COUNT(*) FROM provider_credentials
            WHERE connection_id=?
        """, (cid,)).fetchone()[0] == 1


def test_f01_manual_agent_blocks_connection_removal(client):
    created = client.post('/api/connections', json={
        'provider': 'aws_agentcore',
        'label': 'Manual Agent Protected Connection',
        'env_prefix': 'F01_AWS',
        'scope': {'region': 'us-east-1'},
    })
    assert created.status_code == 201, created.text
    cid = created.json()['id']

    agent = client.post('/api/agents', json={
        'name': 'Manually Registered Agent',
        'provider': 'aws_agentcore',
        'connection_id': cid,
    })
    assert agent.status_code == 201, agent.text

    removed = client.delete(f'/api/connections/{cid}')
    assert removed.status_code == 409, removed.text

    assert client.get(
        f"/api/agents/{agent.json()['id']}"
    ).status_code == 200


def test_f01_manual_agent_blocks_connection_scope_change(client):
    created = client.post('/api/connections', json={
        'provider': 'aws_agentcore',
        'label': 'Manual Agent Scope Protection',
        'env_prefix': 'F01_AWS',
        'scope': {'region': 'us-east-1'},
    })
    assert created.status_code == 201, created.text
    cid = created.json()['id']

    agent = client.post('/api/agents', json={
        'name': 'Manually Registered Agent',
        'provider': 'aws_agentcore',
        'connection_id': cid,
    })
    assert agent.status_code == 201, agent.text

    changed = client.patch(
        f'/api/connections/{cid}',
        json={
            'label': 'Changed Connection',
            'env_prefix': 'F01_AWS',
            'scope': {'region': 'us-west-2'},
            'auth_mode': 'legacy',
            'auth_config': {},
        },
    )
    assert changed.status_code == 409, changed.text

    assert client.get(
        f"/api/agents/{agent.json()['id']}"
    ).status_code == 200
