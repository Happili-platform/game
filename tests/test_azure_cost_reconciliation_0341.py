# SPDX-License-Identifier: AGPL-3.0-only
"""Cost Management actual-cost import must stay separate from per-agent attribution."""
from pathlib import Path
import importlib.util
from fastapi.testclient import TestClient
import pytest
from game.main import app
from game.db import initialize

TOKEN='collector-azure-cost-reconciliation-123456789'
SCOPE='/subscriptions/00102aad-d274-4d8f-9eb1-564fdd0d3f9e/resourceGroups/test-ai'
RESOURCE=SCOPE+'/providers/Microsoft.CognitiveServices/accounts/game-ai'

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('GAME_DB_PATH',str(tmp_path/'game.db'))
    monkeypatch.setenv('GAME_VAULT_KEY_PATH',str(tmp_path/'vault.key'))
    monkeypatch.setenv('GAME_RUNTIME_INGEST_TOKEN',TOKEN)
    with TestClient(app) as c: yield c

def payload(amount='12.25',currency='USD'):
    return {'scope':SCOPE,'rows':[{'resource_id':RESOURCE,'usage_day':'2026-11-09',
                                    'currency':currency,'amount':amount}]}

def test_import_idempotent_scope_not_agent_billed(client):
    assert client.post('/api/finops/azure-costs/ingest',json=payload()).status_code==401
    h={'X-GAME-Ingest-Token':TOKEN}
    result=client.post('/api/finops/azure-costs/ingest',json=payload(),headers=h)
    assert result.status_code==201,result.text
    assert result.json()['invoice_verified'] is False
    assert result.json()['agent_attribution']=='not_available'
    for _ in range(2):
        assert client.post('/api/finops/azure-costs/ingest',json=payload('14.50'),headers=h).status_code==201
    costs=client.get('/api/finops/azure-costs?period=all').json()
    assert costs['records']==1
    assert costs['totals_by_currency']=={'USD':'14.50'}
    assert costs['rows'][0]['resource_id']==RESOURCE.lower()
    assert costs['invoice_verified'] is False
    assert costs['agent_attribution']=='Not available'
    summary=client.get('/api/finops/summary?period=all').json()
    assert summary['billed_usd'] is None
    assert summary['estimated_usd'] is None
    initialize()
    assert client.get('/api/finops/azure-costs?period=all').json()['records']==1

def test_currency_separation_and_invalid_inputs(client):
    h={'X-GAME-Ingest-Token':TOKEN}
    assert client.post('/api/finops/azure-costs/ingest',json=payload('2.0','EUR'),headers=h).status_code==201
    assert client.post('/api/finops/azure-costs/ingest',json=payload('5.0','USD'),headers=h).status_code==201
    assert client.get('/api/finops/azure-costs?period=all').json()['totals_by_currency']=={'EUR':'2.0','USD':'5.0'}
    for bad in ('NaN','Infinity','1e99999'):
        assert client.post('/api/finops/azure-costs/ingest',json=payload(bad),headers=h).status_code==422
    wrong=payload();wrong['scope']='/providers/Other'
    assert client.post('/api/finops/azure-costs/ingest',json=wrong,headers=h).status_code==422
    wrong=payload();wrong['rows'][0]['usage_day']='2026-02-31'
    assert client.post('/api/finops/azure-costs/ingest',json=wrong,headers=h).status_code==422
    wrong=payload();wrong['rows'][0]['prompt']='secret'
    assert client.post('/api/finops/azure-costs/ingest',json=wrong,headers=h).status_code==422

def test_azure_response_column_names_and_no_guess():
    path=Path(__file__).resolve().parents[1]/'scripts'/'collect_azure_costs.py'
    spec=importlib.util.spec_from_file_location('azure_cost_collector',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    props={'columns':[{'name':n} for n in ('ResourceId','Currency','PreTaxCost','UsageDate')],
        'rows':[[RESOURCE,'USD',1.125,20261109]]}
    result=module.parse_cost_response({'properties':props})
    assert result[0]['amount']=='1.125'
    assert result[0]['usage_day']=='2026-11-09'
    assert result[0]['resource_id']==RESOURCE.lower()
    with pytest.raises(ValueError,match='missing'):
        module.parse_cost_response({'properties':{'columns':[{'name':'PreTaxCost'}],'rows':[]}})
    props['nextLink']='https://example.com/more'
    with pytest.raises(ValueError,match='paginated'):
        module.parse_cost_response({'properties':props})


def test_azure_cost_unassigned_and_extended_resource_names(client):
    """Azure returns empty ResourceId for some charges and valid ARM IDs with ':' and '~'."""
    h={'X-GAME-Ingest-Token':TOKEN}
    batch={'scope':SCOPE,'rows':[
        {'resource_id':'','usage_day':'2026-11-09','currency':'USD','amount':'0.50'},
        {'resource_id':RESOURCE+'/deployments/gpt-4o:2026~test','usage_day':'2026-11-09',
         'currency':'USD','amount':'0.75'}]}
    response=client.post('/api/finops/azure-costs/ingest',json=batch,headers=h)
    assert response.status_code==201,response.text
    result=client.get('/api/finops/azure-costs?period=all').json()
    assert result['totals_by_currency']=={'USD':'1.25'}
    assert result['records']==2
    assert any(r['resource_id']=='' for r in result['rows'])
    assert client.post('/api/finops/azure-costs/ingest',json=batch,headers=h).status_code==201
    assert client.get('/api/finops/azure-costs?period=all').json()['records']==2
    batch['rows'][1]['resource_id']='/subscriptions/test\nsecret'
    assert client.post('/api/finops/azure-costs/ingest',json=batch,headers=h).status_code==422


def test_azure_collector_keeps_empty_resource_id():
    path=Path(__file__).resolve().parents[1]/'scripts'/'collect_azure_costs.py'
    spec=importlib.util.spec_from_file_location('azure_cost_collector',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data={'properties':{'columns':[{'name':n} for n in
          ('ResourceId','Currency','PreTaxCost','UsageDate')],
          'rows':[['','USD',0.125,20261109],[None,'USD',0.125,20261110]]}}
    rows=module.parse_cost_response(data)
    assert [r['resource_id'] for r in rows]==['','']


def test_azure_cost_non_arm_billing_identifiers(client):
    """Cost Management ResourceId is a billing dimension, not always an ARM ID."""
    h={'X-GAME-Ingest-Token':TOKEN}
    batch={'scope':SCOPE,'rows':[
        {'resource_id':'Unassigned','usage_day':'2026-11-09','currency':'USD','amount':'0.50'},
        {'resource_id':'Marketplace:Third Party Meter','usage_day':'2026-11-09','currency':'USD','amount':'0.75'},
        {'resource_id':'','usage_day':'2026-11-09','currency':'USD','amount':'0.25'},
    ]}
    response=client.post('/api/finops/azure-costs/ingest',json=batch,headers=h)
    assert response.status_code==201,response.text
    assert response.json()['agent_attribution']=='not_available'
    assert client.post('/api/finops/azure-costs/ingest',json=batch,headers=h).status_code==201
    result=client.get('/api/finops/azure-costs?period=all').json()
    assert result['records']==3
    assert result['totals_by_currency']=={'USD':'1.50'}
    assert {r['resource_id'] for r in result['rows']}=={'unassigned','marketplace:third party meter',''}
    batch['rows'][0]['resource_id']='Unassigned\nunsafe'
    assert client.post('/api/finops/azure-costs/ingest',json=batch,headers=h).status_code==422
    batch['rows'][0]['resource_id']='X'*451
    assert client.post('/api/finops/azure-costs/ingest',json=batch,headers=h).status_code==422
