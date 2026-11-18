# SPDX-License-Identifier: AGPL-3.0-only
"""Automatic Foundry discovery/attribution without network access or manual JSON."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from fastapi.testclient import TestClient
import pytest
from game.main import app
from game.db import connection
from game import main as main_module

TOKEN = 'a-secure-collector-test-token-of-at-least-32-characters'
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'collect_azure_foundry.py'
spec=importlib.util.spec_from_file_location('test_auto_foundry_collector',SCRIPT)
collector=importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('GAME_DB_PATH',str(tmp_path/'database.db'))
    monkeypatch.setenv('GAME_RUNTIME_INGEST_TOKEN',TOKEN)
    with TestClient(app) as c: yield c

def _connection():
    with connection() as db:
        db.execute("""INSERT INTO provider_connections(id,provider,label,scope_json,env_prefix,created_at,tenant_id,auth_mode,auth_config_json)
            VALUES ('conn-foundry','microsoft_foundry','Foundry',?, 'SAMPLE','2026-11-09T00:00:00Z', ?, 'legacy','{}')""",
            ('{"project_endpoint":"https://test.services.ai.azure.com/api/projects/myproject"}', __import__('game.auth',fromlist=['LOCAL_TENANT']).LOCAL_TENANT))

def test_synced_inventory_resolves_both_agents(client,monkeypatch):
    _connection()
    monkeypatch.setattr(main_module,'_discover_with_connection',lambda cfg:[
        SimpleNamespace(external_id='patient-access-and-scheduling:1',name='patient-access-and-scheduling',provider='Microsoft Foundry',description='',provider_status='active'),
        SimpleNamespace(external_id='health-plan-member-services:2',name='health-plan-member-services',provider='Microsoft Foundry',description='',provider_status='active'),
    ])
    result=client.post('/api/runtime/azure-inventory-sync',headers={'X-GAME-Ingest-Token':TOKEN})
    assert result.status_code==200,result.text
    assert result.json()['discovered']==2
    mapping,info=collector.automatic_mapping(result.json()['agents'])
    assert len(mapping)>=4 and info['collisions']==0
    assert mapping['patient-access-and-scheduling:1']==mapping['patient-access-and-scheduling']
    assert mapping['health-plan-member-services:2']==mapping['health-plan-member-services']
    assert mapping['patient-access-and-scheduling']!=mapping['health-plan-member-services']
    assert client.post('/api/runtime/azure-inventory-sync').status_code==401
    again=client.post('/api/runtime/azure-inventory-sync',headers={'X-GAME-Ingest-Token':TOKEN})
    assert again.status_code==200
    assert [a['id'] for a in again.json()['agents']]==[a['id'] for a in result.json()['agents']]

def test_fail_closed_for_ambiguous_names():
    agents=[{'id':'ext-1','name':'same','external_id':'same:1','connection_id':'a'},
            {'id':'ext-2','name':'same','external_id':'same:2','connection_id':'b'}]
    mapping,info=collector.automatic_mapping(agents)
    assert 'same' not in mapping and info['collisions']==1
    assert mapping['same:1']=='ext-1' and mapping['same:2']=='ext-2'
    # telemetry containing only ambiguous name is never imported
    rows=[{'OperationId':'a'*32,'TimeGenerated':'2026-11-09T10:00:00Z',
           'Properties':{'gen_ai.agent.name':'same'},'_table':'AppRequests','Id':'b'*16}]
    assert collector.normalize(rows,mapping)[1]['unattributed']==1

def test_launchd_without_mapping(tmp_path):
    source=Path(__file__).resolve().parents[1]/'scripts/install_azure_collector_launchd.py'
    spec=importlib.util.spec_from_file_location('auto_foundry_launchd',source)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    project=tmp_path/'project'
    (project/'.venv/bin').mkdir(parents=True)
    (project/'.venv/bin/python').touch()
    (project/'scripts').mkdir()
    (project/'scripts/run_azure_foundry_scheduled.py').touch()
    plist=mod.make_plist(project,'a'*36,None,300,60,5)
    assert '--mapping' not in plist['ProgramArguments']
    assert plist['StartInterval']==300


def test_foundry_readiness_without_connection(client):
    headers = {'X-GAME-Ingest-Token': TOKEN}

    assert client.get(
        '/api/runtime/azure-inventory-ready'
    ).status_code == 401

    response = client.get(
        '/api/runtime/azure-inventory-ready',
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json() == {'configured': False}


def test_foundry_readiness_with_connection(client):
    _connection()

    response = client.get(
        '/api/runtime/azure-inventory-ready',
        headers={'X-GAME-Ingest-Token': TOKEN},
    )
    assert response.status_code == 200
    assert response.json() == {'configured': True}


def test_collector_skips_sync_without_foundry(monkeypatch, capsys):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {'configured': False}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, headers):
            calls.append(('GET', url))
            return Response()

        def post(self, url, **kwargs):
            pytest.fail("Azure sync must not run without Foundry")

    monkeypatch.setenv(
        'GAME_RUNTIME_INGEST_TOKEN',
        TOKEN,
    )
    monkeypatch.setattr(collector.httpx, 'Client', FakeClient)

    args = SimpleNamespace(
        mapping=None,
        game_url='http://127.0.0.1:8000',
    )

    assert collector.collect(args) == 0
    assert len(calls) == 1
    assert calls[0][1].endswith(
        '/api/runtime/azure-inventory-ready'
    )
    assert 'synchronization skipped' in capsys.readouterr().out
