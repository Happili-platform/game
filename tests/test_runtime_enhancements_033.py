# SPDX-License-Identifier: AGPL-3.0-only
"""Regression coverage: retention, period scoping, quiet collector health and HTTP outcomes."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
from fastapi.testclient import TestClient
import pytest
from game.main import app
from game.db import connection, initialize

TOKEN='collector-secret-for-game-runtime-0000001'
TRACE='d'*32

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('GAME_DB_PATH',str(tmp_path/'data.db'))
    monkeypatch.setenv('GAME_VAULT_KEY_PATH',str(tmp_path/'key'))
    monkeypatch.setenv('GAME_RUNTIME_INGEST_TOKEN',TOKEN)
    with TestClient(app) as c:
        yield c

def test_collection_health_while_existing_history_remains(client):
    agent=client.post('/api/agents',json={'name':'Real agent metadata','provider':'Custom'}).json()
    auth={'X-GAME-Ingest-Token':TOKEN}
    p={'agent_id':agent['id'],'source':'azure_foundry_logs','external_run_id':TRACE,
       'trace_id':TRACE,'status':'unknown','started_at':'2026-11-01T12:00:00Z','spans':[]}
    assert client.post('/api/runtime/ingest',json=p,headers=auth).status_code==201
    old=client.get('/api/runtime/summary?period=all').json()
    assert old['historical_runs']==1 and old['runs']==1
    recent=client.get('/api/runtime/summary?period=24h').json()
    assert recent['runs']==0 and recent['historical_runs']==1
    assert client.get('/api/runtime/runs?period=24h').json()==[]
    assert len(client.get('/api/runtime/runs?period=all').json())==1
    health={'source':'azure_foundry_logs','window_start':'2026-11-09T10:00:00Z',
            'window_end':'2026-11-09T11:00:00Z','metadata_rows':0,'trace_groups':0,
            'eligible':0,'imported':0,'replayed':0,'failed':0}
    assert client.post('/api/runtime/collection-status',json=health).status_code==401
    assert client.post('/api/runtime/collection-status',json=health,headers=auth).status_code==201
    initialize()
    report=client.get('/api/runtime/summary?period=24h').json()
    assert report['runs']==0 and report['historical_runs']==1
    assert report['last_successful_collection_at'] is not None
    assert report['collections'][0]['metadata_rows']==0
    assert report['cost_status']=='Not tracked'
    health['failed']=1
    assert client.post('/api/runtime/collection-status',json=health,headers=auth).status_code==422
    assert client.get('/api/runtime/summary?period=all').json()['runs']==1


def test_outcome_http_result_code_only_for_requests():
    path=Path(__file__).resolve().parents[1]/'scripts'/'collect_azure_foundry.py'
    spec=importlib.util.spec_from_file_location('foundry_collector_improved',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.outcome({'_table':'AppRequests','Success':None,'ResultCode':'200'})=='success'
    assert module.outcome({'_table':'AppRequests','Success':None,'ResultCode':'429'})=='failure'
    assert module.outcome({'_table':'AppRequests','Success':None,'ResultCode':'0'})=='unknown'
    assert module.outcome({'_table':'AppDependencies','Success':None,'ResultCode':'500'})=='unknown'
    assert module.outcome({'_table':'AppRequests','Success':False,'ResultCode':'200'})=='failure'


def test_scope_and_missing_period(client):
    agent=client.post('/api/agents',json={'name':'Known agent','provider':'Custom'}).json()
    auth={'X-GAME-Ingest-Token':TOKEN}
    for stamp,tid in [('2026-11-01T12:00:00Z','a'*32),('2026-11-09T12:00:00Z','b'*32)]:
        p={'agent_id':agent['id'],'source':'otel_adapter','external_run_id':tid,'status':'success',
           'trace_id':tid,'started_at':stamp,'spans':[]}
        assert client.post('/api/runtime/ingest',json=p,headers=auth).status_code==201
    all_rows=client.get('/api/runtime/summary?period=all').json()
    assert all_rows['runs']==2 and len(all_rows['daily_trend'])==2
    assert client.get('/api/runtime/summary?period=broken').status_code==422

def test_mac_launchd_plist_contains_no_secret(tmp_path,monkeypatch):
    import sys
    import plistlib
    import importlib.util
    from pathlib import Path
    script=Path(__file__).resolve().parents[1]/'scripts'/'install_azure_collector_launchd.py'
    spec=importlib.util.spec_from_file_location('game_launchd_installer',script)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv('HOME',str(tmp_path))
    # pathlib.home() uses the user home, so test only output structure here.
    project=tmp_path/'project'
    (project/'.venv/bin').mkdir(parents=True)
    (project/'.venv/bin/python').touch()
    (project/'scripts').mkdir()
    (project/'scripts/run_azure_foundry_scheduled.py').touch()
    mapping=tmp_path/'mapping.json'
    mapping.write_text('{}')
    job=module.make_plist(project,'a'*36,mapping,900,60,5)
    assert job['StartInterval']==900 and job['RunAtLoad'] is False
    assert 'GAME_RUNTIME_INGEST_TOKEN' not in str(job)
    assert 'AZURE_CLIENT_SECRET' not in str(job)
    assert job['ProgramArguments'][0]==str(project/'.venv/bin/python')
