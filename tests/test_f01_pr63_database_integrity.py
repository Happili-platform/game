# SPDX-License-Identifier: AGPL-3.0-only
"""PR #63: SQLite migration and startup safety regressions."""

import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from game.db import db_path, require_existing_runtime_database
from game.main import app
from scripts.f01_prepare_migration import prepare


def test_database_path_expands_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    database = tmp_path / "game.db"
    database.touch()

    monkeypatch.setenv("GAME_DB_PATH", "~/game.db")
    monkeypatch.setenv("GAME_TESTING", "false")

    assert db_path() == database
    assert require_existing_runtime_database() == database


def test_uppercase_password_mode_rejects_missing_database(
    monkeypatch, tmp_path
):
    missing = tmp_path / "must-not-create.db"

    monkeypatch.setenv("GAME_AUTH_MODE", "PASSWORD")
    monkeypatch.setenv("GAME_TESTING", "false")
    monkeypatch.setenv("GAME_DB_PATH", str(missing))

    with pytest.raises(RuntimeError, match="does not exist"):
        with TestClient(app):
            pass

    assert not missing.exists()


def test_wal_migration_produces_standalone_identity_database(
    tmp_path, monkeypatch
):
    from game.db import initialize

    original = tmp_path / "source.db"
    staged = tmp_path / "staged.db"

    monkeypatch.setenv("GAME_DB_PATH", str(original))
    monkeypatch.setenv("GAME_DEMO_DATA", "false")

    initialize()

    with closing(sqlite3.connect(original)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""
            INSERT INTO agents (
                id, name, provider, environment,
                approval_status, lifecycle_status,
                created_at, tenant_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "wal-agent", "WAL Agent", "Test",
            "development", "pending", "active",
            "2026-11-27", "local-dev",
        ))
        db.commit()

    result = prepare(original, staged)

    assert result["integrity"] == "ok"
    assert result["first"]["created"] == 1
    assert not (tmp_path / "staged.db-wal").exists()

    # Immutable access deliberately ignores companion WAL files.
    # This verifies the standalone .db contains the migrated data.
    uri = staged.resolve().as_uri() + "?immutable=1"

    with closing(sqlite3.connect(uri, uri=True)) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM canonical_agents"
        ).fetchone()[0] == 1

        assert db.execute(
            "SELECT COUNT(*) FROM agent_legacy_references"
        ).fetchone()[0] == 1

        assert db.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok"
