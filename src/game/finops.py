# SPDX-License-Identifier: AGPL-3.0-only
"""Evidence-based FinOps v0.3.4.0. Estimates never masquerade as billed charges."""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4
import re
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .auth import require, permits_resource
from . import rbac
from .db import connection, iso, utc_now
from .runtime import _collector, _period_start, _visible_agent, _ts

router = APIRouter(prefix='/api/finops', tags=['finops'])
SAFE_MODEL = re.compile(r'^[a-zA-Z0-9._:/@+\-]{1,140}$')
SAFE_OPERATION = re.compile(r'^[a-zA-Z0-9._:/@\-]{1,160}$')

class UsageEvidence(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    agent_id: str = Field(min_length=1, max_length=160)
    source: str = Field(pattern=r'^[a-zA-Z0-9._-]{2,80}$')
    external_run_id: str = Field(min_length=1, max_length=160)
    operation_id: str = Field(min_length=1, max_length=160)
    occurred_at: datetime
    model_id: str | None = Field(default=None, max_length=140)
    input_tokens: int | None = Field(default=None, ge=0, le=1000000000)
    output_tokens: int | None = Field(default=None, ge=0, le=1000000000)
    evidence: str = Field(pattern=r'^(azure_appinsights_genai_attributes|otel_genai_attributes)$')

    @model_validator(mode='after')
    def check(self):
        _ts(self.occurred_at)
        if not SAFE_OPERATION.fullmatch(self.external_run_id) or not SAFE_OPERATION.fullmatch(self.operation_id):
            raise ValueError('Unsafe source operation ID')
        if self.model_id is not None and not SAFE_MODEL.fullmatch(self.model_id):
            raise ValueError('Unsafe model identifier')
        if self.input_tokens is None and self.output_tokens is None:
            raise ValueError('At least one observed token count is required')
        return self

class RateCard(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    provider: str = Field(pattern=r'^[a-zA-Z0-9._-]{2,80}$')
    model_id: str = Field(min_length=1, max_length=140)
    input_usd_per_million: str
    output_usd_per_million: str
    valid_from: datetime
    valid_until: datetime | None = None
    source_url: str = Field(min_length=12, max_length=500, pattern=r'^https://')

    @model_validator(mode='after')
    def check(self):
        if not SAFE_MODEL.fullmatch(self.model_id): raise ValueError('Invalid model ID')
        _ts(self.valid_from)
        if self.valid_until is not None:
            _ts(self.valid_until)
            if self.valid_until <= self.valid_from: raise ValueError('Invalid effective date range')
        for value in (self.input_usd_per_million,self.output_usd_per_million):
            try: number=Decimal(value)
            except InvalidOperation: raise ValueError('Invalid rate') from None
            if not number.is_finite() or not (0 <= number <= 1000000): raise ValueError('Rate outside allowed range')
        return self

@router.post('/usage/ingest', status_code=201)
def ingest_usage(payload: UsageEvidence, request: Request):
    tenant=_collector(request)
    with connection() as db:
        run=db.execute('''SELECT id FROM runtime_runs WHERE tenant_id=? AND agent_id=? AND source=? AND external_run_id=?''',
            (tenant,payload.agent_id,payload.source,payload.external_run_id)).fetchone()
        if not run: raise HTTPException(404,'Matching runtime execution not found')
        prior=db.execute('''SELECT * FROM finops_usage WHERE tenant_id=? AND source=? AND agent_id=? AND external_run_id=? AND operation_id=?''',
            (tenant,payload.source,payload.agent_id,payload.external_run_id,payload.operation_id)).fetchone()
        if prior:
            for field,val in [('input_tokens',payload.input_tokens),('output_tokens',payload.output_tokens),('model_id',payload.model_id),('occurred_at',_ts(payload.occurred_at))]:
                if prior[field] is not None and val is not None and prior[field] != val:
                    raise HTTPException(409,'Conflicting source usage replay')
            db.execute('''UPDATE finops_usage SET input_tokens=COALESCE(input_tokens,?),output_tokens=COALESCE(output_tokens,?),model_id=COALESCE(model_id,?) WHERE id=?''',
                       (payload.input_tokens,payload.output_tokens,payload.model_id,prior['id']))
        else:
            db.execute('''INSERT INTO finops_usage (id,tenant_id,agent_id,run_id,source,external_run_id,operation_id,occurred_at,model_id,input_tokens,output_tokens,evidence,first_ingested_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                ('fu-'+uuid4().hex,tenant,payload.agent_id,run['id'],payload.source,payload.external_run_id,payload.operation_id,
                 _ts(payload.occurred_at),payload.model_id,payload.input_tokens,payload.output_tokens,payload.evidence,iso(utc_now())))
    return {'accepted':True,'replayed':bool(prior)}

# Azure Cost Management returns charges at Azure resource/billing scope, not
# reliably at Foundry agent scope. Preserve provenance and forbid attribution.
SCOPE_RE = re.compile(r'^/subscriptions/[0-9a-fA-F-]{36}(?:/resourceGroups/[a-zA-Z0-9._()\-]{1,90})?$')
# Azure Cost Management ResourceId is a billing dimension, not guaranteed to be
# an ARM path. Values such as 'Unassigned' and marketplace identifiers are valid.
# Accept bounded, printable identifiers while retaining the original dimension.
RESOURCE_RE = re.compile(r'^[^\x00-\x1f\x7f-\x9f]{1,450}$')

class AzureScopeCostRow(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    resource_id: str = Field(max_length=450)
    usage_day: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    amount: str = Field(max_length=70)

    @model_validator(mode='after')
    def validate_row(self):
        if self.resource_id and not RESOURCE_RE.fullmatch(self.resource_id):
            raise ValueError('Azure billing resource identifier must be printable text (up to 450 characters) or empty')
        try: datetime.strptime(self.usage_day,'%Y-%m-%d')
        except ValueError: raise ValueError('Invalid usage day') from None
        try: number=Decimal(self.amount)
        except InvalidOperation: raise ValueError('Invalid amount') from None
        if not number.is_finite() or abs(number)>Decimal('1000000000000'):
            raise ValueError('Cost amount outside allowed range')
        return self

class AzureScopeCostBatch(BaseModel):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=True)
    scope: str = Field(min_length=20,max_length=200)
    rows: list[AzureScopeCostRow] = Field(max_length=30000)

    @model_validator(mode='after')
    def validate_scope(self):
        if not SCOPE_RE.fullmatch(self.scope): raise ValueError('Unsupported Azure scope')
        if len({(r.resource_id.lower(),r.usage_day,r.currency) for r in self.rows}) != len(self.rows):
            raise ValueError('Duplicate resource/day/currency in batch')
        return self

@router.post('/azure-costs/ingest',status_code=201)
def ingest_azure_costs(payload:AzureScopeCostBatch,request:Request):
    tenant=_collector(request)
    # Rows can be adjusted retroactively by Azure. UPSERT replaces the amount
    # from the same authoritative source; it never SUMs repeated imports.
    with connection() as db:
        for r in payload.rows:
            db.execute("""INSERT INTO finops_azure_scope_costs
                (tenant_id,scope,resource_id,usage_day,currency,amount,collected_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(tenant_id,scope,resource_id,usage_day,currency)
                DO UPDATE SET amount=excluded.amount,collected_at=excluded.collected_at""",
                (tenant,payload.scope.lower(),r.resource_id.lower(),r.usage_day,r.currency,
                 str(Decimal(r.amount)),iso(utc_now())))
    return {'accepted':len(payload.rows),'classification':'azure_scope_actual_cost_unallocated',
            'agent_attribution':'not_available','invoice_verified':False}

@router.get('/azure-costs')
def azure_costs(request:Request,period:str=Query('30d',pattern=r'^(24h|7d|30d|all)$')):
    actor=require(request,'finops.billing.view')
    since=_period_start(period)
    day=since[:10] if since is not None else None
    with connection() as db:
        rows=[dict(r) for r in db.execute("""SELECT scope,resource_id,usage_day,currency,amount,collected_at
           FROM finops_azure_scope_costs WHERE tenant_id=? AND (? IS NULL OR usage_day>=?)
           ORDER BY usage_day DESC,scope,resource_id""",(actor.tenant_id,day,day))]
    # No currency conversion. No conflation of Azure resource charges with per-agent costs.
    total={}
    for row in rows:
        total[row['currency']]=total.get(row['currency'],Decimal(0))+Decimal(row['amount'])
    return {'period':period,'rows':rows,'totals_by_currency':{k:str(v) for k,v in sorted(total.items())},
      'records':len(rows),'last_collection':max((r['collected_at'] for r in rows),default=None),
      'classification':'Azure Cost Management ActualCost (scope-level, subject to adjustment)',
      'agent_attribution':'Not available','invoice_verified':False,
      'notice':'Scope charges may include non-agent resources; not allocated to agents or represented as final invoice charges.'}

@router.post('/rates',status_code=201)
def set_rate(payload:RateCard,request:Request):
    actor=require(request,'finops.rates.manage')
    with connection() as db:
        start=_ts(payload.valid_from)
        end=_ts(payload.valid_until) if payload.valid_until else None
        # Deny overlapping pricing windows; never silently override historical rates.
        old=db.execute('''SELECT 1 FROM finops_rate_cards WHERE tenant_id=? AND provider=? AND model_id=?
          AND (valid_until IS NULL OR valid_until>?) AND (? IS NULL OR valid_from<?)''',
          (actor.tenant_id,payload.provider,payload.model_id,start,end,end)).fetchone()
        if old: raise HTTPException(409,'Overlapping rate period')
        db.execute('''INSERT INTO finops_rate_cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
          ('rate-'+uuid4().hex,actor.tenant_id,payload.provider,payload.model_id,'USD',
           str(Decimal(payload.input_usd_per_million)),str(Decimal(payload.output_usd_per_million)),start,end,
           payload.source_url,actor.subject,iso(utc_now())))
        # Audit price changes by model, period and actor; do not log credentials.
        db.execute('''INSERT INTO audit_events
          (id,tenant_id,actor,operation,resource_id,occurred_at,details_json)
          VALUES (?,?,?,?,?,?,?)''',
          ('aud-'+uuid4().hex[:16],actor.tenant_id,actor.subject,
           'finops.rate.create',payload.model_id,iso(utc_now()),
           __import__('json').dumps({'provider':payload.provider,'valid_from':start,
                                     'input_rate':payload.input_usd_per_million,
                                     'output_rate':payload.output_usd_per_million})))
    return {'recorded':True,'classification':'configured_estimate_only','billed_cost':'Not tracked'}

@router.get('/rates')
def rates(request:Request):
    actor=require(request,'finops.estimates.view')
    with connection() as db:
        return [dict(r) for r in db.execute('SELECT * FROM finops_rate_cards WHERE tenant_id=? ORDER BY provider,model_id,valid_from DESC',(actor.tenant_id,))]

def _estimate(db, record):
    # Model identity is not enough: exact provider/model, effective rate and BOTH
    # token counts must be available. No implicit provider price or USD=0 assumption.
    if record['model_id'] is None or record['input_tokens'] is None or record['output_tokens'] is None:
        return None
    price=db.execute('''SELECT input_usd_per_million,output_usd_per_million FROM finops_rate_cards
      WHERE tenant_id=? AND provider=? AND model_id=? AND valid_from<=?
        AND (valid_until IS NULL OR valid_until>?)''',
        (record['tenant_id'],record['source'],record['model_id'],record['occurred_at'],record['occurred_at'])).fetchone()
    if not price: return None
    return (Decimal(record['input_tokens'])*Decimal(price['input_usd_per_million'])+
            Decimal(record['output_tokens'])*Decimal(price['output_usd_per_million']))/Decimal(1000000)

def _visible_finops_agent(db,actor,agent_id):
    if not _visible_agent(db,actor,agent_id):
        return False
    if rbac.normalized_role(actor.role)=='business_owner':
        user_id=actor.subject.removeprefix('local-user:')
        return db.execute('SELECT 1 FROM agent_governance WHERE tenant_id=? AND agent_id=? AND business_owner_user_id=?',
                          (actor.tenant_id,agent_id,user_id)).fetchone() is not None
    return True

@router.get('/summary')
def summary(request:Request, period:str=Query('30d',pattern=r'^(24h|7d|30d|all)$'),agent_id:str|None=None):
    actor=require(request,'finops.usage.view')
    since=_period_start(period)
    with connection() as db:
        rows=[dict(r) for r in db.execute('''SELECT * FROM finops_usage WHERE tenant_id=? AND (? IS NULL OR agent_id=?) AND (? IS NULL OR occurred_at>=?) ORDER BY occurred_at DESC''',
            (actor.tenant_id,agent_id,agent_id,since,since)) if _visible_finops_agent(db,actor,r['agent_id'])]
        names={r['id']:r['name'] for table in ('agents','discovered_agents') for r in db.execute(f'SELECT id,name FROM {table} WHERE tenant_id=?',(actor.tenant_id,))}
        approvals={r['agent_id']:dict(r) for r in db.execute(
            'SELECT agent_id,approval_status,requested_budget_usd,requested_cost_center FROM agent_governance WHERE tenant_id=?',(actor.tenant_id,))}
        groups={}
        estimated_total=Decimal(0)
        estimated_count=0
        for row in rows:
            cost=_estimate(db,row) if 'finops.estimates.view' in (actor.capabilities if actor.capabilities is not None else rbac.effective_capabilities(actor.role)) else None
            if cost is not None:
                estimated_total+=cost;estimated_count+=1
            group=groups.setdefault(row['agent_id'],{'agent_id':row['agent_id'],'name':names.get(row['agent_id'],row['agent_id']),
                'operations':0,'input_tokens_observed':0,'output_tokens_observed':0,'input_samples':0,'output_samples':0,
                'estimated_usd':Decimal(0),'estimated_operations':0})
            group['operations']+=1
            for key in ('input','output'):
                if row[key+'_tokens'] is not None:
                    group[key+'_tokens_observed']+=row[key+'_tokens'];group[key+'_samples']+=1
            if cost is not None:group['estimated_usd']+=cost;group['estimated_operations']+=1
        result=[]
        for g in groups.values():
            g['estimated_usd']=str(g['estimated_usd'].quantize(Decimal('.000001'))) if g['estimated_operations'] else None
            record=approvals.get(g['agent_id']) if 'finops.estimates.view' in (actor.capabilities if actor.capabilities is not None else rbac.effective_capabilities(actor.role)) else None
            g['approved_monthly_budget_usd']=record['requested_budget_usd'] if record and record['approval_status']=='approved' else None
            g['cost_center']=record['requested_cost_center'] if record and record['approval_status']=='approved' else None
            # A partial estimate cannot establish budget adherence; never flag compliant.
            g['budget_comparison']='Partial estimate — cannot verify budget' if g['approved_monthly_budget_usd'] is not None and g['estimated_usd'] is not None else 'Not tracked'
            result.append(g)
        return {'period':period,'usage_operations':len(rows),'agent_count':len(groups),
          'input_tokens_observed':sum(r['input_tokens'] for r in rows if r['input_tokens'] is not None),
          'output_tokens_observed':sum(r['output_tokens'] for r in rows if r['output_tokens'] is not None),
          'input_token_samples':sum(r['input_tokens'] is not None for r in rows),
          'output_token_samples':sum(r['output_tokens'] is not None for r in rows),
          'estimated_usd':str(estimated_total.quantize(Decimal('.000001'))) if estimated_count else None,
          'estimated_operations':estimated_count,'billed_usd':None,'billed_status':'Not tracked',
          'estimation_status':'Partial' if 0<estimated_count<len(rows) else ('Estimated' if estimated_count else 'Not tracked'),
          'by_agent':sorted(result,key=lambda r:(-r['operations'],r['name'])),
          'notice':'Token telemetry is observed; rate-based costs are estimates, never Azure invoice charges.'}
