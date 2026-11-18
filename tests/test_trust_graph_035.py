# SPDX-License-Identifier: AGPL-3.0-only
"""Trust graph evidence semantics, isolation, and authorization regression tests."""
from fastapi.testclient import TestClient
from game.main import app
from game.db import connection
import pytest

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('GAME_DB_PATH', str(tmp_path/'test.db'))
    monkeypatch.setenv('GAME_VAULT_KEY_PATH', str(tmp_path/'vault'/'key'))
    monkeypatch.setenv('GAME_DEMO_DATA', 'false')
    with TestClient(app) as c:
        yield c


def seed_connection(client):
    with connection() as db:
        db.execute('''INSERT INTO provider_connections
          (id, provider, label, scope_json, env_prefix, created_at, tenant_id)
          VALUES (?,?,?,?,?,?,?)''', ('con-test','github','GitHub test','{}','TEST','2026-01-01T00:00:00Z','local-dev'))


def test_empty_readonly_graph(client):
    data = client.get('/api/trust-graph')
    assert data.status_code == 200
    assert data.json()['tools']==[]
    assert data.json()['links']==[]


def test_upsert_tool_and_declared_link_not_execution(client):
    seed_connection(client)
    agent=client.post('/api/agents',json={'name':'Trust graph agent','provider':'github'}).json()
    payload={'connection_id':'con-test','namespace':'github-org:example',
             'tools':[{'external_id':'issues/read','name':'Read issues','capability':'read'}]}
    r=client.post('/api/trust-graph/tools/snapshot',json=payload)
    assert r.status_code==200, r.text
    assert r.json()['execution_evidence'] is False
    tools=client.get('/api/trust-graph').json()['tools']
    assert len(tools)==1
    tool_id=tools[0]['id']
    payload['tools'][0]['name']='Read GitHub issues'
    client.post('/api/trust-graph/tools/snapshot',json=payload)
    assert client.get('/api/trust-graph').json()['tools'][0]['id']==tool_id
    assert client.get('/api/trust-graph').json()['tools'][0]['name']=='Read GitHub issues'
    link={'agent_id':agent['id'],'tool_id':tool_id,'evidence_type':'declared_configuration',
          'evidence_reference':'config://agents/trust-graph-agent'}
    r=client.post('/api/trust-graph/links',json=link)
    assert r.status_code==201, r.text
    assert r.json()['executed'] is False
    link_id=r.json()['id']
    assert client.post('/api/trust-graph/links',json=link).json()['id']==link_id
    assert len(client.get('/api/trust-graph').json()['links'])==1


def test_reject_unknown_connection_agent_and_duplicate_tools(client):
    assert client.post('/api/trust-graph/tools/snapshot',json={
        'connection_id':'missing','namespace':'test','tools':[]}).status_code==404
    seed_connection(client)
    assert client.post('/api/trust-graph/tools/snapshot',json={
        'connection_id':'con-test','namespace':'test',
        'tools':[{'external_id':'a','name':'A'},{'external_id':'a','name':'B'}]}).status_code==422
    assert client.post('/api/trust-graph/links',json={'agent_id':'missing','tool_id':'missing',
        'evidence_type':'observed_invocation','evidence_reference':'event-1'}).status_code==404
    assert client.post('/api/trust-graph/links',json={'agent_id':'missing','tool_id':'missing',
        'evidence_type':'speculation','evidence_reference':'event-1'}).status_code==422


def test_tenant_isolation(client):
    seed_connection(client)
    with connection() as db:
        db.execute("INSERT INTO tenants(id,name,created_at) VALUES ('other','Other','2026-01-01')")
        db.execute("""INSERT INTO trust_tools VALUES
            ('hidden','other','con-test','other','tool','Hidden','','read','2026-01-01','2026-01-01')""")
    assert client.get('/api/trust-graph').json()['tools']==[]
