# SPDX-License-Identifier: AGPL-3.0-only
"""Read-only, evidence-backed agent/tool relationship inventory.

The API does not contact external MCP endpoints and never executes tools.
An ingest is an authenticated provider snapshot, not evidence of execution.
"""
from __future__ import annotations

import json
from uuid import uuid4
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ConfigDict
from .auth import require, permits_resource, require_resource
from .db import connection, utc_now, iso

router = APIRouter(prefix='/api/trust-graph', tags=['trust-graph'])


class ToolSnapshot(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    external_id: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=500)
    capability: str = Field(default='unknown', max_length=100)


class ToolIngest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    connection_id: str
    namespace: str = Field(min_length=1, max_length=200)
    tools: list[ToolSnapshot] = Field(max_length=500)


class LinkIngest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    agent_id: str
    tool_id: str
    evidence_type: str = Field(pattern='^(declared_configuration|observed_invocation)$')
    evidence_reference: str = Field(min_length=1, max_length=500)


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS trust_tools (
      id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, connection_id TEXT NOT NULL,
      namespace TEXT NOT NULL, external_id TEXT NOT NULL, name TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '', capability TEXT NOT NULL DEFAULT 'unknown',
      first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
      UNIQUE(tenant_id, connection_id, namespace, external_id));
    CREATE INDEX IF NOT EXISTS idx_trust_tools_tenant ON trust_tools(tenant_id, connection_id);
    CREATE TABLE IF NOT EXISTS trust_links (
      id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, agent_id TEXT NOT NULL,
      tool_id TEXT NOT NULL, evidence_type TEXT NOT NULL CHECK(evidence_type IN
         ('declared_configuration','observed_invocation')),
      evidence_reference TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
      UNIQUE(tenant_id, agent_id, tool_id, evidence_type, evidence_reference));
    CREATE INDEX IF NOT EXISTS idx_trust_links_tenant ON trust_links(tenant_id, agent_id);
    ''')


def _audit(db, actor, operation, resource_id, count):
    db.execute('''INSERT INTO audit_events (id, tenant_id, actor, operation, resource_id, occurred_at, details_json)
       VALUES (?,?,?,?,?,?,?)''', ('aud-'+uuid4().hex[:16], actor.tenant_id, actor.subject,
       operation, resource_id, iso(utc_now()), json.dumps({'count':count})))


@router.post('/tools/snapshot')
def ingest_snapshot(body: ToolIngest, request: Request):
    actor = require(request, 'connections.discover')
    require_resource(actor, connection_id=body.connection_id)
    if len({x.external_id for x in body.tools}) != len(body.tools):
        raise HTTPException(422, 'Duplicate tool external IDs in snapshot')
    with connection() as db:
        c = db.execute('SELECT 1 FROM provider_connections WHERE id=? AND tenant_id=?',
                       (body.connection_id, actor.tenant_id)).fetchone()
        if not c:
            raise HTTPException(404, 'Provider connection not found')
        now = iso(utc_now())
        for t in body.tools:
            row = db.execute('''SELECT id FROM trust_tools WHERE tenant_id=? AND connection_id=? AND namespace=? AND external_id=?''',
                             (actor.tenant_id, body.connection_id, body.namespace, t.external_id)).fetchone()
            if row:
                db.execute('''UPDATE trust_tools SET name=?,description=?,capability=?,last_seen=? WHERE id=?''',
                           (t.name,t.description,t.capability,now,row['id']))
            else:
                db.execute('''INSERT INTO trust_tools VALUES (?,?,?,?,?,?,?,?,?,?)''',
                           ('tool-'+uuid4().hex[:16],actor.tenant_id,body.connection_id,body.namespace,
                            t.external_id,t.name,t.description,t.capability,now,now))
        _audit(db, actor, 'trust_graph.tools.snapshot', body.connection_id, len(body.tools))
    return {'accepted':len(body.tools), 'mode':'upsert_only', 'execution_evidence':False}


@router.post('/links', status_code=201)
def ingest_link(body: LinkIngest, request: Request):
    actor = require(request, 'connections.discover')
    with connection() as db:
        agent = db.execute('SELECT connection_id FROM agents WHERE tenant_id=? AND id=?',
                           (actor.tenant_id,body.agent_id)).fetchone()
        if agent is None:
            agent = db.execute('SELECT connection_id FROM discovered_agents WHERE tenant_id=? AND id=?',
                               (actor.tenant_id,body.agent_id)).fetchone()
        tool = db.execute('SELECT connection_id FROM trust_tools WHERE tenant_id=? AND id=?',
                          (actor.tenant_id,body.tool_id)).fetchone()
        if not agent or not tool:
            raise HTTPException(404,'Agent or tool not found')
        if not (permits_resource(actor, agent['connection_id'], body.agent_id) and
                permits_resource(actor, tool['connection_id'])):
            raise HTTPException(404,'Agent or tool not found')
        now=iso(utc_now())
        existing=db.execute('''SELECT id FROM trust_links WHERE tenant_id=? AND agent_id=? AND tool_id=?
           AND evidence_type=? AND evidence_reference=?''',
           (actor.tenant_id, body.agent_id,body.tool_id,body.evidence_type,body.evidence_reference)).fetchone()
        if existing:
            db.execute('UPDATE trust_links SET last_seen=? WHERE id=?',(now,existing['id']))
            link_id=existing['id']
        else:
            link_id='link-'+uuid4().hex[:16]
            db.execute('INSERT INTO trust_links VALUES (?,?,?,?,?,?,?,?)',
                       (link_id,actor.tenant_id,body.agent_id,body.tool_id,body.evidence_type,body.evidence_reference,now,now))
        _audit(db,actor,'trust_graph.link.record',body.agent_id,1)
    return {'id':link_id,'evidence_type':body.evidence_type,'executed':body.evidence_type=='observed_invocation'}


@router.get('')
def graph(request: Request):
    actor=require(request,'agents.view')
    with connection() as db:
        tools=[dict(r) for r in db.execute('SELECT * FROM trust_tools WHERE tenant_id=? ORDER BY name',
                                            (actor.tenant_id,)) if permits_resource(actor,r['connection_id'])]
        allowed={t['id'] for t in tools}
        agents={r['id']:r['connection_id'] for table in ('agents','discovered_agents') for r in
                db.execute(f'SELECT id,connection_id FROM {table} WHERE tenant_id=?',(actor.tenant_id,))
                if permits_resource(actor,r['connection_id'],r['id'])}
        links=[dict(r) for r in db.execute('SELECT * FROM trust_links WHERE tenant_id=?',
                                            (actor.tenant_id,)) if r['tool_id'] in allowed and r['agent_id'] in agents]
        return {'tools':tools,'links':links, 'semantics':{'tools':'declared provider capabilities, not actual access',
                'declared_configuration':'configured relationship, not proof of invocation',
                'observed_invocation':'reported tool execution; verify evidence reference at source'}}
