# SPDX-License-Identifier: AGPL-3.0-only
"""v0.3.4.0 metadata-only evidence and cost separation tests."""
from datetime import datetime, timezone
from fastapi.testclient import TestClient
import pytest
from game.main import app
from game.db import connection, initialize
import importlib.util
from pathlib import Path

TOKEN='collector-authenticated-token-for-finops-123456789'
TRACE='b'*32
START='2026-11-09T14:00:00Z'

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('GAME_DB_PATH',str(tmp_path/'test.db'))
    monkeypatch.setenv('GAME_VAULT_KEY_PATH',str(tmp_path/'vault.key'))
    monkeypatch.setenv('GAME_RUNTIME_INGEST_TOKEN',TOKEN)
    with TestClient(app) as c: yield c

def create_run(client):
    agent=client.post('/api/agents',json={'name':'Actual Foundry agent','provider':'Azure'}).json()
    run={'agent_id':agent['id'],'source':'azure_foundry_logs','external_run_id':TRACE,'trace_id':TRACE,
         'status':'unknown','started_at':START,'spans':[]}
    assert client.post('/api/runtime/ingest',headers={'X-GAME-Ingest-Token':TOKEN},json=run).status_code==201
    return agent

def evidence(agent_id):
    return {'agent_id':agent_id,'source':'azure_foundry_logs','external_run_id':TRACE,
            'operation_id':'f'*16,'occurred_at':START,'model_id':'gpt-test-version',
            'input_tokens':100,'output_tokens':30,'evidence':'azure_appinsights_genai_attributes'}

def test_usage_ingestion_dedupe_and_unknown_cost(client):
    a=create_run(client)
    response=client.post('/api/finops/usage/ingest',json=evidence(a['id']),headers={'X-GAME-Ingest-Token':TOKEN})
    assert response.status_code==201,response.text
    assert not response.json()['replayed']
    replay=client.post('/api/finops/usage/ingest',json=evidence(a['id']),headers={'X-GAME-Ingest-Token':TOKEN})
    assert replay.status_code==201 and replay.json()['replayed']
    summary=client.get('/api/finops/summary?period=all').json()
    assert summary['usage_operations']==1 and summary['input_tokens_observed']==100
    assert summary['estimated_usd'] is None and summary['billed_usd'] is None
    assert summary['billed_status']=='Not tracked'
    assert summary['by_agent'][0]['estimated_usd'] is None
    initialize()
    assert client.get('/api/finops/summary?period=all').json()['usage_operations']==1

def test_rates_only_admin_and_explicit_estimates(client):
    a=create_run(client)
    h={'X-GAME-Ingest-Token':TOKEN}
    assert client.post('/api/finops/usage/ingest',json=evidence(a['id']),headers=h).status_code==201
    rate={'provider':'azure_foundry_logs','model_id':'gpt-test-version','input_usd_per_million':'2.00',
          'output_usd_per_million':'8.00','valid_from':'2026-01-01T00:00:00Z',
          'source_url':'https://example.org/documented-prices'}
    result=client.post('/api/finops/rates',json=rate)
    assert result.status_code==201,result.text
    assert client.post('/api/finops/rates',json=rate).status_code==409
    cost=client.get('/api/finops/summary?period=all').json()
    assert cost['estimated_usd']=='0.000440'
    assert cost['billed_usd'] is None
    assert cost['estimated_operations']==1

def test_conflicting_replay_orphan_and_strict_fields(client):
    a=create_run(client)
    h={'X-GAME-Ingest-Token':TOKEN}
    p=evidence(a['id']);p['external_run_id']='other'
    assert client.post('/api/finops/usage/ingest',json=p,headers=h).status_code==404
    p=evidence(a['id'])
    assert client.post('/api/finops/usage/ingest',json=p).status_code==401
    assert client.post('/api/finops/usage/ingest',json=p,headers=h).status_code==201
    p['input_tokens']=101
    assert client.post('/api/finops/usage/ingest',json=p,headers=h).status_code==409
    p=evidence(a['id']);p['prompt']='secret'
    assert client.post('/api/finops/usage/ingest',json=p,headers=h).status_code==422

def test_azure_extraction_only_model_spans_and_metadata():
    path=Path(__file__).resolve().parents[1]/'scripts/collect_azure_foundry.py'
    spec=importlib.util.spec_from_file_location('collector_finops',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    payload={'trace_id':TRACE,'agent_id':'agent-one','source':'azure_foundry_logs','external_run_id':TRACE}
    root={'OperationId':TRACE,'_table':'AppRequests','Id':'c'*16,'TimeGenerated':START,
          'Properties':{'gen_ai.usage.input_tokens':300,'gen_ai.agent.id':'foundry'}}
    model={'OperationId':TRACE,'_table':'AppDependencies','Id':'d'*16,'TimeGenerated':START,
          'Properties':{'gen_ai.usage.input_tokens':'100','gen_ai.usage.output_tokens':30,
                        'gen_ai.response.model':'model-a','gen_ai.input.messages':'secret'}}
    usage=module.usage_from_traces([root,model],[payload])
    assert len(usage)==1 and usage[0]['input_tokens']==100
    assert 'secret' not in str(usage)
    assert module.usage_from_traces([root],[payload])==[]
