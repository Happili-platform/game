# SPDX-License-Identifier: AGPL-3.0-only
"""No Azure calls, sample traces test only the adapter's decision logic."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import pytest

SRC = Path(__file__).resolve().parents[1] / 'scripts' / 'collect_azure_foundry.py'
spec = importlib.util.spec_from_file_location('foundry_collector', SRC)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
TRACE = 'a'*32
BASE = {'OperationId': TRACE, 'TimeGenerated': '2026-11-06T12:00:00Z',
        'Id': 'b'*16, 'ParentId': None, 'DurationMs': 1300,
        'Success': True, 'Name': 'user-provided sensitive stuff',
        '_table': 'AppRequests'}
MAP = {'foundry-agent-01': 'agent-a', 'foundry-agent-02': 'agent-b'}


def test_explicit_attribution_sanitization_and_metadata_only():
    rows = [dict(BASE, Properties={'gen_ai.agent.id':'foundry-agent-01', 'prompt':'secret text'})]
    payloads, stats = mod.normalize(rows, MAP)
    assert stats['eligible'] == 1
    assert payloads[0]['agent_id'] == 'agent-a'
    assert payloads[0]['source'] == 'azure_foundry_logs'
    assert payloads[0]['external_run_id'] == TRACE
    assert payloads[0]['status'] == 'success'
    assert payloads[0]['ended_at'] == '2026-11-06T12:00:01.300000Z'
    assert 'secret text' not in str(payloads)
    assert 'user-provided' not in str(payloads)
    assert payloads[0]['spans'][0]['name'] == 'Foundry agent execution'


def test_no_attribution_and_ambiguous_skip():
    rows = [dict(BASE, Properties={})]
    assert mod.normalize(rows, MAP)[0] == []
    ambiguous = [dict(BASE, Properties={'agent.id':'foundry-agent-01'}),
                 dict(BASE, Id='c'*16, Properties={'gen_ai.agent.name':'foundry-agent-02'})]
    payloads, stats = mod.normalize(ambiguous, MAP)
    assert not payloads and stats['ambiguous'] == 1


def test_partial_unknown_and_deduplicated_spans():
    rows = [dict(BASE, DurationMs=None, Success=None, Properties={'agent.id':'foundry-agent-01'}),
            dict(BASE, DurationMs=None, Success=None, Properties={}, Name='call model', _table='AppDependencies')]
    payloads, _ = mod.normalize(rows, MAP)
    assert len(payloads) == 1
    assert payloads[0]['status'] == 'unknown'
    assert payloads[0]['ended_at'] is None
    assert len(payloads[0]['spans']) == 1


def test_invalid_trace_and_timestamp_skipped():
    assert mod.normalize([dict(BASE, OperationId='not-hex', Properties={'agent.id':'foundry-agent-01'})], MAP)[0] == []
    rows = [dict(BASE, TimeGenerated='no time', Properties={'agent.id':'foundry-agent-01'})]
    assert mod.normalize(rows, MAP)[1]['invalid_timestamps'] == 1


def test_derived_ids_stable_and_safe():
    assert mod.span_id('|root.123', TRACE) == mod.span_id('|root.123', TRACE)
    assert len(mod.span_id('|root.123', TRACE)) == 16
    assert mod.span_id('B'*16, TRACE) == 'b'*16


def test_mapping_validation(tmp_path):
    cfg = tmp_path/'agents.json'
    cfg.write_text('{"foundry-agent-01":"discovered-agent-one"}')
    assert mod.read_mapping(cfg)['foundry-agent-01'] == 'discovered-agent-one'
    cfg.write_text('{"foundry-agent-01":""}')
    with pytest.raises(ValueError):
        mod.read_mapping(cfg)


def test_query_kql_restricted_and_shape():
    class FakeReply:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {'tables':[{'columns':[{'name':'OperationId'},{'name':'TimeGenerated'}],
                               'rows':[[TRACE,'2026-11-06T12:00:00Z']]}]}
    class FakeClient:
        def post(self,url,headers,json,timeout):
            assert 'api.loganalytics.azure.com/v1/workspaces/' in url
            assert 'Properties=column_ifexists' in json['query']
            assert 'AppRequests | where TimeGenerated' in json['query']
            assert 'AppTraces' not in json['query']
            assert 'take 50' in json['query']
            return FakeReply()
    rows, state = mod.query_table(FakeClient(), 'a'*36, 'token', 'AppRequests',
                                  datetime(2026,11,6,tzinfo=timezone.utc),
                                  datetime(2026,11,7,tzinfo=timezone.utc), 50)
    assert len(rows) == 1 and state == 'ok'
