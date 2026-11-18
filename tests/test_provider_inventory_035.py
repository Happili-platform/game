# SPDX-License-Identifier: AGPL-3.0-only
import pytest
from fastapi.testclient import TestClient
from game import provider_integrations as pi
from game.main import app
from game.db import connection


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv('GAME_DB_PATH',str(tmp_path/'provider.db'))
    monkeypatch.setenv('GAME_TESTING','true')
    with TestClient(app) as api:
        yield api


def test_github_readonly_flow(client,monkeypatch):
    created=client.post('/api/connections',json={'provider':'github_inventory','label':'GitHub sample',
        'scope':{'organization':'Happili-platform'},'env_prefix':'AC_GITHUB'}).json()
    assert created['provider']=='github_inventory'
    cid=created['id']
    assert client.post(f'/api/connections/{cid}/test').status_code==502 # no credentials
    monkeypatch.setattr(pi,'_collect',lambda row: ([('repository','123','testorg/repo',{'visibility':'private'}),
        ('app_installation','77','readonly',{'permissions':{'metadata':'read'}})],[]))
    probe=client.post(f'/api/connections/{cid}/test')
    assert probe.status_code==200,probe.text
    assert probe.json()['inventory_counts']=={'repository':1,'app_installation':1}
    assert client.get('/api/provider-inventory').json()==[]
    first=client.post(f'/api/connections/{cid}/discover')
    assert first.status_code==200,first.text
    assert first.json()['discovered']==2
    assert len(client.get('/api/provider-inventory').json())==2
    assert client.get('/api/trust-graph').json()['links']==[]
    assert client.post(f'/api/connections/{cid}/discover').status_code==200
    assert len(client.get('/api/provider-inventory').json())==2


def test_atlassian_only_advertised_tools(client,monkeypatch):
    created=client.post('/api/connections',json={'provider':'atlassian_rovo_mcp','label':'Rovo sample',
        'scope':{'endpoint':'https://mcp.atlassian.com/v2/mcp'},'env_prefix':'AC_ATLASSIAN'}).json()
    assert created['provider']=='atlassian_rovo_mcp'
    cid=created['id']
    monkeypatch.setattr(pi,'_collect',lambda row: ([('mcp_tool','search','search',{'catalog':'advertised_primary_only'})],
        [{'external_id':'search','name':'search','description':'Search','capability':'mcp_advertised'}]))
    assert client.post(f'/api/connections/{cid}/discover').status_code==200
    data=client.get('/api/trust-graph').json()
    assert len(data['tools'])==1
    assert data['tools'][0]['capability']=='mcp_advertised'
    assert data['links']==[]
    assert len(client.get('/api/provider-inventory').json())==1


def test_inventory_scope_validation():
    from game.connectors import validate_scope
    with pytest.raises(ValueError):validate_scope('atlassian_rovo_mcp',{'endpoint':'http://localhost:1234/private'})
    with pytest.raises(ValueError):validate_scope('github_inventory',{'organization':'foo/bar'})
