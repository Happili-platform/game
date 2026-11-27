# SPDX-License-Identifier: AGPL-3.0-only
"""F01: Validate migrations on a disposable database backup."""

import hashlib
import sqlite3

import pytest

from game.db import connection, initialize
from game.identity import (
    initialize_identity_schema,
    backfill_legacy_references,
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def database_copy(tmp_path, monkeypatch):
    original = tmp_path / "original.db"
    backup = tmp_path / "migration-test.db"

    monkeypatch.setenv("GAME_DB_PATH", str(original))
    monkeypatch.setenv("GAME_DEMO_DATA", "false")
    initialize()

    with connection() as db:
        db.execute("""
            INSERT INTO provider_connections
            (id, provider, label, scope_json, env_prefix,
             created_at, tenant_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "conn-test", "google_agent_engine",
            "Migration Test", '{"project_id":"sample-project",'
            '"location":"us-central1"}',
            "GAME_GOOGLE", "2026-11-27", "local-dev",
        ))

        db.execute("""
            INSERT INTO discovered_agents
            (id, connection_id, external_id, name, provider,
             discovered_at, discovery_last_seen,
             created_at, tenant_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "ext-existing", "conn-test", "agent-123",
            "Historical Agent", "Google Agent Engine",
            "2026-11-27", "2026-11-27",
            "2026-11-27", "local-dev",
        ))

    # SQLite's online backup API creates a consistent copy.
    with sqlite3.connect(original) as src:
        with sqlite3.connect(backup) as dst:
            src.backup(dst)

    return original, backup


def migrate_copy(path):
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        initialize_identity_schema(db)
        result = backfill_legacy_references(db)
        db.commit()
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
        return result, integrity, foreign_keys


def test_migration_preserves_original_database(database_copy):
    original, backup = database_copy
    before = digest(original)

    result, integrity, foreign_keys = migrate_copy(backup)

    assert result["created"] == 1
    assert integrity == "ok"
    assert foreign_keys == []
    assert digest(original) == before

    with sqlite3.connect(backup) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM canonical_agents"
        ).fetchone()[0] == 1

        assert db.execute(
            "SELECT legacy_agent_id FROM agent_legacy_references"
        ).fetchone()[0] == "ext-existing"

        assert db.execute(
            "SELECT id FROM discovered_agents"
        ).fetchone()[0] == "ext-existing"


def test_repeated_migration_does_not_duplicate_identities(database_copy):
    original, backup = database_copy

    first, _, _ = migrate_copy(backup)

    with sqlite3.connect(backup) as db:
        canonical_before = db.execute(
            "SELECT canonical_agent_id "
            "FROM agent_legacy_references "
            "WHERE legacy_agent_id='ext-existing'"
        ).fetchone()[0]

    second, integrity, foreign_keys = migrate_copy(backup)

    with sqlite3.connect(backup) as db:
        canonical_after = db.execute(
            "SELECT canonical_agent_id "
            "FROM agent_legacy_references "
            "WHERE legacy_agent_id='ext-existing'"
        ).fetchone()[0]

        assert db.execute(
            "SELECT COUNT(*) FROM canonical_agents"
        ).fetchone()[0] == 1

    assert first["created"] == 1
    assert second["created"] == 0
    assert second["existing"] == 1
    assert canonical_before == canonical_after
    assert integrity == "ok"
    assert foreign_keys == []
