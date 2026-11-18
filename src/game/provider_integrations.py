# SPDX-License-Identifier: AGPL-3.0-only
"""Read-only GitHub App and Atlassian Rovo MCP capability inventories.

No agent relationships are inferred from provider resources or tool listings.
All remote requests are constrained to fixed API hosts. No MCP tools/call requests.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request

from . import vault
from .auth import require, permits_resource, require_resource
from .db import connection, iso, utc_now

router = APIRouter(prefix='/api/provider-inventory', tags=['provider-inventory'])
PROVIDERS = {'github_inventory', 'atlassian_rovo_mcp'}


class InventoryError(Exception):
    pass


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS provider_inventory (
      id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, connection_id TEXT NOT NULL,
      kind TEXT NOT NULL, external_id TEXT NOT NULL, name TEXT NOT NULL,
      details_json TEXT NOT NULL DEFAULT '{}', first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
      UNIQUE(tenant_id, connection_id, kind, external_id)
    );
    CREATE INDEX IF NOT EXISTS idx_provider_inventory_tenant ON provider_inventory(tenant_id,connection_id);
    ''')


def _github(connection_scope, creds):
    org = connection_scope['organization']
    try:
        now = int(time.time())
        signed = jwt.encode({'iat': now-60, 'exp': now+540, 'iss': str(creds['app_id'])},
                            creds['private_key_pem'], algorithm='RS256')
        headers = {'Authorization': f'Bearer {signed}', 'Accept':'application/vnd.github+json',
                   'X-GitHub-Api-Version':'2026-03-10'}
        with httpx.Client(base_url='https://api.github.com',timeout=20,follow_redirects=False,trust_env=False) as http:
            install=http.get(f'/orgs/{org}/installation', headers=headers)
            install.raise_for_status()
            installation=install.json()
            if installation.get('account',{}).get('login','').lower()!=org.lower():
                raise InventoryError('GitHub App installation is not owned by the specified organization')
            install_id=installation['id']
            response=http.post(f'/app/installations/{install_id}/access_tokens',headers=headers,json={})
            response.raise_for_status()
            token=response.json()['token']
            api_headers={'Authorization':f'Bearer {token}','Accept':'application/vnd.github+json',
                         'X-GitHub-Api-Version':'2026-03-10'}
            resources=[]
            def pages(path, key, kind):
                for page in range(1,101):
                    result=http.get(path,headers=api_headers,params={'per_page':100,'page':page})
                    result.raise_for_status()
                    payload=result.json(); items=payload.get(key,[])
                    if not isinstance(items,list):raise InventoryError('GitHub API returned an invalid inventory')
                    for x in items:
                        if kind=='repository':
                            resources.append((kind,str(x['id']),str(x['full_name']),
                                  {'visibility':x.get('visibility','unknown'),'archived':bool(x.get('archived',False))}))
                        else:
                            resources.append((kind,str(x['id']),str(x.get('app_slug') or x.get('id')),
                                  {'permissions':x.get('permissions') or {},'repository_selection':x.get('repository_selection')}))
                    if len(items)<100:return
                raise InventoryError('GitHub pagination safety limit reached')
            pages('/installation/repositories','repositories','repository')
            pages(f'/orgs/{org}/installations','installations','app_installation')
            return resources, []
    except (httpx.HTTPError, KeyError, ValueError, jwt.PyJWTError) as exc:
        raise InventoryError('GitHub authentication or inventory query failed; verify App ID, installation, permissions and organization') from exc


def _atlassian(connection_scope, creds):
    # Only catalog metadata. Never call tools/call or send business inputs.
    endpoint=connection_scope['endpoint']
    headers={'Authorization':f"Bearer {creds['api_key']}", 'Accept':'application/json, text/event-stream',
             'Content-Type':'application/json', 'MCP-Protocol-Version':'2025-06-18'}
    def parse(resp):
        resp.raise_for_status()
        if 'text/event-stream' in resp.headers.get('content-type',''):
            for line in resp.text.splitlines():
                if line.startswith('data: '):
                    try:
                        data=json.loads(line[6:])
                        if isinstance(data,dict) and ('result' in data or 'error' in data):return data
                    except ValueError:continue
            raise InventoryError('MCP stream did not contain a JSON-RPC response')
        return resp.json()
    try:
        with httpx.Client(timeout=25,follow_redirects=False,trust_env=False) as http:
            initial_response=http.post(endpoint,headers=headers,json={'jsonrpc':'2.0','id':1,'method':'initialize',
                'params':{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'GAME','version':'0.3.5'}}})
            initial=parse(initial_response)
            if 'error' in initial or not isinstance(initial.get('result'),dict):
                raise InventoryError('Atlassian MCP initialization was rejected')
            more=headers.copy()
            session_id=initial_response.headers.get('mcp-session-id')
            if session_id:more['Mcp-Session-Id']=session_id
            http.post(endpoint, headers=more, json={'jsonrpc':'2.0','method':'notifications/initialized'}).raise_for_status()
            result=parse(http.post(endpoint,headers=more,json={'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}}))
            if 'error' in result:raise InventoryError('Atlassian MCP tools/list request was rejected')
            payload=result.get('result') or {}
            tools=payload.get('tools',[])
            if not isinstance(tools,list):raise InventoryError('MCP tool catalog is malformed')
            if payload.get('nextCursor'):raise InventoryError('MCP catalog requires pagination; this snapshot was not saved')
            if len(tools)>500:raise InventoryError('MCP catalog exceeds safety limit')
            resources=[]; capabilities=[]
            for tool in tools:
                if not isinstance(tool,dict) or not isinstance(tool.get('name'),str):
                    raise InventoryError('MCP returned invalid tool descriptor')
                name=tool['name']; desc=str(tool.get('description') or '')[:500]
                resources.append(('mcp_tool',name,name,{'description':desc,'catalog':'advertised_primary_only'}))
                capabilities.append({'external_id':name,'name':name,'description':desc,'capability':'mcp_advertised'})
            return resources,capabilities
    except (httpx.HTTPError,ValueError,KeyError) as exc:
        raise InventoryError('Atlassian Rovo MCP inventory failed; check admin API-key enablement, scopes and network') from exc


def _collect(row):
    with connection() as db:
        saved=db.execute('SELECT encrypted_json FROM provider_credentials WHERE connection_id=? AND tenant_id=?',
                         (row['id'],row['tenant_id'])).fetchone()
    if not saved:raise InventoryError('Save encrypted provider credentials before testing')
    try:credentials=vault.decrypt(row['id'],row['provider'],saved['encrypted_json'])
    except vault.VaultError as exc:raise InventoryError('Credential vault unavailable; restore encryption key') from exc
    scope=json.loads(row['scope_json'])
    if row['provider']=='github_inventory':return _github(scope,credentials)
    if row['provider']=='atlassian_rovo_mcp':return _atlassian(scope,credentials)
    raise InventoryError('Unsupported provider inventory type')


def run(request,actor,row,sync=False):
    require_resource(actor,row['id'])
    if row['provider'] not in PROVIDERS:raise HTTPException(409,'Not an inventory provider')
    # Scoped credentials must never be decrypted for a non-local network request in legacy mode.
    from .main import _require_local_credentials_request
    _require_local_credentials_request(request)
    try:
        resources, capabilities=_collect(row)
        if len(resources)>10000:raise InventoryError('Inventory safety limit exceeded')
    except InventoryError as exc:
        with connection() as db:
            db.execute('UPDATE provider_connections SET last_error=? WHERE id=? AND tenant_id=?',
                       (str(exc),row['id'],actor.tenant_id))
        raise HTTPException(502,str(exc)) from None
    except Exception:
        raise HTTPException(502,'Provider integration failed; check server logs and provider permissions') from None
    counts={}
    for kind, *_ in resources:counts[kind]=counts.get(kind,0)+1
    if not sync:return {'connected':True,'inventory_counts':counts,'discovered':len(resources),
                        'notice':'Read-only connectivity test. No inventory saved.'}
    now=iso(utc_now())
    with connection() as db:
        for kind,external_id,name,details in resources:
            db.execute('''INSERT INTO provider_inventory (id,tenant_id,connection_id,kind,external_id,name,details_json,first_seen,last_seen)
            VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(tenant_id,connection_id,kind,external_id)
            DO UPDATE SET name=excluded.name,details_json=excluded.details_json,last_seen=excluded.last_seen''',
            ('item-'+uuid4().hex[:16],actor.tenant_id,row['id'],kind,external_id,name,json.dumps(details),now,now))
        for tool in capabilities:
            db.execute('''INSERT INTO trust_tools (id,tenant_id,connection_id,namespace,external_id,name,description,capability,first_seen,last_seen)
               VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(tenant_id,connection_id,namespace,external_id)
               DO UPDATE SET name=excluded.name,description=excluded.description,capability=excluded.capability,last_seen=excluded.last_seen''',
               ('tool-'+uuid4().hex[:16],actor.tenant_id,row['id'],'atlassian-rovo',tool['external_id'],tool['name'],tool['description'],tool['capability'],now,now))
        db.execute('UPDATE provider_connections SET last_synced_at=?,last_error=NULL WHERE id=? AND tenant_id=?',(now,row['id'],actor.tenant_id))
        db.execute('INSERT INTO audit_events (id,tenant_id,actor,operation,resource_id,occurred_at,details_json) VALUES (?,?,?,?,?,?,?)',
            ('aud-'+uuid4().hex[:16],actor.tenant_id,actor.subject,'provider.inventory.sync',row['id'],now,json.dumps({'counts':counts})))
    return {'connection_id':row['id'],'discovered':len(resources),'inventory_counts':counts,'synced_at':now,
            'notice':'Provider resources and advertised MCP tools only; no agent access or tool invocation inferred.'}


@router.get('')
def list_inventory(request:Request):
    actor=require(request,'agents.view')
    with connection() as db:
        rows=[dict(r) for r in db.execute('SELECT * FROM provider_inventory WHERE tenant_id=? ORDER BY kind,name',
                                          (actor.tenant_id,)) if permits_resource(actor,r['connection_id'])]
    for r in rows:r['details']=json.loads(r.pop('details_json'))
    return rows
