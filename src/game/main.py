# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant-aware GAME prototype API; OIDC bearer auth or loopback local mode."""
from __future__ import annotations

import sqlite3
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .core import enrich_agent
from .policy_engine import rule_configs, RULES_BY_CODE
from .version import __version__
from . import connectors, vault, local_accounts
from .auth import require, require_resource, permits_resource, LOCAL_TENANT, current_principal
from . import rbac
from .db import connection, initialize, iso, utc_now
from .runtime import router as runtime_router
from .finops import router as finops_router
from .trust_graph import router as trust_graph_router
from . import provider_integrations


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize()
    yield


app = FastAPI(
    title="GAME API", version=__version__, lifespan=lifespan,
    description="Tenant-scoped agent inventory; OIDC bearer API mode or loopback-only developer mode.",
)


app.include_router(runtime_router)
app.include_router(finops_router)
app.include_router(trust_graph_router)
app.include_router(provider_integrations.router)


class AgentCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=100)
    provider: str = Field(min_length=2, max_length=100)
    connection_id: str | None = None
    description: str = Field(default="", max_length=500)
    owner_email: str | None = Field(default=None, max_length=254)
    environment: Literal["development", "staging", "production"] = "development"
    approval_status: Literal["approved", "pending", "unapproved"] = "pending"  # legacy field; never permits business approval
    lifecycle_status: Literal["active", "paused", "retired"] = "active"
    cost_center: str = Field(default="", max_length=80)
    budget_usd: float = Field(default=0, ge=0, le=1e9)
    sensitive_access: bool = False


class UsageCreate(BaseModel):
    agent_id: str
    cost_usd: float = Field(ge=0, le=1e9)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    outcome: Literal["success", "failure", "unknown"] = "unknown"


def _agents_from_db(db: sqlite3.Connection, tenant_id: str, actor=None) -> list[dict]:
    month = utc_now().strftime("%Y-%m")
    policy_rules = rule_configs([dict(row) for row in db.execute(
        'SELECT * FROM policy_rules WHERE tenant_id=?', (tenant_id,))])
    rows = db.execute("""SELECT a.*, COALESCE(s.monthly_cost, 0) AS monthly_cost
          FROM agents a LEFT JOIN (
            SELECT agent_id, SUM(cost_usd) AS monthly_cost
            FROM usage_events WHERE substr(occurred_at,1,7) = ? AND tenant_id = ? GROUP BY agent_id
          ) s ON a.id = s.agent_id WHERE a.tenant_id = ? ORDER BY a.name COLLATE NOCASE""", (month, tenant_id, tenant_id)).fetchall()
    local = [{**{k: row[k] for k in row.keys() if k != 'monthly_cost'}, 'monthly_spend_usd': row['monthly_cost']} for row in rows]
    discovered = db.execute("SELECT * FROM discovered_agents WHERE tenant_id=? ORDER BY name COLLATE NOCASE", (tenant_id,)).fetchall()
    for row in discovered:
        item = dict(row)
        item["monthly_cost"] = 0.0
        # Discovery timestamps are NOT activity evidence, and do not imply production status.
        local.append(item)
    # GAME governance is authoritative. Preserve provider-reported status
    # separately: an imported 'approved' field is never proof of budget approval.
    approvals = {r['agent_id']: dict(r) for r in db.execute(
        """SELECT g.*,u.username AS business_owner_username,u.display_name AS business_owner_display_name,u.active AS business_owner_active
            FROM agent_governance g LEFT JOIN local_users u ON u.id=g.business_owner_user_id
            WHERE g.tenant_id=?""", (tenant_id,)).fetchall()}
    affected_map = {}
    for row in db.execute('''SELECT agent_id,cve_id FROM agent_vulnerability_links
                         WHERE tenant_id=? AND assessment='affected' ''', (tenant_id,)):
        affected_map.setdefault(row['agent_id'], []).append(row['cve_id'])
    for a in local:
        a['confirmed_affected_cves'] = affected_map.get(a['id'], [])
        g = approvals.get(a['id'], {})
        a['provider_approval_status'] = a.get('approval_status', 'unknown')
        a['approval_status'] = g.get('approval_status', 'not_reviewed')
        a['business_owner_user_id'] = g.get('business_owner_user_id')
        a['business_owner_name'] = g.get('business_owner_display_name') or g.get('business_owner_username')
        a['business_owner_active'] = bool(g.get('business_owner_active')) if g.get('business_owner_user_id') else None
        a['approval_submitted_by'] = g.get('submitted_by')
        a['approval_submitted_at'] = g.get('submitted_at')
        a['approval_decided_by'] = g.get('decided_by')
        a['approval_decided_at'] = g.get('decided_at')
        a['approval_reason'] = g.get('decision_reason', '')
        a['approval_justification'] = g.get('justification', '')
        a['approval_requested_cost_center'] = g.get('requested_cost_center', '')
        a['approval_requested_budget_usd'] = g.get('requested_budget_usd') if g else None
        a['approved_budget_usd'] = g.get('requested_budget_usd') if a['approval_status']=='approved' else None
        enriched = enrich_agent(a, float(a.get('monthly_spend_usd') or 0), rules=policy_rules)
        a.update(enriched)
    if actor is not None:
        local = [a for a in local if permits_resource(actor, a.get('connection_id'), a['id'])]
        grants = actor.capabilities if actor.capabilities is not None else rbac.effective_capabilities(actor.role)
        if 'finops.estimates.view' not in grants:
            for a in local:
                a['monthly_spend_usd'] = None
                a['spend_observed'] = False
                a['approved_budget_usd'] = None
                a['approval_requested_budget_usd'] = None
                a['budget_usd'] = None
                a['cost_center'] = ''
                a['approval_requested_cost_center'] = ''
    return sorted(local, key=lambda a: a["name"].casefold())


@app.get("/api/health")
def health():
    return {"status": "ok", "prototype": True, "version": app.version}


@app.get("/api/agents")
def list_agents(request: Request):
    actor = require(request, 'agents.view')
    with connection() as db:
        return _agents_from_db(db, actor.tenant_id, actor)


@app.get("/api/agents/{agent_id}")
def get_agent(agent_id: str, request: Request):
    actor = require(request, 'agents.view')
    with connection() as db:
        agent = next((a for a in _agents_from_db(db, actor.tenant_id, actor) if a["id"] == agent_id), None)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        rows = db.execute("""SELECT * FROM usage_events WHERE agent_id=?
                AND tenant_id=? ORDER BY occurred_at DESC LIMIT 30""", (agent_id, actor.tenant_id)).fetchall() if agent.get("source") != "discovered" else []
        return {**agent, "recent_usage": [dict(row) for row in rows]}


@app.post("/api/agents", status_code=201)
def create_agent(payload: AgentCreate, request: Request):
    actor = require(request, 'agents.register')
    if payload.approval_status == 'approved':
        raise HTTPException(422, 'Business Owner approval must use the separate approval workflow')
    if payload.connection_id:
        require_resource(actor, connection_id=payload.connection_id)
        with connection() as db:
            target = db.execute('SELECT provider FROM provider_connections WHERE id=? AND tenant_id=?',
                                (payload.connection_id, actor.tenant_id)).fetchone()
        if not target:
            raise HTTPException(404, 'Connection not found')
        if payload.provider != target['provider']:
            raise HTTPException(422, 'Agent provider must match the selected connection')
    elif not permits_resource(actor):
        raise HTTPException(403, 'Assign a permitted provider connection to register an agent')
    agent_id = f"agt-{uuid4().hex[:12]}"
    with connection() as db:
        db.execute("""INSERT INTO agents (
          id,name,provider,description,owner_email,environment,approval_status,
          lifecycle_status,cost_center,budget_usd,sensitive_access,last_seen,source,created_at,tenant_id,connection_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
          agent_id, payload.name, payload.provider, payload.description,
          payload.owner_email or None, payload.environment, 'pending',
          payload.lifecycle_status, payload.cost_center, payload.budget_usd,
          int(payload.sensitive_access), None, "manual", iso(utc_now()), actor.tenant_id, payload.connection_id
        ))
        _audit(db, actor, 'agent.create', agent_id)
        return next(a for a in _agents_from_db(db, actor.tenant_id, actor) if a["id"] == agent_id)


@app.post("/api/usage", status_code=201)
def record_usage(payload: UsageCreate, request: Request):
    actor = require(request, 'usage.record')
    with connection() as db:
        if not db.execute("SELECT 1 FROM agents WHERE id=? AND tenant_id=?", (payload.agent_id, actor.tenant_id)).fetchone():
            if db.execute("SELECT 1 FROM discovered_agents WHERE id=? AND tenant_id=?", (payload.agent_id, actor.tenant_id)).fetchone():
                raise HTTPException(status_code=409, detail="Provider-discovered records are inventory-only until cost telemetry integration")
            raise HTTPException(status_code=404, detail="Agent not found")
        row = db.execute('SELECT connection_id FROM agents WHERE id=? AND tenant_id=?', (payload.agent_id, actor.tenant_id)).fetchone()
        require_resource(actor, row['connection_id'], payload.agent_id)
        usage_id = f"evt-{uuid4().hex[:16]}"
        happened = iso(utc_now())
        db.execute("""INSERT INTO usage_events (
          id,agent_id,occurred_at,cost_usd,input_tokens,output_tokens,outcome,source,tenant_id
        ) VALUES (?,?,?,?,?,?,?,?,?)""", (
          usage_id, payload.agent_id, happened, payload.cost_usd,
          payload.input_tokens, payload.output_tokens, payload.outcome, "manual", actor.tenant_id
        ))
        db.execute("UPDATE agents SET last_seen=? WHERE id=? AND tenant_id=?", (happened, payload.agent_id, actor.tenant_id))
        _audit(db, actor, 'usage.record', payload.agent_id)
    return {"id": usage_id, "recorded": True}


@app.get("/api/overview")
def overview(request: Request):
    actor = require(request, 'overview.view')
    with connection() as db:
        agents = _agents_from_db(db, actor.tenant_id, actor)
        monthly = round(sum(a["monthly_spend_usd"] or 0 for a in agents), 2)
        by_provider: dict[str, dict] = {}
        for a in agents:
            p = by_provider.setdefault(a["provider"], {"provider": a["provider"], "count": 0, "spend_usd": 0})
            p["count"] += 1
            p["spend_usd"] = round(p["spend_usd"] + (a["monthly_spend_usd"] or 0), 2)
        high = [a for a in agents if a["risk_level"] == "high"]
        flagged = [a for a in agents if a["risk_level"] != "clear"]
        return {
            "month": utc_now().strftime("%Y-%m"),
            "totals": {
                "agents": len(agents), "active": sum(a["lifecycle_status"] == "active" for a in agents),
                "missing_owners": sum(a["lifecycle_status"] != "retired" and not (a["business_owner_user_id"] or a["owner_email"]) for a in agents),
                "flagged_agents": len(flagged), "high_risk_agents": len(high),
                "monthly_spend_usd": monthly if 'finops.estimates.view' in (actor.capabilities if actor.capabilities is not None else rbac.effective_capabilities(actor.role)) else None,
            },
            "by_provider": sorted(by_provider.values(), key=lambda x: (-x["spend_usd"], x["provider"])) if 'finops.estimates.view' in (actor.capabilities if actor.capabilities is not None else rbac.effective_capabilities(actor.role)) else [{"provider":v["provider"],"count":v["count"],"spend_usd":None} for v in by_provider.values()],
            "attention": sorted(flagged, key=lambda a: (a["risk_level"] != "high", -len(a["findings"]), a["name"]))[:8],
            "data_notice": "Only manual/demo usage costs are included. Provider discovery does not retrieve billing or runtime telemetry.",
        }



# --- Optional vulnerability references, never an automatic vulnerability scanner. ---

class VulnerabilityReference(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    cve_id: str = Field(min_length=13, max_length=32)
    component_name: str = Field(min_length=2, max_length=150)
    component_version: str = Field(default='', max_length=100)
    assessment: Literal['under_review', 'affected', 'not_affected'] = 'under_review'
    evidence_source: str = Field(default='', max_length=500)


def _visible_agent_for_vulnerability(db, actor, agent_id: str):
    row = db.execute('SELECT connection_id FROM agents WHERE id=? AND tenant_id=?',
                     (agent_id, actor.tenant_id)).fetchone()
    if row is None:
        row = db.execute('SELECT connection_id FROM discovered_agents WHERE id=? AND tenant_id=?',
                         (agent_id, actor.tenant_id)).fetchone()
    if row is None:
        raise HTTPException(404, 'Agent not found')
    require_resource(actor, row['connection_id'], agent_id)
    return row


def _validate_vulnerability_link(payload: VulnerabilityReference) -> str:
    cve_id = payload.cve_id.upper()
    if not re.fullmatch(r'CVE-[0-9]{4}-[0-9]{4,}', cve_id):
        raise HTTPException(422, 'CVE ID must follow the published CVE identifier format')
    if payload.assessment == 'affected':
        if not payload.component_version or len(payload.evidence_source.strip()) < 10:
            raise HTTPException(422, 'Affected status requires an observed component version and evidence reference')
    return cve_id


@app.get('/api/agents/{agent_id}/vulnerabilities')
def list_vulnerability_references(agent_id: str, request: Request):
    actor = require(request, 'agents.view')
    with connection() as db:
        _visible_agent_for_vulnerability(db, actor, agent_id)
        records = [dict(row) for row in db.execute('''
            SELECT id,cve_id,component_name,component_version,assessment,evidence_source,assessed_by,
                   created_at,updated_at FROM agent_vulnerability_links
            WHERE tenant_id=? AND agent_id=? ORDER BY created_at DESC,id''',
            (actor.tenant_id, agent_id))]
    for r in records:
        r['nvd_url'] = 'https://nvd.nist.gov/vuln/detail/' + r['cve_id']
        r['cvss_status'] = 'not_enriched'  # Read the official source; no fabricated numeric score.
    return records


@app.post('/api/agents/{agent_id}/vulnerabilities', status_code=201)
def add_vulnerability_reference(agent_id: str, payload: VulnerabilityReference, request: Request):
    actor = require(request, 'governance.remediate')
    cve_id = _validate_vulnerability_link(payload)
    with connection() as db:
        _visible_agent_for_vulnerability(db, actor, agent_id)
        link_id = 'vln-' + uuid4().hex[:16]
        now = iso(utc_now())
        try:
            db.execute('''INSERT INTO agent_vulnerability_links
                (id,tenant_id,agent_id,cve_id,component_name,component_version,assessment,
                 evidence_source,assessed_by,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (link_id, actor.tenant_id, agent_id, cve_id, payload.component_name,
                 payload.component_version, payload.assessment, payload.evidence_source,
                 actor.subject, now, now))
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'This CVE and component reference already exists for this agent')
        _audit(db, actor, 'agent.vulnerability.reference.add', agent_id,
               {'cve_id': cve_id, 'assessment': payload.assessment,
                'component_name': payload.component_name, 'component_version': payload.component_version})
    return {'id':link_id, 'cve_id':cve_id, 'assessment':payload.assessment,
            'nvd_url':'https://nvd.nist.gov/vuln/detail/'+cve_id,
            'note':'CVE existence and component applicability are not independently verified. CVSS enrichment is not enabled.'}


@app.patch('/api/agents/{agent_id}/vulnerabilities/{link_id}')
def update_vulnerability_reference(agent_id: str, link_id: str,
                                   payload: VulnerabilityReference, request: Request):
    actor = require(request, 'governance.remediate')
    cve_id = _validate_vulnerability_link(payload)
    with connection() as db:
        _visible_agent_for_vulnerability(db, actor, agent_id)
        row = db.execute('SELECT id FROM agent_vulnerability_links WHERE tenant_id=? AND agent_id=? AND id=?',
                         (actor.tenant_id,agent_id,link_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Vulnerability reference not found')
        try:
            db.execute('''UPDATE agent_vulnerability_links SET cve_id=?,component_name=?,component_version=?,
              assessment=?,evidence_source=?,assessed_by=?,updated_at=?
              WHERE tenant_id=? AND agent_id=? AND id=?''',
              (cve_id,payload.component_name,payload.component_version,payload.assessment,
               payload.evidence_source,actor.subject,iso(utc_now()),actor.tenant_id,agent_id,link_id))
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Duplicate CVE and component reference')
        _audit(db, actor, 'agent.vulnerability.reference.update', agent_id,
               {'cve_id':cve_id,'assessment':payload.assessment})
    return {'updated':True,'id':link_id,'assessment':payload.assessment}


# --- Configurable, advisory-only policies and evidence-based evaluation snapshots. ---

class PolicyRuleUpdate(BaseModel):
    enabled: bool | None = None
    severity: Literal['high', 'medium', 'low'] | None = None
    stale_after_days: int | None = Field(default=None, ge=1, le=365)


def _policy_rules(db: sqlite3.Connection, tenant_id: str) -> list[dict]:
    return rule_configs([dict(row) for row in db.execute(
        'SELECT * FROM policy_rules WHERE tenant_id=?', (tenant_id,))])


@app.get('/api/policies')
def policy_catalog(request: Request):
    actor = require(request, 'governance.view')
    with connection() as db:
        rules = _policy_rules(db, actor.tenant_id)
        agents = _agents_from_db(db, actor.tenant_id, actor)
        counts = {r['code']: 0 for r in rules}
        for agent in agents:
            for finding in agent['findings']:
                counts[finding['code']] += 1
        last_run = db.execute('''SELECT id,evaluated_at,agents_evaluated,open_findings,resolved_findings
                      FROM policy_evaluation_runs WHERE tenant_id=? ORDER BY evaluated_at DESC,id DESC LIMIT 1''',
                      (actor.tenant_id,)).fetchone()
    return {'rules': [{**r, 'affected_agents': counts[r['code']]} for r in rules],
            'agents_visible': len(agents), 'last_recorded_evaluation': dict(last_run) if last_run else None,
            'can_manage': rbac.allowed(actor.role, 'governance.manage') and (actor.scope or {}).get('kind', 'all') == 'all',
            'can_remediate': rbac.allowed(actor.role, 'governance.remediate'),
            'can_evaluate': rbac.allowed(actor.role, 'governance.evaluate') and (actor.scope or {}).get('kind','all') == 'all',
            'notice': 'Live preview uses available inventory metadata. An empty finding list is not proof of compliance. '
                      'Cloud usage and activity telemetry are not collected by discovery.'}


@app.patch('/api/policies/{code}')
def configure_policy(code: str, payload: PolicyRuleUpdate, request: Request):
    actor = require(request, 'governance.manage')
    if (actor.scope or {}).get('kind', 'all') != 'all':
        raise HTTPException(403, 'Company-wide governance administration required')
    if code not in RULES_BY_CODE:
        raise HTTPException(404, 'Policy not found')
    changes = payload.model_dump(exclude_unset=True)
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(422, 'At least one non-null policy setting is required')
    if 'stale_after_days' in changes and code != 'STALE_AGENT':
        raise HTTPException(422, 'Inactivity threshold applies only to STALE_AGENT')
    with connection() as db:
        existing = db.execute('SELECT * FROM policy_rules WHERE tenant_id=? AND code=?',
                              (actor.tenant_id, code)).fetchone()
        if not existing:
            raise HTTPException(404, 'Policy not configured for this company')
        previous = dict(existing)
        effective = {name: value for name, value in changes.items() if previous[name] != value}
        if effective:
            assignments = ','.join(f'{column}=?' for column in effective)
            db.execute(f'''UPDATE policy_rules SET {assignments},version=version+1,updated_at=?,updated_by=?
                         WHERE tenant_id=? AND code=?''',
                       (*[int(v) if isinstance(v, bool) else v for v in effective.values()],
                        iso(utc_now()), actor.subject, actor.tenant_id, code))
            _audit(db, actor, 'policy.rule.update', code,
                   {'changed': {name: {'from': previous[name], 'to': value}
                                for name, value in effective.items()}})
        row = db.execute('SELECT * FROM policy_rules WHERE tenant_id=? AND code=?',
                         (actor.tenant_id, code)).fetchone()
    return next(r for r in rule_configs([dict(row)]) if r['code'] == code)


@app.post('/api/policies/evaluate')
def run_policy_evaluation(request: Request):
    actor = require(request, 'governance.evaluate')
    if (actor.scope or {}).get('kind', 'all') != 'all':
        raise HTTPException(403, 'Company-wide policy evaluation permission required')
    with connection() as db:
        agents = _agents_from_db(db, actor.tenant_id, actor)
        at = iso(utc_now())
        current = {}
        for agent in agents:
            for finding in agent['findings']:
                key = (agent['id'], finding['code'])
                current[key] = finding
                db.execute('''INSERT INTO policy_findings(tenant_id,agent_id,policy_code,status,severity,
                   message,evidence_json,first_seen_at,last_evaluated_at,resolved_at)
                   VALUES (?,?,?,?,?,?,?,?,?,NULL)
                   ON CONFLICT(tenant_id,agent_id,policy_code) DO UPDATE SET
                      status='open',severity=excluded.severity,message=excluded.message,
                      evidence_json=excluded.evidence_json,last_evaluated_at=excluded.last_evaluated_at,
                      resolved_at=NULL''',
                   (actor.tenant_id,agent['id'],finding['code'],'open',finding['severity'],
                    finding['message'],json.dumps(finding['evidence'],sort_keys=True),at,at))
        open_rows = db.execute('''SELECT agent_id,policy_code FROM policy_findings
                                WHERE tenant_id=? AND status='open' ''', (actor.tenant_id,)).fetchall()
        to_resolve = [(agent_id, code) for agent_id, code in open_rows if (agent_id, code) not in current]
        for agent_id, code in to_resolve:
            db.execute('''UPDATE policy_findings SET status='resolved',resolved_at=?,last_evaluated_at=?
                  WHERE tenant_id=? AND agent_id=? AND policy_code=?''',
                  (at,at,actor.tenant_id,agent_id,code))
        run_id = 'polrun-' + uuid4().hex[:16]
        db.execute('''INSERT INTO policy_evaluation_runs(id,tenant_id,actor,evaluated_at,
                   agents_evaluated,open_findings,resolved_findings) VALUES (?,?,?,?,?,?,?)''',
                   (run_id, actor.tenant_id,actor.subject,at,len(agents),len(current),len(to_resolve)))
        _audit(db,actor,'policy.evaluate',run_id,
               {'agents_evaluated':len(agents),'open_findings':len(current),'resolved_in_run':len(to_resolve)})
    return {'id':run_id,'evaluated_at':at,'agents_evaluated':len(agents),
            'open_findings':len(current),'resolved_in_run':len(to_resolve),
            'advisory_only':True}


@app.get('/api/policies/findings')
def policy_findings_history(request: Request, limit: int=Query(default=100,ge=1,le=500)):
    actor = require(request, 'governance.view')
    with connection() as db:
        visible_agents = {a['id'] for a in _agents_from_db(db,actor.tenant_id,actor)}
        rows = db.execute('''SELECT * FROM policy_findings WHERE tenant_id=?
                    ORDER BY last_evaluated_at DESC,agent_id,policy_code LIMIT ?''',
                    (actor.tenant_id,limit)).fetchall()
        return [{**dict(row),'evidence':json.loads(row['evidence_json'])}
                for row in rows if row['agent_id'] in visible_agents]


@app.get('/api/policies/runs')
def policy_evaluation_history(request: Request, limit: int=Query(default=20,ge=1,le=100)):
    actor = require(request, 'governance.view')
    if (actor.scope or {}).get('kind','all') != 'all':
        raise HTTPException(403, 'Company-wide governance access required')
    with connection() as db:
        return [dict(row) for row in db.execute('''SELECT * FROM policy_evaluation_runs
                        WHERE tenant_id=? ORDER BY evaluated_at DESC,id DESC LIMIT ?''',
                        (actor.tenant_id,limit)).fetchall()]


class PolicyRemediationUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    note: str = Field(min_length=10, max_length=1500)
    due_date: str | None = None  # YYYY-MM-DD, optional


@app.patch('/api/policies/findings/{agent_id}/{code}/remediation')
def document_policy_remediation(agent_id: str, code: str,
                                payload: PolicyRemediationUpdate, request: Request):
    actor = require(request, 'governance.remediate')
    if code not in RULES_BY_CODE:
        raise HTTPException(404, 'Policy not found')
    from datetime import date
    if payload.due_date is not None:
        try:
            parsed = date.fromisoformat(payload.due_date)
            if parsed.isoformat() != payload.due_date:
                raise ValueError('Date must be YYYY-MM-DD')
        except ValueError:
            raise HTTPException(422, 'Due date must be YYYY-MM-DD') from None
    with connection() as db:
        row = db.execute('''SELECT connection_id FROM agents WHERE id=? AND tenant_id=?
                            UNION ALL SELECT connection_id FROM discovered_agents
                            WHERE id=? AND tenant_id=? LIMIT 1''',
                         (agent_id,actor.tenant_id,agent_id,actor.tenant_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Agent not found')
        require_resource(actor,row['connection_id'],agent_id)
        existing = db.execute('''SELECT status FROM policy_findings WHERE tenant_id=? AND agent_id=? AND policy_code=?''',
                              (actor.tenant_id,agent_id,code)).fetchone()
        if not existing:
            raise HTTPException(404, 'No recorded finding to remediate; run an evaluation first')
        if existing['status'] != 'open':
            raise HTTPException(409, 'Resolved findings cannot be edited')
        now=iso(utc_now())
        db.execute('''UPDATE policy_findings SET remediation_note=?,remediation_due_date=?,
                 remediation_updated_by=?,remediation_updated_at=?
                 WHERE tenant_id=? AND agent_id=? AND policy_code=?''',
                 (payload.note,payload.due_date,actor.subject,now,actor.tenant_id,agent_id,code))
        _audit(db,actor,'policy.finding.remediation.update',agent_id,
               {'policy_code':code,'remediation_due_date':payload.due_date})
    return {'updated':True,'status':existing['status'],
            'note':'Remediation documented, but finding is not suppressed or considered resolved.'}




# --- Authenticated tenant metadata and audit trail. ---

def _audit(db: sqlite3.Connection, actor, operation: str, resource_id: str, details: dict | None = None) -> None:
    # Deliberately never record credentials, tokens, or request headers.
    db.execute('''INSERT INTO audit_events (id, tenant_id, actor, operation, resource_id, occurred_at, details_json)
            VALUES (?,?,?,?,?,?,?)''', ('aud-' + uuid4().hex[:16], actor.tenant_id, actor.subject,
                               operation, resource_id, iso(utc_now()), json.dumps(details or {})))


class CompanySettingsUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    company_name: str = Field(min_length=2, max_length=80)


def _validated_company_name(name: str) -> str:
    # Company labels are plain text, not HTML. Prevent controls/newlines as well.
    if re.search(r'[\x00-\x1f\x7f<>]', name):
        raise HTTPException(422, 'Company name must be plain text on one line')
    return name


def _company_name(db: sqlite3.Connection, tenant_id: str = LOCAL_TENANT) -> str:
    row = db.execute('SELECT name FROM tenants WHERE id=?', (tenant_id,)).fetchone()
    if not row or row['name'] == 'Legacy / Local Development':
        return 'Company'
    return row['name']


@app.get('/api/branding')
def public_branding():
    # Intentionally public, like the customer name displayed on the login page.
    # No company users, provider configuration, tokens or other data are returned.
    with connection() as db:
        name = _company_name(db)
    return {'company_name': name}


@app.get('/api/company/settings')
def company_settings(request: Request):
    actor = require(request, 'members.manage')
    if rbac.normalized_role(actor.role) != 'admin':
        raise HTTPException(403, 'Company Admin required')
    with connection() as db:
        return {'company_name': _company_name(db, actor.tenant_id)}


@app.patch('/api/company/settings')
def update_company_settings(payload: CompanySettingsUpdate, request: Request):
    actor = require(request, 'members.manage')
    if rbac.normalized_role(actor.role) != 'admin':
        raise HTTPException(403, 'Company Admin required')
    name = _validated_company_name(payload.company_name)
    with connection() as db:
        result = db.execute('UPDATE tenants SET name=? WHERE id=? AND active=1',
                            (name, actor.tenant_id))
        if result.rowcount != 1:
            raise HTTPException(404, 'Company workspace not found')
        _audit(db, actor, 'company.settings.update', actor.tenant_id)
    return {'company_name': name}


@app.get('/api/me')
def whoami(request: Request):
    actor = require(request)
    with connection() as db:
        row = db.execute('SELECT name FROM tenants WHERE id=?', (actor.tenant_id,)).fetchone()
    return {'tenant_id': actor.tenant_id, 'tenant_name': row['name'] if row else '',
            'role': actor.role, 'display_role': rbac.ROLES.get(rbac.normalized_role(actor.role), {}).get('label', actor.role),
            'capabilities': sorted(actor.capabilities if actor.capabilities is not None else rbac.effective_capabilities(actor.role)), 'scope': actor.scope or {'kind':'all'},
            'subject': actor.subject,
            'auth_mode': os.getenv('GAME_AUTH_MODE', 'password')}


class MemberRevoke(BaseModel):
    issuer: str = Field(min_length=8, max_length=300)
    subject: str = Field(min_length=1, max_length=300)


@app.post('/api/members/revoke')
def revoke_member(payload: MemberRevoke, request: Request):
    actor = require(request, 'tenant_admin')
    issuer = payload.issuer.rstrip('/')
    if os.getenv('GAME_AUTH_MODE') == 'oidc' and issuer == os.getenv('GAME_OIDC_ISSUER', '').rstrip('/') and payload.subject == actor.subject:
        raise HTTPException(409, 'Cannot revoke your own active tenant administration')
    with connection() as db:
        member = db.execute('SELECT role FROM tenant_memberships WHERE tenant_id=? AND issuer=? AND subject=? AND active=1',
                            (actor.tenant_id,issuer,payload.subject)).fetchone()
        if not member:
            raise HTTPException(404, 'Member not found')
        if rbac.normalized_role(member['role']) == 'admin':
            remaining = db.execute("SELECT COUNT(*) FROM tenant_memberships WHERE tenant_id=? AND role IN ('tenant_admin','admin') AND active=1",
                                   (actor.tenant_id,)).fetchone()[0]
            if remaining <= 1:
                raise HTTPException(409, 'Cannot remove the last tenant admin')
        db.execute('UPDATE tenant_memberships SET active=0 WHERE tenant_id=? AND issuer=? AND subject=?',
                   (actor.tenant_id,issuer,payload.subject))
        _audit(db, actor, 'member.revoke', payload.subject)
    return {'revoked': True}


@app.get('/api/audit')
def audit_log(request: Request, limit: int = Query(default=50, ge=1, le=200)):
    actor = require(request, 'audit.view')
    if not permits_resource(actor):
        raise HTTPException(403, 'Company-wide audit permission required')
    with connection() as db:
        rows = db.execute('SELECT * FROM audit_events WHERE tenant_id=? ORDER BY occurred_at DESC LIMIT ?',
                          (actor.tenant_id, limit)).fetchall()
    return [dict(row) for row in rows]


class MemberGrant(BaseModel):
    issuer: str = Field(min_length=8, max_length=300)
    subject: str = Field(min_length=1, max_length=300)
    role: Literal['viewer', 'agent_owner', 'provider_admin', 'business_owner', 'auditor', 'admin', 'analyst', 'connection_admin', 'tenant_admin']
    scope: dict | None = None


@app.get('/api/members')
def members(request: Request):
    actor = require(request, 'members.view')
    with connection() as db:
        rows = db.execute('SELECT issuer,subject,role,active,scope_json FROM tenant_memberships WHERE tenant_id=?',
                          (actor.tenant_id,)).fetchall()
    return [{**dict(row), 'scope': json.loads(row['scope_json'])} for row in rows]


@app.post('/api/members', status_code=201)
def grant_member(payload: MemberGrant, request: Request):
    actor = require(request, 'members.manage')
    # The membership is applied ONLY to the currently authenticated tenant.
    expected_issuer = os.getenv('GAME_OIDC_ISSUER', '').rstrip('/')
    if not payload.issuer.startswith('https://') or (expected_issuer and payload.issuer.rstrip('/') != expected_issuer):
        raise HTTPException(422, 'Issuer must match the configured OIDC issuer')
    # A selected resource scope is mandatory for scoped roles unless the admin deliberately grants company-wide.
    scope = payload.scope if payload.scope is not None else (
        {'kind': 'all'} if payload.role in ('admin', 'tenant_admin', 'auditor', 'analyst', 'connection_admin') else
        {'kind': 'selected', 'connection_ids': [], 'agent_ids': []})
    if scope.get('kind') not in ('all', 'selected') or set(scope) - {'kind', 'connection_ids', 'agent_ids'}:
        raise HTTPException(422, 'Invalid access scope')
    if rbac.normalized_role(payload.role) == 'business_owner' and scope['kind'] != 'selected':
        raise HTTPException(422, 'Business Owner requires selected resource scope')
    if rbac.normalized_role(payload.role) in ('admin', 'auditor') and scope['kind'] != 'all':
        raise HTTPException(422, 'Admin and Auditor require company-wide scope')
    if scope['kind'] == 'selected':
        if not isinstance(scope.get('connection_ids', []), list) or not isinstance(scope.get('agent_ids', []), list):
            raise HTTPException(422, 'Scope IDs must be lists')
        if len(scope.get('connection_ids', [])) > 1000 or len(scope.get('agent_ids', [])) > 1000:
            raise HTTPException(422, 'Too many scope IDs')
        with connection() as db:
            for cid in scope.get('connection_ids', []):
                if not isinstance(cid, str) or not db.execute('SELECT 1 FROM provider_connections WHERE id=? AND tenant_id=?', (cid, actor.tenant_id)).fetchone():
                    raise HTTPException(422, 'Scope contains a connection outside this company')
            for aid in scope.get('agent_ids', []):
                if not isinstance(aid, str) or not (db.execute('SELECT 1 FROM agents WHERE id=? AND tenant_id=?', (aid, actor.tenant_id)).fetchone() or db.execute('SELECT 1 FROM discovered_agents WHERE id=? AND tenant_id=?', (aid, actor.tenant_id)).fetchone()):
                    raise HTTPException(422, 'Scope contains an agent outside this company')
    with connection() as db:
        previous = db.execute('SELECT role FROM tenant_memberships WHERE tenant_id=? AND issuer=? AND subject=? AND active=1',
                              (actor.tenant_id, payload.issuer.rstrip('/'), payload.subject)).fetchone()
        if previous and rbac.normalized_role(previous['role']) == 'admin' and rbac.normalized_role(payload.role) != 'admin':
            if os.getenv('GAME_AUTH_MODE') == 'oidc' and payload.subject == actor.subject:
                raise HTTPException(409, 'Cannot demote your own active administration')
            count = db.execute("SELECT COUNT(*) FROM tenant_memberships WHERE tenant_id=? AND role IN ('tenant_admin','admin') AND active=1",
                               (actor.tenant_id,)).fetchone()[0]
            if count <= 1:
                raise HTTPException(409, 'Cannot demote the last company administrator')
        db.execute("""INSERT INTO tenant_memberships (tenant_id,issuer,subject,role,active,scope_json)
            VALUES (?,?,?,?,1,?) ON CONFLICT (tenant_id,issuer,subject)
            DO UPDATE SET role=excluded.role,active=1,scope_json=excluded.scope_json""",
            (actor.tenant_id, payload.issuer.rstrip('/'), payload.subject, payload.role, json.dumps(scope)))
        _audit(db, actor, 'member.grant', payload.subject)
    return {'granted': True}


@app.get('/api/rbac/catalog')
def role_catalog(request: Request):
    require(request)
    return rbac.catalog()


# --- Provider connections and encrypted local-development credential storage. ---
# Local development remains loopback-only; OIDC mode requires a verified access token.


def _require_local_credentials_request(request: Request) -> None:
    client_host = request.client.host if request.client else ''
    host = request.url.hostname or ''
    if not (client_host in {'127.0.0.1', '::1'} and host in {'127.0.0.1', 'localhost', '::1'}):
        if not (os.getenv('GAME_TESTING') == 'true'
                and client_host == 'testclient' and host == 'testserver'):
            raise HTTPException(403, 'Local credential operations require localhost access')
    origin = request.headers.get('origin')
    if origin:
        from urllib.parse import urlsplit
        parsed = urlsplit(origin)
        if parsed.scheme != request.url.scheme or parsed.netloc != request.headers.get('host'):
            raise HTTPException(403, 'Cross-origin credential submission is not allowed')


def _saved_row(db: sqlite3.Connection, connection_id: str, tenant_id: str):
    return db.execute('SELECT * FROM provider_credentials WHERE connection_id=? AND tenant_id=?',
                      (connection_id, tenant_id)).fetchone()


def _expires_at(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('Timezone required')
        return iso(stamp.astimezone(timezone.utc))
    except (ValueError, TypeError):
        raise ValueError('Credential expiration must be an ISO 8601 timestamp with timezone') from None


def _saved_status(row: sqlite3.Row) -> tuple[str, str, str | None]:
    """Return (source, status, expiration) without leaking credential values."""
    with connection() as db:
        record = _saved_row(db, row['id'], row['tenant_id'])
    if record is None:
        return '', '', None
    try:
        vault.decrypt(row['id'], row['provider'], record['encrypted_json'])
    except vault.VaultError:
        return 'vault_unavailable', 'unavailable', record['expires_at']
    expires_at = record['expires_at']
    if expires_at and datetime.fromisoformat(expires_at.replace('Z', '+00:00')) <= utc_now():
        return 'encrypted', 'expired', expires_at
    return 'encrypted', 'ready' if expires_at else 'expiration_unknown', expires_at


def _credential_details(row: sqlite3.Row) -> tuple[str, str, str | None]:
    if row['auth_mode'] != 'legacy':
        if row['auth_mode'] == 'push_oidc':
            return 'push_oidc', 'configured', None
        return 'workload_identity', 'configured', None
    source, status, expiry = _saved_status(row)
    if source:
        return source, status, expiry
    provider, prefix = row['provider'], row['env_prefix']
    if provider == 'microsoft_foundry':
        if all(os.getenv(f'{prefix}_AZURE_{k}') for k in ('TENANT_ID', 'CLIENT_ID', 'CLIENT_SECRET')):
            return 'environment', 'external', None
        if os.getenv(f'{prefix}_AZURE_USE_MANAGED_IDENTITY') == 'true':
            return 'managed_identity', 'external', None
        return 'not_configured', 'missing', None
    if provider in ('aws_agentcore', 'aws_bedrock_classic'):
        if os.getenv(f'{prefix}_AWS_PROFILE') or all(os.getenv(k) for k in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY')):
            return 'environment', 'external', None
        return 'external', 'unverified', None
    if provider == 'google_agent_engine':
        if os.getenv('GOOGLE_APPLICATION_CREDENTIALS'):
            return 'environment', 'external', None
        return 'external', 'unverified', None
    return 'external', 'unverified', None


def _credential_source(row: sqlite3.Row) -> str:
    return _credential_details(row)[0]


def _clear_saved_credentials(db: sqlite3.Connection, connection_id: str, tenant_id: str) -> None:
    db.execute('DELETE FROM provider_credentials WHERE connection_id=? AND tenant_id=?', (connection_id, tenant_id))


def _discover_with_connection(configured: dict) -> list[connectors.DiscoveredAgent]:
    connection_id = configured['id']
    provider = configured['provider']
    if configured['provider'] in ('github_inventory','atlassian_rovo_mcp'):
        raise connectors.DiscoveryError('Use the provider inventory workflow')
    if configured['provider'] == 'custom_registry':
        raise connectors.DiscoveryError('Private registries use authenticated push ingestion, not remote polling')
    if configured.get('auth_mode') != 'legacy':
        return connectors.discover(configured)
    if os.getenv('GAME_AUTH_MODE', 'local') == 'oidc':
        raise connectors.DiscoveryError('Legacy credential mode is disabled for multi-tenant API hosting')
    with connection() as db:
        stored = _saved_row(db, connection_id, configured['tenant_id'])
    if stored:
        if stored['expires_at'] and datetime.fromisoformat(stored['expires_at'].replace('Z', '+00:00')) <= utc_now():
            raise connectors.DiscoveryError('Saved temporary credentials have expired; update the connection credentials')
        try:
            values = vault.decrypt(connection_id, provider, stored['encrypted_json'])
        except vault.VaultError as exc:
            raise connectors.DiscoveryError(str(exc)) from None
        if provider == 'microsoft_foundry':
            return connectors.discover(configured, azure_credentials=values)
        if provider in ('aws_agentcore', 'aws_bedrock_classic'):
            # Prevent metadata (expiration) from being passed to boto3.
            return connectors.discover(configured, aws_credentials={k: values[k] for k in ('access_key_id', 'secret_access_key', 'session_token')})
        if provider == 'google_agent_engine':
            return connectors.discover(configured, google_credentials=values)
    return connectors.discover(configured)


class AzureSessionCredentials(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    tenant_id: str = Field(pattern=r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
    client_id: str = Field(pattern=r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
    client_secret: str = Field(min_length=1, max_length=4096)

class ConnectionCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    provider: Literal["microsoft_foundry", "google_agent_engine", "aws_agentcore", "aws_bedrock_classic", "custom_registry", "github_inventory", "atlassian_rovo_mcp"]
    label: str = Field(min_length=2, max_length=100)
    scope: dict[str, str]
    env_prefix: str = Field(min_length=2, max_length=40, pattern=r"^[A-Z][A-Z0-9_]*$")
    auth_mode: str = "legacy"
    auth_config: dict[str, str] = Field(default_factory=dict)


class ConnectionUpdate(BaseModel):
    # Immutable provider type: switch providers by creating a new connection.
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    label: str = Field(min_length=2, max_length=100)
    scope: dict[str, str]
    env_prefix: str = Field(min_length=2, max_length=40, pattern=r"^[A-Z][A-Z0-9_]*$")
    auth_mode: str = "legacy"
    auth_config: dict[str, str] = Field(default_factory=dict)
    clear_inventory_on_scope_change: bool = False


def _public_connection(row: sqlite3.Row) -> dict:
    details = _credential_details(row)
    return {
        "id": row["id"], "provider": row["provider"], "label": row["label"],
        "auth_mode": row["auth_mode"], "auth_config": json.loads(row["auth_config_json"]),
        "scope": json.loads(row["scope_json"]), "env_prefix": row["env_prefix"],
        "created_at": row["created_at"], "last_synced_at": row["last_synced_at"],
        "last_error": row["last_error"],
        "credential_source": details[0],
        "credential_status": details[1],
        "credential_expires_at": details[2], "tenant_id": row['tenant_id'],
    }


@app.get("/api/providers")
def providers_catalog(request: Request):
    require(request)
    return connectors.CATALOG


@app.get("/api/connections")
def list_connections(request: Request):
    actor = require(request, 'connections.view')
    with connection() as db:
        return [_public_connection(row) for row in db.execute("SELECT * FROM provider_connections WHERE tenant_id=? ORDER BY created_at DESC", (actor.tenant_id,))
                if permits_resource(actor, row['id'])]


@app.post("/api/connections", status_code=201)
def onboard_connection(payload: ConnectionCreate, request: Request):
    actor = require(request, 'connections.manage')
    if not permits_resource(actor):
        raise HTTPException(403, 'Only company-wide provider admins can create new connections')
    try:
        scope = connectors.validate_scope(payload.provider, payload.scope)
        mode, config = connectors.validate_auth_config(payload.provider, payload.auth_mode, payload.auth_config)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    id_ = "conn-" + uuid4().hex
    with connection() as db:
        db.execute("""INSERT INTO provider_connections
          (id, provider, label, scope_json, env_prefix, created_at, tenant_id, auth_mode, auth_config_json)
           VALUES (?,?,?,?,?,?,?,?,?)""", (id_, payload.provider, payload.label, json.dumps(scope), payload.env_prefix,
               iso(utc_now()), actor.tenant_id, mode, json.dumps(config)))
        row = db.execute("SELECT * FROM provider_connections WHERE id=? AND tenant_id=?", (id_, actor.tenant_id)).fetchone()
        _audit(db, actor, 'connection.create', id_)
    return _public_connection(row)


@app.put("/api/connections/{connection_id}/credentials")
async def set_session_credentials(connection_id: str, request: Request):
    actor = require(request, 'connections.credentials')
    require_resource(actor, connection_id)
    _require_local_credentials_request(request)
    # Validate without exposing secret values in error responses; encrypt before storing.
    with connection() as db:
        row = db.execute("SELECT provider, auth_mode FROM provider_connections WHERE id=? AND tenant_id=?", (connection_id, actor.tenant_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Provider connection not found")
    require_resource(actor, connection_id)
    provider = row["provider"]
    if row['auth_mode'] != 'legacy':
        raise HTTPException(409, 'Workload identity connection does not accept static credentials')
    try:
        raw = await request.body()
        if len(raw) > 25000:
            raise ValueError("Credential payload exceeds allowed size")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Credentials must be an object")
        if provider == "microsoft_foundry":
            values = AzureSessionCredentials.model_validate(data).model_dump()
            credentials = values
            expiry = None
        elif provider in ("aws_agentcore", "aws_bedrock_classic"):
            if not {"access_key_id", "secret_access_key", "session_token"}.issubset(data) or set(data) - {"access_key_id", "secret_access_key", "session_token", "expires_at"}:
                raise ValueError("AWS credentials require all three fields")
            credentials = {k: data[k] for k in ("access_key_id", "secret_access_key", "session_token")}
            if not all(isinstance(v, str) and v.strip() for v in credentials.values()):
                raise ValueError("AWS credentials must be nonempty")
            if any(len(v) > 8000 for v in credentials.values()):
                raise ValueError("AWS credentials exceed allowed length")
            expiry = _expires_at(data.get('expires_at'))
        elif provider == 'github_inventory':
            if set(data) != {'app_id', 'private_key_pem'} or not str(data.get('app_id', '')).isdigit():
                raise ValueError('GitHub App ID and PEM are required')
            pem = data['private_key_pem']
            pem_prefix = '-----' + 'BEGIN '
            if not isinstance(pem, str) or not (pem.startswith(pem_prefix + 'RSA PRIVATE KEY-----') or pem.startswith(pem_prefix + 'PRIVATE KEY-----')) or len(pem)>16000:
                raise ValueError('Invalid PEM private key')
            from cryptography.hazmat.primitives import serialization
            serialization.load_pem_private_key(pem.encode(), password=None)
            credentials = {'app_id': data['app_id'], 'private_key_pem': pem}
            expiry = None
        elif provider == 'atlassian_rovo_mcp':
            if set(data) != {'api_key'} or not isinstance(data.get('api_key'), str) or not (15 <= len(data['api_key']) <= 16000):
                raise ValueError('Atlassian service account API key required')
            credentials = {'api_key': data['api_key']}
            expiry = None
        elif provider == "google_agent_engine":
            if set(data) != {"service_account_json"}:
                raise ValueError("Google credentials require service_account_json")
            if not isinstance(data["service_account_json"], str):
                raise ValueError("Service account JSON must be text")
            key = json.loads(data["service_account_json"])
            if not isinstance(key, dict) or key.get("type") != "service_account":
                raise ValueError("Not a service account key")
            if key.get("token_uri") != "https://oauth2.googleapis.com/token":
                raise ValueError("Invalid Google OAuth token endpoint")
            if (not isinstance(key.get("private_key"), str) or
                    not key["private_key"].startswith("-----BEGIN PRIVATE KEY-----") or
                    not isinstance(key.get("client_email"), str) or
                    not key["client_email"].endswith(".gserviceaccount.com") or
                    not isinstance(key.get("private_key_id"), str) or
                    not isinstance(key.get("client_id"), str)):
                raise ValueError("Not a supported Google service account key")
            credentials = key
            expiry = None
        else:
            raise ValueError("Provider does not support local credentials")
    except Exception:
        # Never include raw validator exceptions (possibly containing key material) in responses.
        raise HTTPException(422, "Invalid credential data for the selected provider. Check all required fields.") from None
    try:
        with connection() as db:
            existing = db.execute("""SELECT pc.id, pc.provider, cr.encrypted_json
                 FROM provider_credentials cr JOIN provider_connections pc ON pc.id=cr.connection_id
                 WHERE pc.tenant_id=? LIMIT 1""", (actor.tenant_id,)).fetchone()
            if existing:
                # Never encrypt new credentials under a replacement/wrong master key
                # while existing records require the original one.
                vault.decrypt(existing['id'], existing['provider'], existing['encrypted_json'])
            encrypted = vault.encrypt(connection_id, provider, credentials, has_saved_credentials=existing is not None)
            now = iso(utc_now())
            db.execute("""INSERT INTO provider_credentials (connection_id,encrypted_json,saved_at,rotated_at,expires_at,tenant_id)
              VALUES (?,?,?,?,?,?) ON CONFLICT(connection_id) DO UPDATE SET
              encrypted_json=excluded.encrypted_json,rotated_at=excluded.rotated_at,expires_at=excluded.expires_at""",
              (connection_id, encrypted, now, now, expiry, actor.tenant_id))
            db.execute('UPDATE provider_connections SET last_error=NULL WHERE id=? AND tenant_id=?', (connection_id, actor.tenant_id))
            _audit(db, actor, 'credentials.replace', connection_id)
    except vault.VaultError as exc:
        raise HTTPException(503, str(exc)) from None
    return {"configured": True, "credential_source": "encrypted", "credential_status":
            'expired' if expiry and datetime.fromisoformat(expiry.replace('Z', '+00:00')) <= utc_now()
            else ('ready' if expiry else 'expiration_unknown'),
            "notice": "Encrypted in SQLite, key stored separately; survives server restart"}


@app.delete("/api/connections/{connection_id}/credentials")
def clear_session_credentials(connection_id: str, request: Request):
    actor = require(request, 'connections.credentials')
    require_resource(actor, connection_id)
    _require_local_credentials_request(request)
    with connection() as db:
        row = db.execute("SELECT provider, auth_mode FROM provider_connections WHERE id=? AND tenant_id=?", (connection_id, actor.tenant_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Provider connection not found")
    with connection() as db:
        _clear_saved_credentials(db, connection_id, actor.tenant_id)
        _audit(db, actor, 'credentials.clear', connection_id)
    return {"cleared": True}


@app.post("/api/connections/{connection_id}/test")
def test_connection(connection_id: str, request: Request):
    """Read-only API probe; unlike discover, does not change inventory or sync metadata."""
    actor = require(request, 'connection_admin')
    require_resource(actor, connection_id)
    with connection() as db:
        row = db.execute("SELECT * FROM provider_connections WHERE id=? AND tenant_id=?", (connection_id, actor.tenant_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Provider connection not found")
    configured = _public_connection(row)
    if configured['provider'] in ('github_inventory','atlassian_rovo_mcp'):
        return provider_integrations.run(request, actor, row, sync=False)
    if configured['provider'] == 'custom_registry':
        raise HTTPException(409, 'Private registry uses POST /api/connections/{id}/ingest')
    if configured["credential_source"] in ("encrypted", "vault_unavailable"):
        _require_local_credentials_request(request)
    try:
        agents = _discover_with_connection(configured)
    except connectors.DiscoveryError as exc:
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "Provider test failed; check credentials and access") from exc
    return {"connected": True, "visible_agents": len(agents), "notice": "Read-only test. Inventory unchanged."}


@app.patch("/api/connections/{connection_id}")
def edit_connection(connection_id: str, payload: ConnectionUpdate, request: Request):
    actor = require(request, 'connection_admin')
    require_resource(actor, connection_id)
    with connection() as db:
        row = db.execute("SELECT * FROM provider_connections WHERE id=? AND tenant_id=?", (connection_id, actor.tenant_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Provider connection not found")
        try:
            new_scope = connectors.validate_scope(row["provider"], payload.scope)
            auth_mode, auth_config = connectors.validate_auth_config(row['provider'], payload.auth_mode, payload.auth_config,
                                                                     existing=json.loads(row['auth_config_json']))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        current_scope = json.loads(row["scope_json"])
        scope_changed = new_scope != current_scope
        credential_changed = (row["env_prefix"] != payload.env_prefix or row['auth_mode'] != auth_mode or
                              json.loads(row['auth_config_json']) != auth_config)
        target_changed = scope_changed or credential_changed
        count = db.execute("SELECT COUNT(*) FROM discovered_agents WHERE connection_id=? AND tenant_id=?", (connection_id, actor.tenant_id)).fetchone()[0]
        count += db.execute('SELECT COUNT(*) FROM provider_inventory WHERE connection_id=? AND tenant_id=?',(connection_id, actor.tenant_id)).fetchone()[0]
        if target_changed and count and not payload.clear_inventory_on_scope_change:
            raise HTTPException(409, detail=f"This identity/scope has {count} previously discovered agent(s). Confirm clearing stale inventory records before changing the connection target.")
        if target_changed and count:
            db.execute('DELETE FROM trust_links WHERE tenant_id=? AND tool_id IN (SELECT id FROM trust_tools WHERE connection_id=? AND tenant_id=?)',(actor.tenant_id, connection_id, actor.tenant_id))
            db.execute('DELETE FROM trust_tools WHERE connection_id=? AND tenant_id=?',(connection_id, actor.tenant_id))
            db.execute('DELETE FROM provider_inventory WHERE connection_id=? AND tenant_id=?',(connection_id, actor.tenant_id))
            # Old inventory is no longer valid for the new provider identity or project/region.
            db.execute("DELETE FROM discovered_agents WHERE connection_id=? AND tenant_id=?", (connection_id, actor.tenant_id))
        reset_sync = target_changed
        if reset_sync:
            _clear_saved_credentials(db, connection_id, actor.tenant_id)
        db.execute("""UPDATE provider_connections
            SET label=?, scope_json=?, env_prefix=?, auth_mode=?, auth_config_json=?,
                last_synced_at=CASE WHEN ? THEN NULL ELSE last_synced_at END,
                last_error=CASE WHEN ? THEN NULL ELSE last_error END
            WHERE id=? AND tenant_id=?""", (
                payload.label, json.dumps(new_scope), payload.env_prefix, auth_mode, json.dumps(auth_config),
                int(reset_sync), int(reset_sync), connection_id, actor.tenant_id,
            ))
        updated = db.execute("SELECT * FROM provider_connections WHERE id=? AND tenant_id=?", (connection_id, actor.tenant_id)).fetchone()
        _audit(db, actor, 'connection.update', connection_id)
    # Read saved credential metadata only after the scope change has committed.
    return {**_public_connection(updated), "cleared_inventory_count": count if target_changed else 0}


@app.delete("/api/connections/{connection_id}")
def remove_connection(connection_id: str, request: Request, remove_inventory: bool = Query(default=False)):
    actor = require(request, 'members.manage')
    require_resource(actor, connection_id)
    with connection() as db:
        row = db.execute("SELECT id FROM provider_connections WHERE id=? AND tenant_id=?", (connection_id, actor.tenant_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Provider connection not found")
        count = db.execute("SELECT COUNT(*) FROM discovered_agents WHERE connection_id=? AND tenant_id=?", (connection_id, actor.tenant_id)).fetchone()[0]
        if count and not remove_inventory:
            raise HTTPException(409, detail=f"Connection has {count} discovered agent(s). Confirm local inventory removal.")
        db.execute('DELETE FROM trust_links WHERE tenant_id=? AND tool_id IN (SELECT id FROM trust_tools WHERE connection_id=? AND tenant_id=?)',(actor.tenant_id, connection_id, actor.tenant_id))
        db.execute('DELETE FROM trust_tools WHERE connection_id=? AND tenant_id=?',(connection_id, actor.tenant_id))
        db.execute('DELETE FROM provider_inventory WHERE connection_id=? AND tenant_id=?',(connection_id, actor.tenant_id))
        db.execute("DELETE FROM discovered_agents WHERE connection_id=? AND tenant_id=?", (connection_id, actor.tenant_id))
        db.execute("DELETE FROM provider_connections WHERE id=? AND tenant_id=?", (connection_id, actor.tenant_id))
        _audit(db, actor, 'connection.remove', connection_id)
        return {"removed": True, "removed_inventory_count": count}


@app.post("/api/connections/{connection_id}/discover")
def sync_connection(connection_id: str, request: Request):
    actor = require(request, 'connection_admin')
    require_resource(actor, connection_id)
    with connection() as db:
        row = db.execute("SELECT * FROM provider_connections WHERE id=? AND tenant_id=?", (connection_id, actor.tenant_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Provider connection not found")
        configured = _public_connection(row)
    if configured['provider'] in ('github_inventory','atlassian_rovo_mcp'):
        return provider_integrations.run(request, actor, row, sync=True)
    if configured['provider'] == 'custom_registry':
        raise HTTPException(409, 'Private registry uses POST /api/connections/{id}/ingest')
    if configured["credential_source"] in ("encrypted", "vault_unavailable"):
        _require_local_credentials_request(request)
    # Remote discovery completes BEFORE the DB transaction: partial fetch failures do not
    # cause partial inventory writes. A successful empty response does not remove old records.
    try:
        agents = _discover_with_connection(configured)
        if len(agents) > 10000:
            raise connectors.DiscoveryError("Over 10,000 agents returned; narrow the scope")
    except connectors.DiscoveryError as exc:
        with connection() as db:
            db.execute("UPDATE provider_connections SET last_error=? WHERE id=? AND tenant_id=?", (str(exc), connection_id, actor.tenant_id))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        # Never expose raw provider exceptions (they could contain tokens, URLs or tenant IDs).
        with connection() as db:
            db.execute("UPDATE provider_connections SET last_error=? WHERE id=? AND tenant_id=?", ("Provider integration failed; inspect server logs", connection_id, actor.tenant_id))
        raise HTTPException(status_code=502, detail="Provider integration failed; check credentials and access") from exc
    synced = iso(utc_now())
    with connection() as db:
        for item in agents:
            db.execute("""INSERT INTO discovered_agents (
              id, connection_id, external_id, name, provider, description, provider_status,
              discovered_at, discovery_last_seen, created_at, tenant_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(connection_id,external_id) DO UPDATE SET
              name=excluded.name, provider=excluded.provider, description=excluded.description,
              provider_status=excluded.provider_status, discovery_last_seen=excluded.discovery_last_seen
            """, (
              "ext-" + uuid4().hex, connection_id, item.external_id, item.name[:100], item.provider[:100],
              item.description[:500], item.provider_status[:100], synced, synced, synced, actor.tenant_id
            ))
        db.execute("UPDATE provider_connections SET last_synced_at=?, last_error=NULL WHERE id=? AND tenant_id=?", (synced, connection_id, actor.tenant_id))
        _audit(db, actor, 'connection.discover', connection_id)
    return {"connection_id": connection_id, "discovered": len(agents), "synced_at": synced,
            "notice": "Inventory only. No agent actions, telemetry, runtime activity or billing imported."}


# Collector-only inventory synchronization: uses existing Foundry provider connections.
# Does not require a separate JSON map or a browser login. Fails closed on
# incomplete discovery so a new agent cannot be silently attributed to old data.
@app.get('/api/runtime/azure-inventory-ready')
def azure_inventory_ready(request: Request):
    from .runtime import _collector
    tenant = _collector(request)
    with connection() as db:
        configured = db.execute(
            "SELECT 1 FROM provider_connections "
            "WHERE tenant_id=? AND provider='microsoft_foundry' LIMIT 1",
            (tenant,)
        ).fetchone() is not None
    return {'configured': configured}


@app.post('/api/runtime/azure-inventory-sync')
def collector_sync_azure_inventory(request: Request):
    from .runtime import _collector
    tenant = _collector(request)
    with connection() as db:
        connections = [dict(r) for r in db.execute(
            "SELECT * FROM provider_connections WHERE tenant_id=? AND provider='microsoft_foundry' ORDER BY id",
            (tenant,)).fetchall()]
    if not connections:
        raise HTTPException(409, 'No Microsoft Foundry provider connection is configured')
    snapshots = []
    for row in connections:
        configured = _public_connection(row)
        try:
            discovered = _discover_with_connection(configured)
        except Exception:
            # No raw provider errors, endpoint URLs, credentials or tokens are exposed.
            raise HTTPException(503, 'Microsoft Foundry discovery failed; verify existing connection credentials and project permissions') from None
        if len(discovered) > 10000:
            raise HTTPException(503, 'Foundry discovery exceeds the supported inventory limit')
        snapshots.append((row, discovered))
    now = iso(utc_now())
    with connection() as db:
        for row, discovered in snapshots:
            for item in discovered:
                db.execute("""INSERT INTO discovered_agents (
                    id,connection_id,external_id,name,provider,description,provider_status,
                    discovered_at,discovery_last_seen,created_at,tenant_id)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(connection_id,external_id) DO UPDATE SET
                    name=excluded.name,provider_status=excluded.provider_status,
                    description=excluded.description,discovery_last_seen=excluded.discovery_last_seen
                """, ('ext-'+uuid4().hex,row['id'],item.external_id,item.name[:100],
                      item.provider[:100],item.description[:500],item.provider_status[:100],
                      now,now,now,tenant))
            db.execute("UPDATE provider_connections SET last_synced_at=?,last_error=NULL WHERE id=? AND tenant_id=?",
                       (now,row['id'],tenant))
        # Do not return project endpoints or credentials. Only exact provider
        # identities required for client-side correlation.
        rows = [dict(r) for r in db.execute("""SELECT a.id,a.external_id,a.name,a.connection_id
            FROM discovered_agents a JOIN provider_connections c ON c.id=a.connection_id
            WHERE a.tenant_id=? AND c.provider='microsoft_foundry' AND
            a.discovery_last_seen=? ORDER BY a.id""",(tenant,now)).fetchall()]
    return {'agents':rows,'connections_synced':len(snapshots), 'discovered':sum(len(d) for _,d in snapshots)}


# --- Business-owner approval. Technical administrators cannot approve or reject. ---
class AssignBusinessOwner(BaseModel):
    owner_user_id: str = Field(min_length=5, max_length=80)

class ApprovalRequest(BaseModel):
    justification: str = Field(min_length=10, max_length=1500)
    requested_budget_usd: float = Field(ge=0, le=1e9)
    cost_center: str = Field(min_length=2, max_length=80)

class ApprovalDecision(BaseModel):
    decision: Literal['approved','rejected']
    reason: str = Field(min_length=10, max_length=1500)

def _governed_agent(db, tenant_id: str, agent_id: str):
    for table in ('agents','discovered_agents'):
        row = db.execute(f'SELECT id,connection_id,budget_usd,cost_center FROM {table} WHERE id=? AND tenant_id=?',
                         (agent_id,tenant_id)).fetchone()
        if row:
            return row
    raise HTTPException(404,'Agent not found')

@app.get('/api/business-owners')
def list_business_owners(request: Request):
    require(request,'agents.owner.assign')
    with connection() as db:
        rows = db.execute("SELECT id,username,display_name,email FROM local_users WHERE role='business_owner' AND active=1 ORDER BY username").fetchall()
    return [dict(r) for r in rows]


@app.post('/api/agents/{agent_id}/business-owner')
def assign_business_owner(agent_id: str, payload: AssignBusinessOwner, request: Request):
    actor = require(request,'agents.owner.assign')
    with connection() as db:
        agent = _governed_agent(db,actor.tenant_id,agent_id)
        require_resource(actor,agent['connection_id'],agent_id)
        person = db.execute('SELECT id,role,active,scope_json FROM local_users WHERE id=?', (payload.owner_user_id,)).fetchone()
        if not person or person['role'] != 'business_owner' or not person['active']:
            raise HTTPException(422,'Assign an active user with the Business Owner role')
        scope = json.loads(person['scope_json'])
        # Assignments are explicit and cannot give wider company access.
        if scope.get('kind') != 'selected':
            raise HTTPException(422,'Business Owner must have selected resource scope')
        agent_ids=scope.get('agent_ids',[])
        if agent_id not in agent_ids:
            scope['agent_ids']=[*agent_ids,agent_id]
            db.execute('UPDATE local_users SET scope_json=? WHERE id=?', (json.dumps(scope),person['id']))
        old_owner=db.execute('SELECT business_owner_user_id FROM agent_governance WHERE tenant_id=? AND agent_id=?',
                             (actor.tenant_id,agent_id)).fetchone()
        if old_owner and old_owner['business_owner_user_id'] and old_owner['business_owner_user_id']!=person['id']:
            previous=db.execute('SELECT scope_json FROM local_users WHERE id=?',(old_owner['business_owner_user_id'],)).fetchone()
            if previous:
                old_scope=json.loads(previous['scope_json'])
                if old_scope.get('kind')=='selected':
                    old_scope['agent_ids']=[x for x in old_scope.get('agent_ids',[]) if x!=agent_id]
                    db.execute('UPDATE local_users SET scope_json=? WHERE id=?',(json.dumps(old_scope),old_owner['business_owner_user_id']))
        now=iso(utc_now())
        db.execute("""INSERT INTO agent_governance
          (tenant_id,agent_id,business_owner_user_id,approval_status,updated_at)
          VALUES (?,?,?,'not_reviewed',?)
          ON CONFLICT(tenant_id,agent_id) DO UPDATE SET
            business_owner_user_id=excluded.business_owner_user_id,approval_status='not_reviewed',
            justification='',requested_cost_center='',submitted_by=NULL,submitted_at=NULL,decided_by=NULL,
            decided_at=NULL,decision_reason='',requested_budget_usd=0,updated_at=excluded.updated_at""",
          (actor.tenant_id,agent_id,person['id'],now))
        _audit(db,actor,'agent.business_owner.assign',agent_id,{'business_owner_id':person['id']})
    return {'assigned':True,'agent_id':agent_id,'business_owner_user_id':person['id'],'approval_status':'not_reviewed'}

@app.post('/api/agents/{agent_id}/approval-request')
def submit_agent_approval(agent_id: str,payload: ApprovalRequest,request: Request):
    actor=require(request,'agents.submit')
    with connection() as db:
        agent=_governed_agent(db,actor.tenant_id,agent_id)
        require_resource(actor,agent['connection_id'],agent_id)
        g=db.execute('SELECT * FROM agent_governance WHERE tenant_id=? AND agent_id=?',
                     (actor.tenant_id,agent_id)).fetchone()
        if not g or not g['business_owner_user_id']:
            raise HTTPException(409,'Assign a Business Owner before requesting approval')
        if g['approval_status']=='pending':
            raise HTTPException(409,'Approval request already pending')
        if g['approval_status']=='approved':
            raise HTTPException(409,'Approved request requires formal reassessment before resubmission')
        owner=db.execute('SELECT active,role FROM local_users WHERE id=?', (g['business_owner_user_id'],)).fetchone()
        if not owner or not owner['active'] or owner['role']!='business_owner':
            raise HTTPException(409,'Assigned Business Owner is not active')
        now=iso(utc_now())
        db.execute("""UPDATE agent_governance SET approval_status='pending',justification=?,
          requested_budget_usd=?,requested_cost_center=?,submitted_by=?,submitted_at=?,decided_by=NULL,decided_at=NULL,
          decision_reason='',updated_at=? WHERE tenant_id=? AND agent_id=?""",
          (payload.justification,payload.requested_budget_usd,payload.cost_center,actor.subject,now,now,actor.tenant_id,agent_id))
        _audit(db,actor,'agent.approval.submit',agent_id,{'requested_budget_usd':payload.requested_budget_usd,'cost_center':payload.cost_center})
    return {'submitted':True,'approval_status':'pending','business_owner_user_id':g['business_owner_user_id']}

@app.post('/api/agents/{agent_id}/approval-decision')
def decide_agent_approval(agent_id: str,payload: ApprovalDecision,request: Request):
    actor=require(request,'agents.approve')
    with connection() as db:
        agent=_governed_agent(db,actor.tenant_id,agent_id)
        require_resource(actor,agent['connection_id'],agent_id)
        g=db.execute('SELECT * FROM agent_governance WHERE tenant_id=? AND agent_id=?',
                     (actor.tenant_id,agent_id)).fetchone()
        if not g or g['approval_status']!='pending':
            raise HTTPException(409,'No pending approval request')
        if actor.subject != 'local-user:' + str(g['business_owner_user_id']):
            raise HTTPException(403,'Only the assigned Business Owner may decide')
        if g['submitted_by']==actor.subject:
            raise HTTPException(403,'A requester cannot approve their own submission')
        now=iso(utc_now())
        db.execute("""UPDATE agent_governance SET approval_status=?,decided_by=?,decided_at=?,
             decision_reason=?,updated_at=? WHERE tenant_id=? AND agent_id=?""",
             (payload.decision,actor.subject,now,payload.reason,now,actor.tenant_id,agent_id))
        _audit(db,actor,'agent.approval.'+payload.decision,agent_id,
               {'business_owner_id':g['business_owner_user_id'],'requested_budget_usd':g['requested_budget_usd'],
                'cost_center':g['requested_cost_center'],'reason':payload.reason})
    return {'agent_id':agent_id,'approval_status':payload.decision,'decided_at':now}

# --- Outbound-only ingestion for customer-hosted agent registries. ---
class PrivateAgentRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    external_id: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default='', max_length=500)
    provider_status: str = Field(default='unknown', max_length=80)
    owner_email: str | None = Field(default=None, max_length=254)


class PrivateAgentBatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    agents: list[PrivateAgentRecord] = Field(min_length=1, max_length=500)


@app.post('/api/connections/{connection_id}/ingest')
def ingest_private_registry(connection_id: str, payload: PrivateAgentBatch, request: Request):
    actor = require(request, 'connection_admin')
    require_resource(actor, connection_id)
    with connection() as db:
        row = db.execute('SELECT * FROM provider_connections WHERE id=? AND tenant_id=?',
                         (connection_id, actor.tenant_id)).fetchone()
        if row is None:
            raise HTTPException(404, 'Provider connection not found')
        if row['provider'] != 'custom_registry' or row['auth_mode'] != 'push_oidc':
            raise HTTPException(409, 'This connection does not accept private registry ingestion')
        # Duplicate external IDs in the batch would otherwise silently override each other.
        ids = [item.external_id for item in payload.agents]
        if len(set(ids)) != len(ids):
            raise HTTPException(422, 'Duplicate external_id in the submitted batch')
        now = iso(utc_now())
        for item in payload.agents:
            db.execute('''INSERT INTO discovered_agents
                 (id,connection_id,external_id,name,provider,description,provider_status,
                  owner_email,discovered_at,discovery_last_seen,created_at,tenant_id)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                 ON CONFLICT(connection_id,external_id) DO UPDATE SET
                  name=excluded.name, description=excluded.description,
                  provider_status=excluded.provider_status, owner_email=excluded.owner_email,
                  discovery_last_seen=excluded.discovery_last_seen''',
                 ('ext-'+uuid4().hex, connection_id, item.external_id, item.name,
                  'Private Agent Registry', item.description, item.provider_status,
                  item.owner_email, now, now, now, actor.tenant_id))
        db.execute('UPDATE provider_connections SET last_synced_at=?,last_error=NULL WHERE id=? AND tenant_id=?',
                   (now, connection_id, actor.tenant_id))
        _audit(db, actor, 'registry.ingest', connection_id)
    return {'connection_id': connection_id, 'ingested': len(payload.agents), 'received_at': now,
            'notice': 'Inventory metadata only. No agent code, secrets, prompts or runtime activity collected.'}



# --- Single-company browser login and local password-account administration. ---
# Local password accounts are development-only; enterprise SSO remains the target for hosted use.

class PasswordLogin(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=local_accounts.MAX_PASSWORD_LENGTH)

class PasswordChange(BaseModel):
    current_password: str
    new_password: str

class LocalUserCreate(BaseModel):
    username: str
    display_name: str = ''
    email: str = ''
    initial_password: str
    role: Literal['admin','provider_admin','agent_owner','business_owner','auditor','viewer']
    scope: dict | None = None

class LocalUserUpdate(BaseModel):
    capabilities: list[str] | None = None  # Restricted to the selected role's permission ceiling
    display_name: str | None = None
    email: str | None = None
    role: Literal['admin','provider_admin','agent_owner','business_owner','auditor','viewer'] | None = None
    scope: dict | None = None
    active: bool | None = None

class AdminResetPassword(BaseModel):
    temporary_password: str


def _password_mode():
    if os.getenv('GAME_AUTH_MODE', 'password').lower() != 'password':
        raise HTTPException(404, 'Local password authentication is disabled')


def _validate_local_scope(role: str, scope: dict | None):
    if scope is None:
        return {'kind':'all'} if role in ('admin','auditor') else {'kind':'selected','connection_ids':[],'agent_ids':[]}
    if not isinstance(scope, dict) or scope.get('kind') not in ('selected','all') or set(scope) - {'kind','connection_ids','agent_ids'}:
        raise HTTPException(422, 'Invalid resource scope')
    if role in ('admin','auditor') and scope.get('kind') != 'all':
        raise HTTPException(422, 'Admin and Auditor must have company-wide scope')
    if role == 'business_owner' and scope.get('kind') != 'selected':
        raise HTTPException(422, 'Business Owner must be scoped to assigned agents')
    if scope.get('kind') == 'selected':
        ids=(scope.get('connection_ids',[]),scope.get('agent_ids',[]))
        if any(not isinstance(values,list) or len(values)>500 or any(not isinstance(v,str) for v in values) for values in ids):
            raise HTTPException(422, 'Invalid resource scope IDs')
        with connection() as db:
            for cid in ids[0]:
                if not db.execute('SELECT 1 FROM provider_connections WHERE id=? AND tenant_id=?',(cid,LOCAL_TENANT)).fetchone():
                    raise HTTPException(422, 'Connection scope does not exist')
            for aid in ids[1]:
                if not (db.execute('SELECT 1 FROM agents WHERE id=? AND tenant_id=?',(aid,LOCAL_TENANT)).fetchone() or
                        db.execute('SELECT 1 FROM discovered_agents WHERE id=? AND tenant_id=?',(aid,LOCAL_TENANT)).fetchone()):
                    raise HTTPException(422, 'Agent scope does not exist')
        return {'kind':'selected','connection_ids':list(dict.fromkeys(ids[0])),'agent_ids':list(dict.fromkeys(ids[1]))}
    return {'kind':'all'}


def _require_password_admin(request: Request):
    _password_mode()
    actor=require(request,'members.manage')
    if actor.role != 'admin':
        raise HTTPException(403, 'Company Admin required')
    return actor


@app.post('/api/auth/login')
def browser_login(payload: PasswordLogin, request: Request):
    _password_mode()
    origin=request.headers.get('origin')
    if origin:
        from urllib.parse import urlparse
        parsed=urlparse(origin)
        if parsed.scheme!=request.url.scheme or parsed.netloc!=request.headers.get('host'):
            raise HTTPException(403,'Cross-origin login not permitted')
    client=request.client.host if request.client else ''
    user=local_accounts.authenticate(payload.username,payload.password,client)
    token,csrf=local_accounts.start_session(user['id'])
    with connection() as db:
        _audit(db,type('Actor',(),{'tenant_id':LOCAL_TENANT,'subject':'local-user:'+user['id']})(),
               'auth.login',user['id'])
    response=JSONResponse({'authenticated':True,'must_change_password':bool(user['must_change_password']),
                           'user':local_accounts.public_user(user),'csrf_token':csrf})
    response.set_cookie(local_accounts.COOKIE, token, httponly=True,
                        secure=request.url.scheme=='https', samesite='strict',
                        max_age=local_accounts.SESSION_HOURS*3600, path='/')
    return response


@app.get('/api/auth/session')
def browser_session(request: Request):
    _password_mode()
    row=local_accounts.session_user(request,enforce_password_change=False)
    return {'authenticated':True,'csrf_token':row['csrf_token'],
            'must_change_password':bool(row['must_change_password']),
            'user':local_accounts.public_user(row)}


@app.post('/api/auth/logout')
def browser_logout(request: Request):
    _password_mode()
    row=local_accounts.session_user(request,enforce_password_change=False)
    local_accounts.check_csrf(request,row)
    with connection() as db:
        db.execute('UPDATE local_sessions SET revoked_at=? WHERE token_hash=?',
                   (iso(utc_now()),local_accounts.token_digest(request.cookies.get(local_accounts.COOKIE,''))))
    with connection() as db:
        _audit(db,type('Actor',(),{'tenant_id':LOCAL_TENANT,'subject':'local-user:'+row['id']})(), 'auth.logout',row['id'])
    response=JSONResponse({'signed_out':True})
    response.delete_cookie(local_accounts.COOKIE,path='/')
    return response


@app.post('/api/auth/change-password')
def browser_change_password(payload: PasswordChange,request: Request):
    _password_mode()
    row=local_accounts.session_user(request,enforce_password_change=False)
    local_accounts.check_csrf(request,row)
    if not local_accounts.verify_password(row['password_hash'],payload.current_password):
        raise HTTPException(400,'Current password is incorrect')
    if local_accounts.verify_password(row['password_hash'],payload.new_password):
        raise HTTPException(422,'New password must differ from the current password')
    try:
        new_hash=local_accounts.hash_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None
    with connection() as db:
        db.execute('UPDATE local_users SET password_hash=?, must_change_password=0, password_changed_at=? WHERE id=?',
                   (new_hash,iso(utc_now()),row['id']))
        local_accounts.revoke_user_sessions(db,row['id'])
        _audit(db, type('Actor',(),{'tenant_id':LOCAL_TENANT,'subject':row['id']})(), 'account.password.change',row['id'])
    response=JSONResponse({'changed':True,'reauthentication_required':True})
    response.delete_cookie(local_accounts.COOKIE,path='/')
    return response


@app.get('/api/local-users')
def list_local_users(request: Request):
    _require_password_admin(request)
    with connection() as db:
        return [{**local_accounts.public_user(dict(row)), 'scope':json.loads(row['scope_json']),
                 'capabilities': sorted(json.loads(row['capabilities_json'])) if row['capabilities_json'] is not None else sorted(rbac.effective_capabilities(row['role']))}
                for row in db.execute('SELECT * FROM local_users ORDER BY username').fetchall()]


@app.post('/api/local-users',status_code=201)
def add_local_user(payload: LocalUserCreate, request: Request):
    actor=_require_password_admin(request)
    scope=_validate_local_scope(payload.role,payload.scope)
    try:
        result=local_accounts.create_user(payload.username,payload.initial_password,payload.role,
             display_name=payload.display_name,email=payload.email,scope=scope,must_change=True)
    except (ValueError,sqlite3.IntegrityError) as exc:
        raise HTTPException(422,'Unable to create user: '+str(exc)) from None
    with connection() as db:
        _audit(db, actor, 'local-user.create',result['id'])
    return result


@app.patch('/api/local-users/{user_id}')
def update_local_user(user_id: str,payload: LocalUserUpdate,request: Request):
    actor=_require_password_admin(request)
    session=local_accounts.session_user(request)
    update=payload.model_dump(exclude_unset=True)
    if not update:
        raise HTTPException(422,'No changes requested')
    with connection() as db:
        row=db.execute('SELECT * FROM local_users WHERE id=?',(user_id,)).fetchone()
        if not row:
            raise HTTPException(404,'User not found')
        role=update.get('role',row['role'])
        active=int(update.get('active',row['active']))
        # Prevent both self-demotion and losing the last enabled Admin.
        if user_id==session['id'] and (role!='admin' or not active):
            raise HTTPException(409,'Cannot deactivate or demote your own administrator account')
        if row['role']=='admin' and (role!='admin' or not active) and row['active']:
            count=db.execute("SELECT COUNT(*) FROM local_users WHERE role='admin' AND active=1").fetchone()[0]
            if count<=1:
                raise HTTPException(409,'Cannot remove the last active Admin')
    scope=_validate_local_scope(role,update.get('scope',json.loads(row['scope_json'])))
    # On role change, default to the new role's full inherited permission set.
    # Existing overrides are retained only if role is unchanged and the request
    # does not explicitly replace them.
    chosen=update.get('capabilities')
    if chosen is None:
        chosen=(json.loads(row['capabilities_json']) if row['capabilities_json'] is not None
                else list(rbac.effective_capabilities(role))) if role==row['role'] else list(rbac.effective_capabilities(role))
    try:
        selected=rbac.validate_selection(role,chosen)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None
    with connection() as db:
        db.execute('UPDATE local_users SET display_name=?,email=?,role=?,scope_json=?,active=?,capabilities_json=? WHERE id=?',
                   (update.get('display_name',row['display_name'])[:120],
                    update.get('email',row['email'])[:254],role,json.dumps(scope),active,json.dumps(sorted(selected)),user_id))
        # New role and disabled state apply immediately to all open browser sessions.
        if not active:
            local_accounts.revoke_user_sessions(db,user_id)
        _audit(db,actor,'local-user.update',user_id,{'role_before':row['role'],'role_after':role,
            'capabilities':sorted(selected),'scope_kind':scope['kind'],'active':bool(active)})
    return {'updated':True}


@app.post('/api/local-users/{user_id}/reset-password')
def admin_reset_local_password(user_id:str,payload:AdminResetPassword,request:Request):
    actor=_require_password_admin(request)
    me=local_accounts.session_user(request)
    if me['id']==user_id:
        raise HTTPException(409,'Use Change Password for your own account')
    try:
        new_hash=local_accounts.hash_password(payload.temporary_password)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None
    with connection() as db:
        user=db.execute('SELECT id FROM local_users WHERE id=?',(user_id,)).fetchone()
        if not user:
            raise HTTPException(404,'User not found')
        db.execute('UPDATE local_users SET password_hash=?,must_change_password=1,password_changed_at=? WHERE id=?',
                   (new_hash,iso(utc_now()),user_id))
        local_accounts.revoke_user_sessions(db,user_id)
        _audit(db,actor,'local-user.password.reset',user_id)
    return {'reset':True,'must_change_password':True}


@app.get('/login',include_in_schema=False)
def login_page(request:Request):
    _password_mode()
    try:
        session=local_accounts.session_user(request,enforce_password_change=False)
    except HTTPException:
        session=None
    if session:
        return RedirectResponse('/password' if session['must_change_password'] else '/',status_code=303)
    return FileResponse(static_dir/'login.html')


@app.get('/password',include_in_schema=False)
def password_page(request:Request):
    _password_mode()
    local_accounts.session_user(request,enforce_password_change=False)
    return FileResponse(static_dir/'password.html')


static_dir = Path(__file__).resolve().parents[2] / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.middleware("http")
async def disable_demo_static_cache(request: Request, call_next):
    # Password mode is for localhost development. A hosted version must use enterprise SSO.
    if os.getenv('GAME_AUTH_MODE', 'password').lower() == 'password':
        origin_host=request.client.host if request.client else ''
        if origin_host not in ('127.0.0.1','::1','testclient'):
            return JSONResponse({'detail':'Password mode permits localhost only'},status_code=403)
    # Prevent an older app.js from breaking tabs after a local upgrade.
    response = await call_next(request)
    if request.url.path in ("/", "/login", "/password") or request.url.path.startswith("/static/") or request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer' 
    return response


@app.get("/", include_in_schema=False)
def index(request: Request):
    if os.getenv('GAME_AUTH_MODE', 'password').lower() == 'password':
        try:
            row=local_accounts.session_user(request,enforce_password_change=False)
        except HTTPException:
            return RedirectResponse('/login',status_code=303)
        if row['must_change_password']:
            return RedirectResponse('/password',status_code=303)
    return FileResponse(static_dir / "index.html")
