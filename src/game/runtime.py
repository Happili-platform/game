# SPDX-License-Identifier: AGPL-3.0-only
"""v0.3.3 runtime evidence API: collector-authenticated writes, user-scoped reads.

This is deliberately a normalized JSON contract, NOT an OTLP endpoint. A provider
adapter/OTel collector must map its telemetry to this contract. Unknown values
remain NULL; no prompt, model response, attributes or tool payloads are accepted.
"""
from __future__ import annotations

import json
import hmac
import os
import re
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import rbac
from .auth import LOCAL_TENANT, require, permits_resource
from .db import connection, iso, utc_now

router = APIRouter(prefix='/api/runtime', tags=['runtime'])
_SAFE_ID = re.compile(r'^[a-zA-Z0-9._:/@-]{1,160}$')
_TRACE_ID = re.compile(r'^[0-9a-fA-F]{32}$')
_SPAN_ID = re.compile(r'^[0-9a-fA-F]{16}$')


def _ts(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError('Timestamps require an explicit timezone')
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _duration(start: datetime, end: datetime | None) -> float | None:
    if end is None:
        return None
    n = (end-start).total_seconds()*1000
    if n < 0:
        raise ValueError('End precedes start')
    return round(n, 3)


class CollectionStatus(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    source: str = Field(pattern=r'^[a-zA-Z0-9._-]{2,80}$')
    window_start: datetime
    window_end: datetime
    metadata_rows: int = Field(ge=0, le=1000000)
    trace_groups: int = Field(ge=0, le=1000000)
    eligible: int = Field(ge=0, le=1000000)
    imported: int = Field(ge=0, le=1000000)
    replayed: int = Field(ge=0, le=1000000)
    failed: int = Field(ge=0, le=1000000)

    @model_validator(mode='after')
    def validate_window(self):
        _ts(self.window_start)
        _ts(self.window_end)
        if self.window_end < self.window_start:
            raise ValueError('Collection end precedes start')
        if self.failed:
            raise ValueError('Failed collection must not be marked successful')
        return self


class RuntimeSpan(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    span_id: str = Field(pattern=r'^[0-9a-fA-F]{16}$')
    parent_span_id: str | None = Field(default=None, pattern=r'^[0-9a-fA-F]{16}$')
    trace_id: str = Field(pattern=r'^[0-9a-fA-F]{32}$')
    kind: str = Field(pattern=r'^(agent|model|tool|mcp|other)$')
    name: str = Field(min_length=1, max_length=160)
    status: str = Field(default='unknown', pattern=r'^(success|failure|unknown)$')
    started_at: datetime
    ended_at: datetime | None = None

    @model_validator(mode='after')
    def validate_time(self):
        _ts(self.started_at)
        if self.ended_at: _ts(self.ended_at)
        _duration(self.started_at, self.ended_at)
        if self.parent_span_id == self.span_id:
            raise ValueError('Span cannot parent itself')
        return self


class RuntimeRun(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    agent_id: str = Field(min_length=1, max_length=160)
    source: str = Field(min_length=2, max_length=80, pattern=r'^[a-zA-Z0-9._-]+$')
    external_run_id: str = Field(min_length=1, max_length=160)
    trace_id: str | None = Field(default=None, pattern=r'^[0-9a-fA-F]{32}$')
    status: str = Field(default='unknown', pattern=r'^(success|failure|unknown)$')
    started_at: datetime
    ended_at: datetime | None = None
    spans: list[RuntimeSpan] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def validate_run(self):
        if not _SAFE_ID.fullmatch(self.external_run_id):
            raise ValueError('Invalid external run identifier')
        _ts(self.started_at)
        if self.ended_at: _ts(self.ended_at)
        _duration(self.started_at, self.ended_at)
        if len({s.span_id for s in self.spans}) != len(self.spans):
            raise ValueError('Duplicate span IDs in one request')
        if len({s.trace_id.lower() for s in self.spans}) > 1:
            raise ValueError('All spans in a run must have the same trace ID')
        if self.trace_id and any(s.trace_id.lower() != self.trace_id.lower() for s in self.spans):
            raise ValueError('Span trace ID differs from run')
        return self


def _collector(request: Request):
    # v0.3.3 local prototype deliberately does not expose collector ingestion
    # over the network, even if a reverse proxy is accidentally configured.
    client = request.client.host if request.client else ''
    if client not in ('127.0.0.1','::1','testclient'):
        raise HTTPException(403, 'Runtime ingestion is localhost-only in v0.3.3')
    if request.headers.get('content-length'):
        try:
            if int(request.headers['content-length']) > 131072:
                raise HTTPException(413, 'Runtime payload too large')
        except ValueError:
            raise HTTPException(400, 'Invalid Content-Length') from None
    configured = os.getenv('GAME_RUNTIME_INGEST_TOKEN', '')
    if len(configured) < 32:
        raise HTTPException(503, 'Runtime collector credential not configured (minimum 32 characters)')
    provided = request.headers.get('X-GAME-Ingest-Token', '')
    if not hmac.compare_digest(provided.encode(), configured.encode()):
        raise HTTPException(401, 'Invalid runtime collector credential')
    # This first release has a single-company collector. Multi-tenant trust
    # bindings are explicitly deferred; never accept tenant IDs in payload.
    return LOCAL_TENANT


def _visible_agent(db, actor, agent_id):
    row = db.execute('SELECT connection_id FROM agents WHERE tenant_id=? AND id=?',
                     (actor.tenant_id, agent_id)).fetchone()
    if not row:
        row = db.execute('SELECT connection_id FROM discovered_agents WHERE tenant_id=? AND id=?',
                         (actor.tenant_id, agent_id)).fetchone()
    if row is None or not permits_resource(actor, row['connection_id'], agent_id):
        return False
    if rbac.normalized_role(actor.role)=='business_owner':
        return db.execute('SELECT 1 FROM agent_governance WHERE tenant_id=? AND agent_id=? AND business_owner_user_id=?',
                          (actor.tenant_id,agent_id,actor.subject.removeprefix('local-user:'))).fetchone() is not None
    return True


@router.post('/ingest', status_code=201)
async def ingest_run(payload: RuntimeRun, request: Request):
    tenant_id = _collector(request)
    now = iso(utc_now())
    run_id = 'run-' + uuid4().hex
    with connection() as db:
        exists = db.execute('SELECT 1 FROM agents WHERE id=? AND tenant_id=? UNION ALL SELECT 1 FROM discovered_agents WHERE id=? AND tenant_id=?',
                            (payload.agent_id, tenant_id, payload.agent_id, tenant_id)).fetchone()
        if not exists:
            raise HTTPException(404, 'Agent not found; discover/register it before collecting telemetry')
        prior = db.execute('SELECT * FROM runtime_runs WHERE tenant_id=? AND source=? AND agent_id=? AND external_run_id=?',
                           (tenant_id, payload.source, payload.agent_id, payload.external_run_id)).fetchone()
        if prior:
            run_id = prior['id']
            # Same source run can be replayed to add missing spans, but its
            # immutable identity/start/trace cannot be silently overwritten.
            if prior['started_at'] != _ts(payload.started_at) or (prior['trace_id'] and payload.trace_id and prior['trace_id'].lower()!=payload.trace_id.lower()):
                raise HTTPException(409, 'Conflicting replay for existing run identity')
            db.execute('''UPDATE runtime_runs SET
                         trace_id=COALESCE(trace_id,?),
                         status=CASE WHEN ?='unknown' THEN status ELSE ? END,
                         ended_at=COALESCE(?,ended_at),
                         duration_ms=COALESCE(?,duration_ms),last_ingested_at=? WHERE id=?''',
                       (payload.trace_id,payload.status,payload.status,
                        _ts(payload.ended_at) if payload.ended_at else None,
                        _duration(payload.started_at,payload.ended_at),now,run_id))
        else:
            db.execute('''INSERT INTO runtime_runs
              (id,tenant_id,agent_id,source,external_run_id,trace_id,status,started_at,ended_at,duration_ms,first_ingested_at,last_ingested_at)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
              (run_id,tenant_id,payload.agent_id,payload.source,payload.external_run_id,
               payload.trace_id.lower() if payload.trace_id else None,payload.status,
               _ts(payload.started_at),_ts(payload.ended_at) if payload.ended_at else None,
               _duration(payload.started_at,payload.ended_at),now,now))
        for span in payload.spans:
            existing = db.execute('SELECT * FROM runtime_spans WHERE run_id=? AND span_id=?', (run_id,span.span_id.lower())).fetchone()
            if existing:
                if existing['trace_id'].lower()!=span.trace_id.lower() or existing['started_at']!=_ts(span.started_at) or existing['kind'] != span.kind or existing['name'] != span.name:
                    raise HTTPException(409, 'Conflicting replay for existing span')
                db.execute('''UPDATE runtime_spans SET
                   status=CASE WHEN ?='unknown' THEN status ELSE ? END,
                   ended_at=COALESCE(?,ended_at),duration_ms=COALESCE(?,duration_ms)
                   WHERE id=?''',
                   (span.status,span.status,_ts(span.ended_at) if span.ended_at else None,
                    _duration(span.started_at,span.ended_at),existing['id']))
            else:
                db.execute('''INSERT INTO runtime_spans
                  (id,run_id,tenant_id,span_id,parent_span_id,trace_id,kind,name,status,started_at,ended_at,duration_ms)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                  ('spn-'+uuid4().hex,run_id,tenant_id,span.span_id.lower(),
                   span.parent_span_id.lower() if span.parent_span_id else None,
                   span.trace_id.lower(),span.kind,span.name,span.status,
                   _ts(span.started_at),_ts(span.ended_at) if span.ended_at else None,
                   _duration(span.started_at,span.ended_at)))
        if not prior:
            # Record the metadata ingestion event, never the collector token.
            db.execute('''INSERT INTO audit_events
                      (id,tenant_id,actor,operation,resource_id,occurred_at,details_json)
                      VALUES (?,?,?,?,?,?,?)''',
                      ('aud-'+uuid4().hex[:16],tenant_id,'runtime-collector',
                       'runtime.run.ingest',run_id,now,
                       json.dumps({'agent_id':payload.agent_id,'source':payload.source,'span_count':len(payload.spans)})))
    return {'id':run_id,'accepted_spans':len(payload.spans),'replayed':bool(prior),'source':payload.source}


@router.post('/collection-status', status_code=201)
async def record_collection_status(payload: CollectionStatus, request: Request):
    tenant = _collector(request)
    with connection() as db:
        db.execute('''INSERT INTO runtime_collection_status
            (tenant_id,source,last_success_at,window_start,window_end,
             metadata_rows,trace_groups,eligible,imported,replayed,failed)
             VALUES (?,?,?,?,?,?,?,?,?,?,?)
             ON CONFLICT(tenant_id,source) DO UPDATE SET
             last_success_at=excluded.last_success_at,
             window_start=excluded.window_start,window_end=excluded.window_end,
             metadata_rows=excluded.metadata_rows,trace_groups=excluded.trace_groups,
             eligible=excluded.eligible,imported=excluded.imported,
             replayed=excluded.replayed,failed=excluded.failed''',
            (tenant,payload.source,iso(utc_now()),_ts(payload.window_start),_ts(payload.window_end),
             payload.metadata_rows,payload.trace_groups,payload.eligible,
             payload.imported,payload.replayed,payload.failed))
    return {'recorded': True}


def _period_start(period: str):
    if period == 'all':
        return None
    return _ts(datetime.now(timezone.utc)-timedelta(hours={'24h':24,'7d':168,'30d':720}[period]))


@router.get('/runs')
def runs(request: Request, agent_id: str | None = None, period: str = Query('all',pattern=r'^(24h|7d|30d|all)$'), limit: int = Query(50,ge=1,le=200)):
    actor = require(request,'runtime.view')
    with connection() as db:
        since = _period_start(period)
        records = db.execute('''SELECT * FROM runtime_runs
            WHERE tenant_id=? AND (? IS NULL OR agent_id=?)
              AND (? IS NULL OR started_at>=?)
            ORDER BY started_at DESC LIMIT 5000''',
            (actor.tenant_id,agent_id,agent_id,since,since)).fetchall()
        rows = [dict(row) for row in records if _visible_agent(db,actor,row['agent_id'])][:limit]
    return rows


@router.get('/runs/{run_id}')
def run_details(run_id: str, request: Request):
    actor = require(request,'runtime.view')
    with connection() as db:
        row=db.execute('SELECT * FROM runtime_runs WHERE tenant_id=? AND id=?', (actor.tenant_id,run_id)).fetchone()
        if not row or not _visible_agent(db,actor,row['agent_id']):
            raise HTTPException(404,'Run not found')
        spans=db.execute('SELECT * FROM runtime_spans WHERE tenant_id=? AND run_id=? ORDER BY started_at,span_id', (actor.tenant_id,run_id)).fetchall()
    return {**dict(row),'spans':[dict(s) for s in spans]}


@router.get('/summary')
def summary(request: Request, agent_id: str | None = None, period: str = Query('all',pattern=r'^(24h|7d|30d|all)$')):
    actor=require(request,'runtime.view')
    with connection() as db:
        rows = [dict(r) for r in db.execute(
            'SELECT agent_id,status,duration_ms,started_at,last_ingested_at FROM runtime_runs WHERE tenant_id=? AND (? IS NULL OR agent_id=?)',
            (actor.tenant_id,agent_id,agent_id)) if _visible_agent(db,actor,r['agent_id'])]
        since = _period_start(period)
        selected = [r for r in rows if since is None or r['started_at'] >= since]
        durations = sorted(r['duration_ms'] for r in selected if r['duration_ms'] is not None)
        known = [r for r in selected if r['status'] in ('success','failure')]
        failures = sum(r['status']=='failure' for r in known)
        p95 = durations[max(0, (95*len(durations)+99)//100-1)] if durations else None
        # Bucket by actual UTC date, not synthetic interpolations.
        daily = {}
        for r in selected:
            day = r['started_at'][:10]
            bucket = daily.setdefault(day, {'date': day,'runs':0,'failures':0,
                                             'known_outcomes':0,'duration_samples':0,'duration_total_ms':0})
            bucket['runs'] += 1
            if r['status'] in ('success','failure'):
                bucket['known_outcomes'] += 1
            if r['status']=='failure':
                bucket['failures'] += 1
            if r['duration_ms'] is not None:
                bucket['duration_samples'] += 1
                bucket['duration_total_ms'] += r['duration_ms']
        trend = [{'date':b['date'], 'runs':b['runs'],'failures':b['failures'],
                  'avg_duration_ms':round(b['duration_total_ms']/b['duration_samples'],1)
                  if b['duration_samples'] else None} for b in sorted(daily.values(),key=lambda x:x['date'])]
        # A collection is company-wide; visibility into collection health is
        # metadata-only, without disclosing agent identities or traces.
        collections = [dict(r) for r in db.execute('SELECT source,last_success_at,window_start,window_end,metadata_rows,trace_groups,eligible,imported,replayed FROM runtime_collection_status WHERE tenant_id=? ORDER BY last_success_at DESC',
            (actor.tenant_id,))]
        return {'runs':len(selected),'historical_runs':len(rows),
                'known_outcomes':len(known),'unknown_outcomes':len(selected)-len(known),
                'failures':failures,
                'success_rate':round((len(known)-failures)/len(known)*100,2) if known else None,
                'p95_duration_ms':p95,'duration_samples':len(durations),
                'last_ingested_at':max((r['last_ingested_at'] for r in rows),default=None),
                'last_successful_collection_at':collections[0]['last_success_at'] if collections else None,
                'collections':collections,'daily_trend':trend,
                'period':period,'coverage':'recorded_runs_only','cost_status':'Not tracked'}


@router.get('/popularity')
def popularity(request: Request,
               agent_id: str | None = None,
               period: str = Query('all', pattern=r'^(24h|7d|30d|all)$'),
               top_n: int = Query(5, ge=1, le=20),
               search: str = Query('', max_length=120)):
    # Server-side grouped counts; search does not alter the scope-wide total.
    actor = require(request, 'runtime.view')
    since = _period_start(period)
    with connection() as db:
        counts = db.execute('''SELECT agent_id, COUNT(*) AS runs
          FROM runtime_runs
          WHERE tenant_id=? AND (? IS NULL OR agent_id=?)
            AND (? IS NULL OR started_at>=?)
          GROUP BY agent_id''', (actor.tenant_id, agent_id, agent_id, since, since)).fetchall()
        visible = {r['agent_id']: r['runs'] for r in counts if _visible_agent(db, actor, r['agent_id'])}
        names = {}
        for table in ('agents', 'discovered_agents'):
            for row in db.execute(f'SELECT id,name FROM {table} WHERE tenant_id=?', (actor.tenant_id,)):
                if row['id'] in visible:
                    names[row['id']] = row['name']
        ranked = sorted(({'agent_id': aid, 'name': names.get(aid, aid), 'runs': n}
                         for aid, n in visible.items()), key=lambda a: (-a['runs'], a['name'].casefold(), a['agent_id']))
        total = sum(visible.values())
        matching = [r for r in ranked if search.casefold() in r['name'].casefold() or search.casefold() in r['agent_id'].casefold()]
        top = matching[:top_n]
        # 'Others' applies to the currently selected ranking scope; no silently missing runs.
        other_runs = sum(r['runs'] for r in matching[top_n:])
        selected_ids = {r['agent_id'] for r in top}
        all_day_counts = db.execute('''SELECT substr(started_at,1,10) AS day, agent_id, COUNT(*) AS runs
            FROM runtime_runs
            WHERE tenant_id=? AND (? IS NULL OR agent_id=?)
              AND (? IS NULL OR started_at>=?)
            GROUP BY substr(started_at,1,10), agent_id
            ORDER BY day DESC''', (actor.tenant_id, agent_id, agent_id, since, since)).fetchall()
        # Cap only the number of plotted active days, never the ranking or historical totals.
        days = sorted({r['day'] for r in all_day_counts if r['agent_id'] in visible}, reverse=True)
        chart_days = set(days[:60])
        day_buckets = {}
        matching_ids = {r['agent_id'] for r in matching}
        for row in all_day_counts:
            aid = row['agent_id']
            if row['day'] not in chart_days or aid not in matching_ids:
                continue
            bucket = day_buckets.setdefault(row['day'], {'date': row['day'], 'total': 0, 'by_agent': {}, 'others': 0})
            n = row['runs']
            bucket['total'] += n
            if aid in selected_ids:
                bucket['by_agent'][aid] = n
            else:
                bucket['others'] += n
    return {
      'period': period, 'top_n': top_n, 'search': search, 'runs': sum(r['runs'] for r in matching),
      'scope_total_runs': total, 'active_agents': len(matching),
      'ranking': [{**r, 'share_pct': round(r['runs'] / sum(a['runs'] for a in matching)*100, 1)
                   if matching else 0} for r in top],
      'others_runs': other_runs, 'others_agents': max(0, len(matching)-len(top)),
      'daily': [day_buckets[d] for d in sorted(day_buckets)],
      'chart_days_truncated': len(days) > 60,
      'coverage': 'recorded_runs_only',
    }
