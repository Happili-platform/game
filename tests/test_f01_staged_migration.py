# SPDX-License-Identifier: AGPL-3.0-only
"""Verify F01 staging never upgrades the source database."""

import sqlite3
from pathlib import Path

import pytest

from game.db import connection, initialize
from game.identity import initialize_identity_schema
from scripts.f01_prepare_migration import prepare


@pytest.fixture
def source_database(tmp_path, monkeypatch):
    source = tmp_path / "original.db"

    monkeypatch.setenv("GAME_DB_PATH", str(source))
    monkeypatch.setenv("GAME_DEMO_DATA", "false")

    initialize()

    with connection() as db:
        db.execute("""
    INSERT INTO agents (
        id, name, provider,
        environment, approval_status, lifecycle_status,
        created_at, tenant_id
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
""", (
    "legacy-one",
    "Historical Agent",
    "Test Provider",
    "development",
    "pending",
    "active",
    "2026-11-27",
    "local-dev",
))

    return source


def test_prepare_creates_upgraded_copy_only(
    source_database, tmp_path
):
    staged = tmp_path / "staged.db"

    result = prepare(source_database, staged)

    assert result["first"]["created"] == 1
    assert result["second"]["created"] == 0
    assert result["integrity"] == "ok"
    assert staged.exists()

    with sqlite3.connect(source_database) as original:
        tables = {
            row[0] for row in original.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table'"
            )
        }

        assert "canonical_agents" not in tables
        assert original.execute(
            "SELECT COUNT(*) FROM agents"
        ).fetchone()[0] == 1

    with sqlite3.connect(staged) as upgraded:
        assert upgraded.execute(
            "SELECT COUNT(*) FROM canonical_agents"
        ).fetchone()[0] == 1

        assert upgraded.execute(
            "SELECT COUNT(*) FROM agent_legacy_references"
        ).fetchone()[0] == 1


def test_prepare_refuses_source_overwrite(source_database):
    with pytest.raises(ValueError):
        prepare(source_database, source_database)


def test_prepare_refuses_existing_output(
    source_database, tmp_path
):
    output = tmp_path / "existing.db"
    output.write_bytes(b"DO NOT OVERWRITE")

    with pytest.raises(FileExistsError):
        prepare(source_database, output)

    assert output.read_bytes() == b"DO NOT OVERWRITE"


def test_f01_simulated_cutover_and_rollback(source_database, tmp_path):
    """Exercise migration and recovery using temporary files only."""
    import os
    from contextlib import closing

    recovery = tmp_path / "recovery.db"
    staged = tmp_path / "upgraded.db"

    # Snapshot the original temporary database consistently.
    with closing(sqlite3.connect(source_database)) as src:
        with closing(sqlite3.connect(recovery)) as dst:
            src.backup(dst)

    def snapshot(path):
        with closing(sqlite3.connect(path)) as db:
            tables = {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            agents = db.execute(
                "SELECT * FROM agents ORDER BY id"
            ).fetchall()
            discovered = db.execute(
                "SELECT * FROM discovered_agents ORDER BY id"
            ).fetchall()
            return tables, agents, discovered

    original = snapshot(source_database)
    assert "canonical_agents" not in original[0]

    # Prepare and validate the upgraded copy.
    result = prepare(source_database, staged)
    assert result["integrity"] == "ok"
    assert result["foreign_key_violations"] == 0

    # SIMULATION ONLY: source_database is inside pytest's tmp_path.
    os.replace(staged, source_database)

    upgraded = snapshot(source_database)
    assert "canonical_agents" in upgraded[0]
    assert upgraded[1:] == original[1:]

    # Simulate deployment failure and restore the recovery copy.
    os.replace(recovery, source_database)

    restored = snapshot(source_database)
    assert restored == original
    assert "canonical_agents" not in restored[0]

    with closing(sqlite3.connect(source_database)) as db:
        assert db.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok"
        assert db.execute(
            "PRAGMA foreign_key_check"
        ).fetchall() == []


def test_f01_failed_preparation_keeps_original_unchanged(tmp_path):
    """An invalid source must not leave a staged output behind."""
    import hashlib
    from contextlib import closing

    source = tmp_path / "incomplete.db"
    output = tmp_path / "invalid-upgrade.db"

    with closing(sqlite3.connect(source)) as db:
        db.execute(
            "CREATE TABLE agents (id TEXT PRIMARY KEY)"
        )
        db.commit()

    before = hashlib.sha256(source.read_bytes()).hexdigest()

    with pytest.raises(sqlite3.OperationalError):
        prepare(source, output)

    after = hashlib.sha256(source.read_bytes()).hexdigest()

    assert before == after
    assert not output.exists()
