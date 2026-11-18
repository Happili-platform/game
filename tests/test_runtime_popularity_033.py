# SPDX-License-Identifier: AGPL-3.0-only
"""Runtime popularity: accurate counts, search, bounded chart, and scope control."""
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from game.main import app

TOKEN = 'collector-secret-for-game-runtime-popularity-0001'

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('GAME_DB_PATH', str(tmp_path / 'test.db'))
    monkeypatch.setenv('GAME_VAULT_KEY_PATH', str(tmp_path / 'key'))
    monkeypatch.setenv('GAME_RUNTIME_INGEST_TOKEN', TOKEN)
    with TestClient(app) as c:
        yield c


def add_agent_runs(client, name, count, offset=0):
    agent = client.post('/api/agents', json={'name': name, 'provider': 'Custom'}).json()
    start = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    if start > datetime.now(timezone.utc):
        start -= timedelta(days=1)
    for i in range(count):
        t = start - timedelta(days=(i+offset) % 4)
        response = client.post('/api/runtime/ingest', json={
            'agent_id': agent['id'], 'source': 'otel_adapter',
            'external_run_id': f'{name.replace(" ", "-")}-{i}',
            'status': 'unknown', 'started_at': t.isoformat(), 'spans': []
        }, headers={'X-GAME-Ingest-Token': TOKEN})
        assert response.status_code == 201, response.text
    return agent['id']


def test_ranking_and_others_are_reconciled(client):
    a = add_agent_runs(client, 'Alpha', 5)
    b = add_agent_runs(client, 'Beta', 3)
    c = add_agent_runs(client, 'Gamma', 2)
    response = client.get('/api/runtime/popularity?period=all&top_n=2')
    assert response.status_code == 200
    data = response.json()
    assert data['runs'] == data['scope_total_runs'] == 10
    assert [a['name'] for a in data['ranking']] == ['Alpha', 'Beta']
    assert [a['runs'] for a in data['ranking']] == [5, 3]
    assert data['others_runs'] == 2 and data['others_agents'] == 1
    assert round(sum(a['share_pct'] for a in data['ranking'])) == 80
    assert sum(day['total'] for day in data['daily']) == 10
    assert sum(day['others'] for day in data['daily']) == 2
    assert all(sum(day['by_agent'].values()) + day['others'] == day['total'] for day in data['daily'])
    one = client.get('/api/runtime/popularity', params={'agent_id': c, 'period': 'all'}).json()
    assert one['runs'] == one['scope_total_runs'] == 2
    assert one['ranking'][0]['agent_id'] == c
    assert one['others_runs'] == 0
    search = client.get('/api/runtime/popularity', params={'search': 'bet', 'period': 'all'}).json()
    assert search['runs'] == 3 and search['scope_total_runs'] == 10
    assert search['ranking'][0]['agent_id'] == b
    assert sum(d['total'] for d in search['daily']) == 3
    assert client.get('/api/runtime/popularity?top_n=21').status_code == 422
    assert client.get('/api/runtime/popularity?period=bad').status_code == 422


def test_empty_and_no_invented_runs(client):
    r = client.get('/api/runtime/popularity?period=all')
    assert r.status_code == 200
    d = r.json()
    assert d['runs'] == d['scope_total_runs'] == 0
    assert d['ranking'] == [] and d['daily'] == []
    assert d['others_runs'] == 0


def test_popularity_route_is_reachable_and_matching_assets_shipped(client):
    from pathlib import Path
    project = Path(__file__).resolve().parents[1]
    html = (project / 'static/index.html').read_text()
    js = (project / 'static/app.js').read_text()
    css = (project / 'static/style.css').read_text()
    for element in ('runtimeTopN', 'runtimePopularitySearch', 'runtimePopularity', 'runtimeTrend'):
        assert f'id="{element}"' in html
        assert element in js
    assert '--runtime-series-01' in css
    assert '--runtime-series-others' in css
    route = client.get('/api/runtime/popularity?period=all&top_n=5')
    assert route.status_code == 200 and route.headers['content-type'].startswith('application/json')
    assert set(('ranking','daily','others_runs','scope_total_runs')).issubset(route.json())

def test_top_n_works_for_large_agent_catalog(client):
    # Fast, isolated fixture: many stored agents without repeated HTTP ingestion cost.
    from game.db import connection
    with connection() as db:
        for i in range(24):
            aid = f'bulk-{i:03}'
            db.execute('''INSERT INTO agents(id,name,provider,environment,approval_status,
              lifecycle_status,created_at,tenant_id)
              VALUES (?,?,?,?,?,?,?,?)''',
              (aid, f'Agent-{i:03}', 'Custom', 'development','pending','active',
               '2026-11-09T12:00:00Z','local-dev'))
            db.execute('''INSERT INTO runtime_runs(id,tenant_id,agent_id,source,
              external_run_id,status,started_at,first_ingested_at,last_ingested_at)
              VALUES (?,?,?,?,?,?,?,?,?)''',
              (f'bulk-run-{i:03}','local-dev',aid,'otel_adapter',f'ext-{i:03}',
               'unknown','2026-11-09T12:00:00Z','2026-11-09T12:00:00Z','2026-11-09T12:00:00Z'))
    response = client.get('/api/runtime/popularity?period=all&top_n=20')
    assert response.status_code == 200
    data = response.json()
    assert data['active_agents'] == 24
    assert len(data['ranking']) == 20
    assert data['others_runs'] == 4
    assert data['others_agents'] == 4
    assert sum(day['total'] for day in data['daily']) == 24
