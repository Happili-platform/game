# SPDX-License-Identifier: AGPL-3.0-only

import importlib.util
from pathlib import Path

import pytest

from game.db import connection
from game.local_accounts import verify_password

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "setup_community.py"


@pytest.fixture
def community(monkeypatch, tmp_path):
    database = tmp_path / "data" / "game.db"
    monkeypatch.setenv("GAME_DB_PATH", str(database))

    spec = importlib.util.spec_from_file_location(
        "community_setup", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Match the script's root validation to our isolated test path.
    module.__file__ = str(tmp_path / "scripts" / "setup_community.py")

    return module


def test_creates_three_accounts(community, monkeypatch):
    passwords = iter([
        "CommunityTestPassword-001",
        "CommunityTestPassword-001",
        "CommunityTestPassword-002",
        "CommunityTestPassword-002",
        "CommunityTestPassword-003",
        "CommunityTestPassword-003",
    ])

    monkeypatch.setattr(
        community.getpass,
        "getpass",
        lambda prompt: next(passwords)
    )

    assert community.setup() == ["coadmin", "proadmin", "bao"]

    with connection() as db:
        rows = db.execute(
            "SELECT username, role, password_hash, scope_json "
            "FROM local_users ORDER BY username"
        ).fetchall()

        assert len(rows) == 3

        accounts = {row["username"]: row for row in rows}

        assert accounts["coadmin"]["role"] == "admin"
        assert accounts["proadmin"]["role"] == "provider_admin"
        assert accounts["bao"]["role"] == "business_owner"

        assert verify_password(
            accounts["coadmin"]["password_hash"],
            "CommunityTestPassword-001"
        )

        assert '"agent_ids": []' in accounts["bao"]["scope_json"]

        assert db.execute(
            "SELECT COUNT(*) FROM provider_credentials"
        ).fetchone()[0] == 0


def test_rejects_short_password(community, monkeypatch):
    monkeypatch.setattr(
        community.getpass,
        "getpass",
        lambda prompt: "coadmin"
    )

    with pytest.raises(ValueError):
        community.setup()

    with connection() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM local_users"
        ).fetchone()[0] == 0
