# SPDX-License-Identifier: AGPL-3.0-only
"""Verify safe database startup without touching operational data."""

import pytest

from game.db import require_existing_runtime_database


def test_missing_database_configuration_rejected(monkeypatch):
    monkeypatch.delenv("GAME_DB_PATH", raising=False)

    with pytest.raises(RuntimeError, match="explicitly configured"):
        require_existing_runtime_database()


def test_missing_database_file_rejected(monkeypatch, tmp_path):
    missing = tmp_path / "missing.db"
    monkeypatch.delenv("GAME_TESTING", raising=False)
    monkeypatch.setenv("GAME_DB_PATH", str(missing))

    with pytest.raises(RuntimeError, match="does not exist"):
        require_existing_runtime_database()

    assert not missing.exists()


def test_existing_database_accepted(monkeypatch, tmp_path):
    database = tmp_path / "test.db"
    database.touch()

    monkeypatch.setenv("GAME_DB_PATH", str(database))

    assert require_existing_runtime_database() == database


def test_testing_mode_allows_new_isolated_database(
    monkeypatch, tmp_path
):
    new_database = tmp_path / "isolated-test.db"

    monkeypatch.setenv("GAME_TESTING", "true")
    monkeypatch.setenv("GAME_DB_PATH", str(new_database))

    assert require_existing_runtime_database() == new_database
    assert not new_database.exists()


def test_production_mode_rejects_missing_database(
    monkeypatch, tmp_path
):
    missing = tmp_path / "production.db"

    monkeypatch.delenv("GAME_TESTING", raising=False)
    monkeypatch.setenv("GAME_DB_PATH", str(missing))

    with pytest.raises(RuntimeError, match="does not exist"):
        require_existing_runtime_database()

    assert not missing.exists()
