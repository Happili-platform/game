#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Read-only Azure Application Insights -> GAME runtime bridge.

No prompt/body/content is exported. Only explicitly attributed traces are ingested.
Uses public Azure Monitor Logs Query API and Azure CLI or workload credentials.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import httpx

LOGS_URL = 'https://api.loganalytics.azure.com/v1/workspaces/{workspace}/query'
TOKEN_SCOPE = 'https://api.loganalytics.io/.default'
HEX_TRACE = re.compile(r'^[a-fA-F0-9]{32}$')
HEX_SPAN = re.compile(r'^[a-fA-F0-9]{16}$')
GUID = re.compile(r'^[0-9a-fA-F-]{36}$')
# Fetch only the minimal columns needed, excluding body, result, and message data.
# Avoid querying AppTraces (which can contain prompts and model content).
TABLES = ('AppRequests', 'AppDependencies')
FIELDS = ('TimeGenerated', 'OperationId', 'Id', 'ParentId', 'Name',
          'DurationMs', 'Success', 'ResultCode', 'Properties')
ATTR_KEYS = ('gen_ai.agent.id', 'gen_ai.agent.name', 'agent.id', 'agent.name',
             'gen_ai.agent_id', 'gen_ai.agent_name')


def timestamp(value):
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Azure timestamp has no timezone')
    return result.astimezone(timezone.utc)


def ts(value):
    return value.isoformat(timespec='microseconds').replace('+00:00', 'Z')


def flatten(data):
    """Keep only the six allowlisted agent-identity keys, not original attributes."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            return {}
    if not isinstance(data, dict):
        return {}
    return {str(k).lower(): str(v) for k, v in data.items()
            if str(k).lower() in ATTR_KEYS and isinstance(v, (str, int)) and v is not None}


def identity(row):
    return set(flatten(row.get('Properties')).values())


def span_id(raw, trace_id):
    """Use genuine Azure hex span ID; otherwise use a stable *derived* local ID."""
    value = str(raw or '').lower()
    if HEX_SPAN.fullmatch(value):
        return value
    return hashlib.sha256((trace_id + ':' + value).encode()).hexdigest()[:16]


def safe_kind(row):
    name = str(row.get('Name') or '').lower()
    typ = str(row.get('_table') or '')
    if 'mcp' in name:
        return 'mcp'
    if 'tool' in name or 'function' in name:
        return 'tool'
    if any(word in name for word in ('chat', 'model', 'completion', 'embeddings')):
        return 'model'
    if typ == 'AppRequests':
        return 'agent'
    return 'other'


def safe_name(row, kind):
    # Do not trust provider operation names, which may contain user input or URLs.
    # Generic labels retain operation class but cannot leak prompts/tool arguments.
    return {'agent': 'Foundry agent execution', 'model': 'Model operation',
            'tool': 'Tool operation', 'mcp': 'MCP operation',
            'other': 'Dependency operation'}[kind]


def outcome(row):
    val = row.get('Success')
    if val is True or (isinstance(val, str) and val.lower() == 'true'):
        return 'success'
    if val is False or (isinstance(val, str) and val.lower() == 'false'):
        return 'failure'
    # Azure requests may omit Success while reporting a numeric HTTP result.
    # Do not infer an overall agent outcome from a dependency/tool result.
    if row.get('_table') == 'AppRequests':
        code = str(row.get('ResultCode') or '').strip()
        if code.isdecimal():
            number = int(code)
            if 200 <= number < 400:
                return 'success'
            if 400 <= number < 600:
                return 'failure'
    return 'unknown'


def duration(row):
    value = row.get('DurationMs')
    if value is None or value == '':
        return None
    try:
        num = float(value)
        return num if 0 <= num < 1e10 else None
    except (ValueError, TypeError):
        return None


def normalize(rows, mapping):
    """Return payloads plus summarized diagnostics. Never guess attribution."""
    groups = defaultdict(list)
    for row in rows:
        trace = str(row.get('OperationId') or '').lower()
        if HEX_TRACE.fullmatch(trace):
            groups[trace].append(row)
    results = []
    diagnostics = {'traces_seen': len(groups), 'unattributed': 0,
                   'ambiguous': 0, 'invalid_timestamps': 0, 'eligible': 0}
    for trace, items in sorted(groups.items()):
        evidence = set().union(*(identity(row) for row in items))
        known_ids = {mapping[k] for k in evidence if k in mapping}
        if len(known_ids) == 0:
            diagnostics['unattributed'] += 1
            continue
        if len(known_ids) > 1:
            diagnostics['ambiguous'] += 1
            continue
        agent_id = next(iter(known_ids))
        prepared = []
        try:
            for item in items:
                started = timestamp(item['TimeGenerated'])
                ms = duration(item)
                ended = started + timedelta(milliseconds=ms) if ms is not None else None
                prepared.append((started, ended, item))
        except (KeyError, TypeError, ValueError, OverflowError):
            diagnostics['invalid_timestamps'] += 1
            continue
        prepared.sort(key=lambda r: r[0])
        # A request span is the most reliable execution root. If only
        # dependencies are present, do not fabricate a run-level outcome.
        roots = [r for r in prepared if r[2].get('_table') == 'AppRequests']
        run_start = min(r[0] for r in (roots or prepared))
        run_end = max((r[1] for r in (roots or prepared) if r[1]), default=None)
        if len(roots) == 1:
            run_status = outcome(roots[0][2])
        elif roots and any(outcome(r[2]) == 'failure' for r in roots):
            run_status = 'failure'
        else:
            run_status = 'unknown'
        # Emit only spans with a real source ID. Derived span IDs are expressly
        # local correlation identifiers, never claimed to be Azure span IDs.
        spans = []
        seen = set()
        for start, end, row in prepared:
            raw_id = row.get('Id')
            if not raw_id:
                continue
            sid = span_id(raw_id, trace)
            if sid in seen:
                continue
            seen.add(sid)
            parent = row.get('ParentId')
            pid = span_id(parent, trace) if parent else None
            if pid == sid:
                pid = None
            kind = safe_kind(row)
            spans.append({'span_id': sid, 'parent_span_id': pid, 'trace_id': trace,
                          'kind': kind, 'name': safe_name(row, kind),
                          'status': outcome(row), 'started_at': ts(start),
                          'ended_at': ts(end) if end else None})
            if len(spans) == 100:
                break
        results.append({'agent_id': agent_id, 'source': 'azure_foundry_logs',
                        'external_run_id': trace, 'trace_id': trace,
                        'status': run_status, 'started_at': ts(run_start),
                        'ended_at': ts(run_end) if run_end else None,
                        'spans': spans})
        diagnostics['eligible'] += 1
    return results, diagnostics


# Accept only standardized aggregate token counts on model dependency spans.
# Do not ingest AppTraces, prompts, responses, per-message or tool arguments.
USAGE_KEYS = ('gen_ai.usage.input_tokens', 'gen_ai.usage.output_tokens',
              'gen_ai.response.model', 'gen_ai.request.model')

def _usage_attrs(raw):
    if isinstance(raw, str):
        try: raw=json.loads(raw)
        except (ValueError, TypeError): return {}
    if not isinstance(raw, dict): return {}
    return {k:raw[k] for k in USAGE_KEYS if k in raw}

def _token_count(value):
    if type(value) is int and 0 <= value <= 1000000000: return value
    if isinstance(value,str) and value.isdecimal():
        number=int(value)
        if number<=1000000000: return number
    return None

def usage_from_traces(rows, payloads):
    """Per-model-operation usage only; avoid request-level rolled-up double counts."""
    allowed={p['trace_id']:p for p in payloads}
    results=[]
    seen=set()
    for row in rows:
        trace=str(row.get('OperationId') or '').lower()
        if trace not in allowed or row.get('_table')!='AppDependencies': continue
        attrs=_usage_attrs(row.get('Properties'))
        inp=_token_count(attrs.get('gen_ai.usage.input_tokens'))
        out=_token_count(attrs.get('gen_ai.usage.output_tokens'))
        if inp is None and out is None: continue
        model=attrs.get('gen_ai.response.model') or attrs.get('gen_ai.request.model')
        if not isinstance(model,str) or not re.fullmatch(r'[A-Za-z0-9._:/@+\-]{1,140}',model): model=None
        raw_id=row.get('Id')
        if not raw_id: continue # Without a distinct operation identity, cannot deduplicate safely.
        operation=span_id(raw_id,trace)
        if (trace,operation) in seen: continue
        seen.add((trace,operation))
        try: occurred=ts(timestamp(row['TimeGenerated']))
        except (KeyError,ValueError,TypeError): continue
        run=allowed[trace]
        results.append({'agent_id':run['agent_id'],'source':run['source'],
                        'external_run_id':run['external_run_id'],'operation_id':operation,
                        'occurred_at':occurred,'model_id':model,'input_tokens':inp,
                        'output_tokens':out,'evidence':'azure_appinsights_genai_attributes'})
    return results


def cli_token():
    try:
        proc = subprocess.run(['az', 'account', 'get-access-token',
                               '--resource', 'https://api.loganalytics.io',
                               '--query', 'accessToken', '-o', 'tsv'],
                              capture_output=True, text=True, check=True, timeout=30)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Azure CLI login is required: run az login and select the correct subscription') from exc
    return proc.stdout.strip()


def service_token(client):
    tenant = os.getenv('AZURE_TENANT_ID', '')
    app = os.getenv('AZURE_CLIENT_ID', '')
    secret = os.getenv('AZURE_CLIENT_SECRET', '')
    if not all((tenant, app, secret)):
        raise RuntimeError('Missing AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET')
    response = client.post('https://login.microsoftonline.com/' + tenant + '/oauth2/v2.0/token',
                           data={'grant_type': 'client_credentials', 'client_id': app,
                                 'client_secret': secret, 'scope': TOKEN_SCOPE})
    response.raise_for_status()
    return response.json()['access_token']


def query_table(client, workspace, token, table, since, until, max_rows):
    if table not in TABLES:
        raise ValueError('Unexpected table')
    # Datetimes are generated in-process, never from arbitrary KQL strings.
    project = ', '.join(f'{f}=column_ifexists("{f}", "")' for f in FIELDS)
    kql = (f'{table} | where TimeGenerated >= datetime({ts(since)}) '
           f'and TimeGenerated < datetime({ts(until)}) '
           f'| project {project} | order by TimeGenerated asc | take {max_rows}')
    response = client.post(LOGS_URL.format(workspace=workspace),
                           headers={'Authorization': 'Bearer ' + token},
                           json={'query': kql}, timeout=50)
    if response.status_code == 400 and ('Failed to resolve table' in response.text or
                                        'does not refer to any known' in response.text):
        return [], 'table_missing'
    response.raise_for_status()
    data = response.json()
    if 'error' in data:
        raise RuntimeError('Azure query returned an error: ' + str(data['error'].get('code', 'unknown')))
    rows = []
    for result in data.get('tables', []):
        columns = [c['name'] for c in result.get('columns', [])]
        for values in result.get('rows', []):
            row = dict(zip(columns, values))
            row['_table'] = table
            rows.append(row)
    return rows, 'ok'


def query_complete_window(client, workspace, token, table, since, until, max_rows,
                          *, max_requests=128):
    """Fetch a complete Azure metadata window, splitting saturated time ranges.

    Azure's ``take N`` can otherwise truncate the window at its query cap.
    No rows are returned to the caller until *every* subrange has completed.
    The bounded request budget fails closed if a burst cannot be retrieved.
    """
    if since >= until:
        raise ValueError('Collection time window must be positive')
    requests = 0
    splits = 0

    def fetch(start, end):
        nonlocal requests, splits
        if requests >= max_requests:
            raise RuntimeError(f'{table} query subdivision budget exceeded; narrow the lookback window')
        requests += 1
        rows, state = query_table(client, workspace, token, table, start, end, max_rows)
        if state == 'table_missing':
            return [], state
        if len(rows) < max_rows:
            return rows, state
        # Half-open intervals prevent boundary duplication. Do not accept any
        # saturated final leaf: a complete time slice cannot be guaranteed.
        if (end - start).total_seconds() <= 1:
            raise RuntimeError(f'{table} has >= {max_rows} records in one second; cannot safely collect all rows')
        midpoint = start + (end - start) / 2
        splits += 1
        left, left_state = fetch(start, midpoint)
        right, right_state = fetch(midpoint, end)
        if left_state != 'ok' or right_state != 'ok':
            raise RuntimeError(f'{table} became unavailable during window subdivision')
        return left + right, 'ok'

    rows, state = fetch(since, until)
    return rows, state, {'queries': requests, 'splits': splits}


def read_mapping(path):
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or not data:
        raise ValueError('mapping JSON must be a nonempty object of exact Azure agent ID -> GAME ID')
    if any(not isinstance(k, str) or not k.strip() or not isinstance(v, str) or not v.strip()
           for k, v in data.items()):
        raise ValueError('mapping values must be nonempty strings')
    return data



def automatic_mapping(agents):
    """Unique provider identities only; never guess across project collisions.

    Foundry may expose either `agent-id:version` or `agent-name` in trace
    attributes. All aliases are conditional on global uniqueness across the
    connected Foundry projects. No version number is fabricated.
    """
    candidates = defaultdict(set)
    for item in agents:
        internal_id = item.get('id')
        if not isinstance(internal_id,str) or not internal_id:
            continue
        for key in ('external_id','name'):
            value = item.get(key)
            if isinstance(value,str) and value.strip():
                candidates[value.strip()].add(internal_id)
                # Versioned IDs can appear as name:1 in telemetry, or simply
                # name in discovery. Only remove a strictly numeric suffix.
                if key == 'external_id' and re.search(r':\d+$',value):
                    candidates[re.sub(r':\d+$','',value)].add(internal_id)
    mapping = {alias:next(iter(ids)) for alias,ids in candidates.items() if len(ids)==1}
    return mapping, {'collisions':sum(len(ids)>1 for ids in candidates.values())}


def collect(args):
    mapping = None
    if args.mapping:
        mapping = read_mapping(args.mapping)
    else:
        ingest_token = os.getenv('GAME_RUNTIME_INGEST_TOKEN', '')
        if len(ingest_token) < 32:
            raise RuntimeError('GAME_RUNTIME_INGEST_TOKEN required for automatic mapping')
        with httpx.Client(timeout=60, trust_env=True) as identity_client:
            base_url = args.game_url.rstrip('/')
            headers = {'X-GAME-Ingest-Token': ingest_token}

            readiness = identity_client.get(
                base_url + '/api/runtime/azure-inventory-ready',
                headers=headers)
            readiness.raise_for_status()

            if readiness.json().get('configured') is not True:
                print('Microsoft Foundry is not configured; '
                      'Azure inventory synchronization skipped.')
                return 0

            response = identity_client.post(
                base_url + '/api/runtime/azure-inventory-sync',
                headers=headers)
            response.raise_for_status()
            inventory = response.json()['agents']
            mapping, diagnostics = automatic_mapping(inventory)
            print('Foundry inventory:', len(inventory), 'agents; mapped identities:',
                  len(mapping), '; identity collisions:', diagnostics['collisions'])
    until = datetime.now(timezone.utc) - timedelta(minutes=args.lag_minutes)
    since = until - timedelta(minutes=args.lookback_minutes)
    with httpx.Client(timeout=55, trust_env=True) as client:
        token = cli_token() if args.auth == 'az-cli' else service_token(client)
        rows = []
        for table in TABLES:
            chunk, state, query_stats = query_complete_window(
                client, args.workspace, token, table, since, until,
                args.max_rows_per_table)
            if state == 'table_missing':
                print(f'INFO: {table} is absent; skipped', file=sys.stderr)
            if query_stats['splits']:
                print(f'INFO: {table} automatically split into complete time windows '
                      f'({query_stats["queries"]} queries, {query_stats["splits"]} splits)')
            rows.extend(chunk)
        payloads, stats = normalize(rows, mapping)
        print('Azure query:', len(rows), 'metadata rows,', stats['traces_seen'], 'trace groups')
        print('Attribution:', stats['eligible'], 'eligible,', stats['unattributed'], 'unattributed,',
              stats['ambiguous'], 'ambiguous,', stats['invalid_timestamps'], 'invalid timestamps')
        usages = usage_from_traces(rows, payloads)
        print('Observed model usage operations:', len(usages), '(no pricing inferred)')
        if args.dry_run:
            for payload in payloads:
                print('DRY RUN:', payload['agent_id'], payload['trace_id'],
                      payload['status'], len(payload['spans']), 'spans')
            print('No telemetry imported (dry run).')
            return 0
        ingest_token = os.getenv('GAME_RUNTIME_INGEST_TOKEN', '')
        if len(ingest_token) < 32:
            raise RuntimeError('GAME_RUNTIME_INGEST_TOKEN must match running GAME (32+ chars)')
        imported = replayed = 0
        for payload in payloads:
            response = client.post(args.game_url.rstrip('/') + '/api/runtime/ingest',
                                   headers={'X-GAME-Ingest-Token': ingest_token}, json=payload)
            if response.status_code != 201:
                # Don't dump response body; Azure or proxy errors could include sensitive data.
                print('ERROR: import failed:', response.status_code, payload['trace_id'], file=sys.stderr)
                continue
            result = response.json()
            imported += not result.get('replayed')
            replayed += bool(result.get('replayed'))
        failed = len(payloads)-imported-replayed
        # Do not submit usage if the corresponding run failed or is missing;
        # endpoint verifies matching run, preventing orphan financial records.
        usage_imported=usage_replayed=usage_failed=0
        if not failed:
            for usage in usages:
                response=client.post(args.game_url.rstrip('/')+'/api/finops/usage/ingest',
                    headers={'X-GAME-Ingest-Token':ingest_token},json=usage)
                if response.status_code!=201:
                    print('ERROR: usage import failed:', response.status_code, usage['external_run_id'], file=sys.stderr)
                    usage_failed+=1
                elif response.json().get('replayed'): usage_replayed+=1
                else: usage_imported+=1
        print('Model usage: Imported:',usage_imported,'| Replayed:',usage_replayed,'| Failed:',usage_failed)
        failed+=usage_failed
        print('Imported:', imported, '| Replayed:', replayed, '| Failed:', failed)
        if not failed:
            # Even a quiet successful query is a successful collection. This
            # separate heartbeat makes 'no agent activity' distinguishable from
            # a collector outage. No identities, secrets or prompts are stored.
            health = client.post(args.game_url.rstrip('/') + '/api/runtime/collection-status',
                headers={'X-GAME-Ingest-Token': ingest_token},
                json={'source': 'azure_foundry_logs', 'metadata_rows': len(rows),
                      'trace_groups': stats['traces_seen'], 'eligible': stats['eligible'],
                      'imported': imported, 'replayed': replayed, 'failed': failed,
                      'window_start': ts(since), 'window_end': ts(until)})
            if health.status_code != 201:
                print('ERROR: collection health update failed:', health.status_code, file=sys.stderr)
                return 2
        return 0 if failed == 0 else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, help='Log Analytics workspace GUID (not App Insights resource name)')
    parser.add_argument('--mapping', help='Optional legacy manual override. Omit for automatic Foundry discovery and mapping')
    parser.add_argument('--auth', choices=('az-cli', 'service-principal'), default='az-cli')
    parser.add_argument('--lookback-minutes', type=int, default=60)
    parser.add_argument('--lag-minutes', type=int, default=5, help='Allow Azure ingestion delay')
    parser.add_argument('--max-rows-per-table', type=int, default=2000)
    parser.add_argument('--game-url', default='http://127.0.0.1:8000')
    parser.add_argument('--dry-run', action='store_true', help='Analyze attribution only; do not import')
    args = parser.parse_args(argv)
    if not GUID.fullmatch(args.workspace):
        parser.error('workspace must be a GUID')
    if not (5 <= args.lookback_minutes <= 1440 and 0 <= args.lag_minutes <= 60):
        parser.error('lookback must be 5..1440 minutes and lag must be 0..60 minutes')
    if not (10 <= args.max_rows_per_table <= 10000):
        parser.error('max rows must be 10..10000')
    if args.game_url.rstrip('/') != 'http://127.0.0.1:8000':
        parser.error('collector only supports GAME at http://127.0.0.1:8000')
    try:
        return collect(args)
    except (ValueError, RuntimeError, httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
        print('Collector error:', str(exc)[:250], file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
