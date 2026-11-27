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
