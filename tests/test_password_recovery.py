# SPDX-License-Identifier: AGPL-3.0-only

import importlib.util
from pathlib import Path

import pytest

from game.db import connection, initialize
from game.local_accounts import (
    create_user,
    start_session,
    verify_password,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reset_local_password.py"

OLD_PASSWORD = "OriginalPassword-001"
NEW_PASSWORD = "RecoveryPassword-002"


@pytest.fixture
def recovery(monkeypatch, tmp_path):
    database = tmp_path / "game.db"
    monkeypatch.setenv("GAME_DB_PATH", str(database))

    initialize()
    user = create_user(
        "recoverytest",
        OLD_PASSWORD,
        "provider_admin",
        scope={
            "kind": "selected",
            "connection_ids": [],
            "agent_ids": [],
        },
    )

    spec = importlib.util.spec_from_file_location(
        "reset_local_password", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module, database, user


def test_password_reset_and_session_revocation(
    recovery, monkeypatch
):
    module, database, user = recovery

    start_session(user["id"])

    prompts = iter([NEW_PASSWORD, NEW_PASSWORD])
    monkeypatch.setattr(
        module.getpass,
        "getpass",
        lambda _: next(prompts),
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda _: "YES",
    )

    module.main([
        "--username", "recoverytest",
        "--db", str(database),
    ])

    with connection() as db:
        row = db.execute(
            """SELECT password_hash, role, active, scope_json,
                      must_change_password
               FROM local_users WHERE id=?""",
            (user["id"],),
        ).fetchone()

        sessions = db.execute(
            "SELECT revoked_at FROM local_sessions WHERE user_id=?",
            (user["id"],),
        ).fetchall()

    assert verify_password(row["password_hash"], NEW_PASSWORD)
    assert not verify_password(row["password_hash"], OLD_PASSWORD)
    assert row["role"] == "provider_admin"
    assert row["active"] == 1
    assert row["must_change_password"] == 1
    assert '"connection_ids": []' in row["scope_json"]
    assert len(sessions) == 1
    assert all(s["revoked_at"] is not None for s in sessions)


def test_mismatched_password_preserves_account(
    recovery, monkeypatch
):
    module, database, user = recovery

    prompts = iter([
        NEW_PASSWORD,
        "DifferentPassword-003",
    ])
    monkeypatch.setattr(
        module.getpass,
        "getpass",
        lambda _: next(prompts),
    )

    with pytest.raises(SystemExit, match="do not match"):
        module.main([
            "--username", "recoverytest",
            "--db", str(database),
        ])

    with connection() as db:
        row = db.execute(
            "SELECT password_hash FROM local_users WHERE id=?",
            (user["id"],),
        ).fetchone()

    assert verify_password(row["password_hash"], OLD_PASSWORD)


def test_unknown_user_does_not_create_account(recovery):
    module, database, _ = recovery

    with pytest.raises(SystemExit, match="not found"):
        module.main([
            "--username", "unknownuser",
            "--db", str(database),
        ])

    with connection() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM local_users"
        ).fetchone()[0]

    assert count == 1


def test_inactive_account_cannot_be_reset(recovery):
    module, database, user = recovery

    with connection() as db:
        db.execute(
            "UPDATE local_users SET active=0 WHERE id=?",
            (user["id"],),
        )

    with pytest.raises(SystemExit, match="inactive"):
        module.main([
            "--username", "recoverytest",
            "--db", str(database),
        ])


def test_environment_database_path_is_honored(
    recovery, monkeypatch, tmp_path
):
    module, database, user = recovery

    # The environment points at our isolated test database.
    monkeypatch.setenv(
        "GAME_DB_PATH",
        str(database)
    )

    prompts = iter([NEW_PASSWORD, NEW_PASSWORD])
    monkeypatch.setattr(
        module.getpass,
        "getpass",
        lambda _: next(prompts),
    )
    monkeypatch.setattr("builtins.input", lambda _: "YES")

    module.main(["--username", "recoverytest"])

    with connection() as db:
        row = db.execute(
            "SELECT password_hash FROM local_users WHERE id=?",
            (user["id"],),
        ).fetchone()

    assert verify_password(row["password_hash"], NEW_PASSWORD)


def test_explicit_database_overrides_environment(
    recovery, monkeypatch, tmp_path
):
    module, database, user = recovery

    # Set the environment to a different, nonexistent database.
    wrong_database = tmp_path / "wrong.db"
    monkeypatch.setenv(
        "GAME_DB_PATH",
        str(wrong_database)
    )

    prompts = iter([NEW_PASSWORD, NEW_PASSWORD])
    monkeypatch.setattr(
        module.getpass,
        "getpass",
        lambda _: next(prompts),
    )
    monkeypatch.setattr("builtins.input", lambda _: "YES")

    module.main([
        "--username", "recoverytest",
        "--db", str(database)
    ])

    assert not wrong_database.exists()

    # Inspect the correct database.
    monkeypatch.setenv("GAME_DB_PATH", str(database))

    with connection() as db:
        row = db.execute(
            "SELECT password_hash FROM local_users WHERE id=?",
            (user["id"],),
        ).fetchone()

    assert verify_password(row["password_hash"], NEW_PASSWORD)
