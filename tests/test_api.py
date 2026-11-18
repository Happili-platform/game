# SPDX-License-Identifier: AGPL-3.0-only
import os

import pytest
from fastapi.testclient import TestClient

from game.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('GAME_VAULT_KEY_PATH', str(tmp_path / 'vault' / 'master.key'))
    monkeypatch.setenv('GAME_DB_PATH', str(tmp_path / 'test.db'))
    monkeypatch.setenv('GAME_DEMO_DATA', 'false')
    with TestClient(app) as c:
        yield c


def test_empty_registry_and_health(client):
    assert client.get('/api/health').json()['status'] == 'ok'
    assert client.get('/api/agents').json() == []
    overview = client.get('/api/overview').json()
    assert overview['totals']['agents'] == 0
    assert overview['totals']['monthly_spend_usd'] == 0


def test_unowned_production_agent_is_flagged(client):
    r = client.post('/api/agents', json={
        'name': 'Invoice processor', 'provider': 'Custom / Python',
        'environment': 'production', 'approval_status': 'pending',
        'budget_usd': 30, 'sensitive_access': True,
    })
    assert r.status_code == 201, r.text
    a = r.json()
    codes = {finding['code'] for finding in a['findings']}
    assert 'MISSING_OWNER' in codes
    assert 'PRODUCTION_NOT_APPROVED' in codes
    assert 'SENSITIVE_ACCESS_UNAPPROVED' in codes
    assert 'STALE_AGENT' in codes
    assert a['risk_level'] == 'high'
    overview = client.get('/api/overview').json()
    assert overview['totals']['missing_owners'] == 1
    assert overview['totals']['flagged_agents'] == 1


def test_cost_alert_and_usage(client):
    created = client.post('/api/agents', json={
        'name': 'Budget tester', 'provider': 'Test Provider',
        'environment': 'development', 'approval_status': 'pending',
        'owner_email': 'team@example.com', 'budget_usd': 10,
    }).json()
    r = client.post('/api/usage', json={
        'agent_id': created['id'], 'cost_usd': 12.75,
        'input_tokens': 300, 'output_tokens': 100, 'outcome': 'success'
    })
    assert r.status_code == 201
    detail = client.get('/api/agents/' + created['id']).json()
    assert detail['monthly_spend_usd'] == 12.75
    assert 'OVER_BUDGET' in {f['code'] for f in detail['findings']}
    assert 'STALE_AGENT' not in {f['code'] for f in detail['findings']}
    assert detail['risk_level'] == 'medium'
    assert len(detail['recent_usage']) == 1
    assert client.get('/api/overview').json()['totals']['monthly_spend_usd'] == 12.75


def test_unknown_agent_and_invalid_usage_rejected(client):
    assert client.get('/api/agents/no-such-id').status_code == 404
    assert client.post('/api/usage', json={'agent_id':'invalid','cost_usd':7}).status_code == 404
    assert client.post('/api/usage', json={'agent_id':'invalid','cost_usd':-1}).status_code == 422
    assert client.post('/api/agents', json={'name':'x', 'provider':'Provider'}).status_code == 422


def test_empty_database_never_seeds_demo_data(tmp_path, monkeypatch):
    monkeypatch.setenv('GAME_VAULT_KEY_PATH', str(tmp_path / 'vault' / 'master.key'))
    monkeypatch.setenv('GAME_DB_PATH', str(tmp_path / 'demo.db'))
    monkeypatch.setenv('GAME_DEMO_DATA', 'true')
    with TestClient(app) as c:
        agents = c.get('/api/agents').json()
        assert agents == []
    with TestClient(app) as c:
        assert c.get('/api/agents').json() == []
