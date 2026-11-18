# SPDX-License-Identifier: AGPL-3.0-only
"""Contract and upgrade checks for the first v0.3.3 runtime increment."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from game.db import connection, initialize
from game.main import app

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('GAME_DB_PATH',str(tmp_path/'test.db'))
    monkeypatch.setenv('GAME_VAULT_KEY_PATH',str(tmp_path/'master.key'))
    with TestClient(app) as c:
        yield c

TOKEN='collector-secret-for-game-runtime-0000001'
TRACE='a'*32
START='2026-11-06T12:00:00Z'
END='2026-11-06T12:00:01Z'


def payload(agent_id):
    return {'agent_id':agent_id,'source':'otel_adapter','external_run_id':'live-451',
            'trace_id':TRACE,'status':'success','started_at':START,'ended_at':END,
            'spans':[{'span_id':'b'*16,'trace_id':TRACE,'kind':'tool',
                      'name':'search-issues','status':'success','started_at':START,'ended_at':END}]}


def test_collector_roundtrip_replay_and_missing_cost(client,monkeypatch):
    monkeypatch.setenv('GAME_RUNTIME_INGEST_TOKEN',TOKEN)
    a=client.post('/api/agents',json={'name':'Real metadata agent','provider':'Custom'}).json()
    body=payload(a['id'])
    assert client.post('/api/runtime/ingest',json=body).status_code==401
    auth={'X-GAME-Ingest-Token':TOKEN}
    created=client.post('/api/runtime/ingest',json=body,headers=auth)
    assert created.status_code==201,created.text
    assert created.json()['replayed'] is False
    replay=client.post('/api/runtime/ingest',json=body,headers=auth)
    assert replay.status_code==201 and replay.json()['replayed'] is True
    assert replay.json()['id']==created.json()['id']
    row=client.get('/api/runtime/runs').json()
    assert len(row)==1 and row[0]['duration_ms']==1000
    detail=client.get('/api/runtime/runs/'+created.json()['id']).json()
    assert len(detail['spans'])==1 and detail['spans'][0]['kind']=='tool'
    summary=client.get('/api/runtime/summary').json()
    assert summary['runs']==1 and summary['success_rate']==100 and summary['p95_duration_ms']==1000
    assert summary['cost_status']=='Not tracked'
    initialize()
    assert len(client.get('/api/runtime/runs').json())==1
    assert len(client.get('/api/runtime/runs/'+created.json()['id']).json()['spans'])==1


def test_unknown_values_and_partial_spans(client,monkeypatch):
    monkeypatch.setenv('GAME_RUNTIME_INGEST_TOKEN',TOKEN)
    a=client.post('/api/agents',json={'name':'Partial run','provider':'Custom'}).json()
    p=payload(a['id']);p['external_run_id']='partial';p['status']='unknown';p['ended_at']=None;p['spans']=[]
    auth={'X-GAME-Ingest-Token':TOKEN}
    assert client.post('/api/runtime/ingest',json=p,headers=auth).status_code==201
    s=client.get('/api/runtime/summary').json()
    assert s['runs']==1 and s['known_outcomes']==0 and s['success_rate'] is None
    assert s['p95_duration_ms'] is None
    p['status']='failure';p['ended_at']=END;p['spans']=payload(a['id'])['spans']
    assert client.post('/api/runtime/ingest',json=p,headers=auth).status_code==201
    s=client.get('/api/runtime/summary').json()
    assert s['runs']==1 and s['failures']==1 and s['success_rate']==0


def test_conflicts_invalid_metadata_and_missing_agent(client,monkeypatch):
    monkeypatch.setenv('GAME_RUNTIME_INGEST_TOKEN',TOKEN)
    auth={'X-GAME-Ingest-Token':TOKEN}
    assert client.post('/api/runtime/ingest',json=payload('nonexistent'),headers=auth).status_code==404
    a=client.post('/api/agents',json={'name':'Scoped demo-free agent','provider':'Custom'}).json()
    p=payload(a['id'])
    assert client.post('/api/runtime/ingest',json=p,headers=auth).status_code==201
    p['started_at']='2026-11-06T11:59:59Z'
    assert client.post('/api/runtime/ingest',json=p,headers=auth).status_code==409
    p=payload(a['id']);p['spans'][0]['name']='Bearer secret'
    assert client.post('/api/runtime/ingest',json=p,headers=auth).status_code==409
    p=payload(a['id']);p['prompt']='secret'
    assert client.post('/api/runtime/ingest',json=p,headers=auth).status_code==422
    p=payload(a['id']);p['spans'][0]['input']='sensitive text'
    assert client.post('/api/runtime/ingest',json=p,headers=auth).status_code==422
    p=payload(a['id']);p['started_at']='2026-11-06T12:00:00'
    assert client.post('/api/runtime/ingest',json=p,headers=auth).status_code==422
    p=payload(a['id']);p['ended_at']='2026-11-06T11:59:00Z'
    assert client.post('/api/runtime/ingest',json=p,headers=auth).status_code==422
    assert client.get('/api/runtime/runs/no-such-run').status_code==404


def test_no_collector_credentials_and_protection(client,monkeypatch):
    monkeypatch.delenv('GAME_RUNTIME_INGEST_TOKEN',raising=False)
    a=client.post('/api/agents',json={'name':'Collectable agent','provider':'Custom'}).json()
    assert client.post('/api/runtime/ingest',json=payload(a['id'])).status_code==503
    assert client.get('/api/runtime/runs').status_code==200
    assert client.get('/api/runtime/summary').json()['runs']==0


def test_existing_registered_data_survives_initialize(client):
    a=client.post('/api/agents',json={'name':'Legacy known agent','provider':'Azure'}).json()
    initialize();initialize()
    assert client.get('/api/agents/'+a['id']).status_code==200
    with connection() as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='runtime_runs'").fetchone()
        assert db.execute("SELECT COUNT(*) AS n FROM runtime_runs").fetchone()['n']==0


def test_viewer_has_read_only_runtime_access_in_password_mode(tmp_path,monkeypatch):
    from game import local_accounts
    monkeypatch.setenv('GAME_AUTH_MODE','password')
    monkeypatch.setenv('GAME_DB_PATH',str(tmp_path/'users.db'))
    monkeypatch.setenv('GAME_VAULT_KEY_PATH',str(tmp_path/'key'))
    monkeypatch.setenv('GAME_RUNTIME_INGEST_TOKEN',TOKEN)
    with TestClient(app) as admin, TestClient(app) as viewer:
        from game.local_accounts import create_user
        password='P@ssword0!'+'x'*10
        create_user('admin',password,'admin',scope={'kind':'all'},must_change=False)
        create_user('viewer',password,'viewer',scope={'kind':'all'},must_change=False)
        for client,name in ((admin,'admin'),(viewer,'viewer')):
            resp=client.post('/api/auth/login',json={'username':name,'password':'P@ssword0!'+'x'*10})
            assert resp.status_code==200,resp.text
        csrf=admin.get('/api/auth/session').json()['csrf_token']
        resp=admin.post('/api/agents',json={'name':'Scoped agent','provider':'Custom'},headers={'X-CSRF-Token':csrf})
        assert resp.status_code==201,resp.text
        a=resp.json()
        assert admin.post('/api/runtime/ingest',json=payload(a['id']),headers={'X-GAME-Ingest-Token':TOKEN}).status_code==201
        assert viewer.get('/api/runtime/runs').status_code==403
        assert viewer.get('/api/finops/summary').status_code==403
        assert viewer.get('/api/finops/azure-costs').status_code==403
        assert viewer.post('/api/agents',json={'name':'Nope','provider':'Test'}).status_code==403
