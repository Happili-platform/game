# SPDX-License-Identifier: AGPL-3.0-only
"""No Azure access required: bounded window subdivision and fail-closed behavior."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'collect_azure_foundry.py'
spec = importlib.util.spec_from_file_location('azure_collector_035', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
T0 = datetime(2026, 11, 11, tzinfo=timezone.utc)


def test_saturated_windows_subdivide_without_duplicate_boundary(monkeypatch):
    timestamps = [T0 + timedelta(seconds=i) for i in range(8)]
    calls = []
    def mock_query(_client, _workspace, _token, _table, since, until, max_rows):
        calls.append((since, until))
        matching = [ts for ts in timestamps if since <= ts < until]
        return matching[:max_rows], 'ok'
    monkeypatch.setattr(mod, 'query_table', mock_query)
    rows, status, meta = mod.query_complete_window(None, 'ws', 'token', 'AppRequests',
                                                   T0, T0 + timedelta(seconds=10), 3)
    assert status == 'ok'
    assert rows == timestamps
    assert meta['splits'] > 0 and meta['queries'] == len(calls)
    assert all(start < end for start, end in calls)


def test_saturated_one_second_fails_closed(monkeypatch):
    def saturated(*args):
        return [1, 2], 'ok'
    monkeypatch.setattr(mod, 'query_table', saturated)
    with pytest.raises(RuntimeError, match='one second'):
        mod.query_complete_window(None, 'ws', 'token', 'AppRequests',
                                  T0, T0 + timedelta(seconds=1), 2)


def test_query_budget_fails_closed(monkeypatch):
    monkeypatch.setattr(mod, 'query_table', lambda *args: ([1, 2], 'ok'))
    with pytest.raises(RuntimeError, match='budget exceeded'):
        mod.query_complete_window(None, 'ws', 'token', 'AppRequests',
                                  T0, T0 + timedelta(seconds=100), 2, max_requests=3)


def test_missing_table_is_not_split(monkeypatch):
    monkeypatch.setattr(mod, 'query_table', lambda *args: ([], 'table_missing'))
    rows, status, info = mod.query_complete_window(None, 'ws', 'token', 'AppRequests',
                                                    T0, T0 + timedelta(minutes=60), 2)
    assert rows == [] and status == 'table_missing' and info['queries'] == 1


def test_error_during_subdivision_propagates(monkeypatch):
    def query(_client, _workspace, _token, _table, start, end, cap):
        if start == T0 and end == T0 + timedelta(seconds=8):
            return [1, 2], 'ok'
        raise RuntimeError('remote query unavailable')
    monkeypatch.setattr(mod, 'query_table', query)
    with pytest.raises(RuntimeError, match='remote query unavailable'):
        mod.query_complete_window(None, 'ws', 'token', 'AppRequests',
                                  T0, T0 + timedelta(seconds=8), 2)
