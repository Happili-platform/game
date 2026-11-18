# SPDX-License-Identifier: AGPL-3.0-only
"""First-time community setup for GAME."""

import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from game.db import initialize, connection, db_path
from game.local_accounts import create_user, validate_password

ACCOUNTS = (
    ("coadmin", "admin", "Community Admin"),
    ("proadmin", "provider_admin", "Provider Administrator"),
    ("bao", "business_owner", "Business Owner"),
)


def setup():
    root = Path(__file__).resolve().parents[1]

    # Use the application's normal database path.
    os.environ.setdefault(
        "GAME_DB_PATH",
        str(root / "data" / "game.db")
    )

    # Security: refuse accidental setup against a remote location
    # or another checkout.
    expected = (root / "data" / "game.db").resolve()
    actual = db_path().resolve()

    if actual != expected:
        raise ValueError(
            f"Unexpected database path: {actual}\n"
            f"Expected: {expected}"
        )

    initialize()

    with connection() as db:
        existing = {
            row["username"].casefold(): dict(row)
            for row in db.execute(
                "SELECT username, role, active FROM local_users"
            )
        }

    expected_roles = {
        name: role for name, role, _ in ACCOUNTS
    }

    for username, row in existing.items():
        if (
            username not in expected_roles
            or row["role"] != expected_roles[username]
            or not row["active"]
        ):
            raise ValueError(
                "Existing non-community or modified user detected. "
                "Use Administration > Users & Roles."
            )

    print(f"\nGAME database: {actual}")
    print("Community account initialization\n")

    created = []

    for username, role, display_name in ACCOUNTS:
        if username in existing:
            print(f"Already configured: {username}")
            continue

        print(f"Configuring {username} ({role})")

        password = getpass.getpass(
            "Choose password (15+ characters): "
        )
        validate_password(password)

        confirmation = getpass.getpass("Confirm password: ")

        if password != confirmation:
            raise ValueError("Passwords do not match")

        scope = (
            {"kind": "all"}
            if role == "admin"
            else {
                "kind": "selected",
                "connection_ids": [],
                "agent_ids": [],
            }
        )

        create_user(
            username=username,
            password=password,
            role=role,
            display_name=display_name,
            scope=scope,
            must_change=False,
        )

        created.append(username)
        print(f"Created: {username}\n")

    print("Community setup complete.")
    return created


if __name__ == "__main__":
    try:
        setup()
    except (ValueError, EOFError, KeyboardInterrupt) as exc:
        raise SystemExit(f"Setup stopped: {exc}") from None
