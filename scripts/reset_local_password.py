# SPDX-License-Identifier: AGPL-3.0-only
"""Recover an GAME local account password from the host CLI."""

import argparse
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Reset a local GAME user password"
    )
    parser.add_argument(
        "--username",
        required=True,
        help="Existing local username"
    )
    parser.add_argument(
        "--db",
        default=os.environ.get(
            "GAME_DB_PATH",
            str(ROOT / "data" / "game.db"),
        ),
        help="Path to the existing GAME database"
    )
    args = parser.parse_args(argv)

    database = Path(args.db).expanduser().resolve()

    if not database.is_file():
        parser.error(f"Database does not exist: {database}")

    os.environ["GAME_DB_PATH"] = str(database)

    from game.db import connection, iso, utc_now
    from game.local_accounts import (
        normalize_username,
        hash_password,
        revoke_user_sessions,
    )

    username = normalize_username(args.username)

    with connection() as db:
        user = db.execute(
            "SELECT id, username, role, active "
            "FROM local_users WHERE username=?",
            (username,)
        ).fetchone()

    if user is None:
        raise SystemExit(f"User not found: {username}")

    if not user["active"]:
        raise SystemExit(
            "Account is inactive. Password reset cannot "
            "reactivate the account."
        )

    print(f"Database: {database}")
    print(f"User: {user['username']}")
    print(f"Role: {user['role']}")

    password = getpass.getpass("New password: ")
    confirm = getpass.getpass("Confirm new password: ")

    if password != confirm:
        raise SystemExit("Passwords do not match.")

    # Reuse the application's Argon2id policy.
    password_hash = hash_password(password)

    confirmation = input(
        f"Reset password for {username}? Type YES: "
    )
    if confirmation != "YES":
        raise SystemExit("Cancelled.")

    with connection() as db:
        cursor = db.execute(
            """
            UPDATE local_users
            SET password_hash=?,
                password_changed_at=?,
                must_change_password=1
            WHERE id=? AND active=1
            """,
            (password_hash, iso(utc_now()), user["id"])
        )
        if cursor.rowcount != 1:
            raise RuntimeError(
                "Account changed during reset; no password updated."
            )

        revoke_user_sessions(db, user["id"])

        from uuid import uuid4
        db.execute(
            '''
            INSERT INTO audit_events
            (id, tenant_id, actor, operation, resource_id, occurred_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (
                "aud-" + uuid4().hex[:16],
                "local-dev",
                "local-operator",
                "local-user.password.recovery",
                user["id"],
                iso(utc_now()),
            ),
        )

    print(f"SUCCESS: Password reset for {username}")
    print("Existing login sessions have been revoked.")


if __name__ == "__main__":
    main()
