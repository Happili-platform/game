# SPDX-License-Identifier: AGPL-3.0-only
"""Read-only readiness checks for F01 Google discovery."""

import json
import os
import sqlite3
import sys
from pathlib import Path

db_path = Path(
    os.environ.get(
        "GAME_DB_PATH",
        str(Path.home() / ".local/share/game/game.db"),
    )
)


def adc_available() -> bool:
    """Verify ADC can obtain an OAuth token, without printing it."""
    try:
        import google.auth
        from google.auth.transport.requests import Request

        credentials, _ = google.auth.default(
            scopes=[
                "https://www.googleapis.com/auth/cloud-platform"
            ]
        )
        credentials.refresh(Request())
        return bool(credentials.token)
    except Exception:
        return False



def report(status, description):
    print(f"[{status}] {description}")

print("\nGAMe F01 — GOOGLE DISCOVERY READINESS")
print("=" * 55)

if not db_path.is_file():
    report("FAIL", "Active database missing")
    sys.exit(1)

uri = db_path.resolve().as_uri() + "?mode=ro"

with sqlite3.connect(uri, uri=True) as db:
    db.row_factory = sqlite3.Row

    integrity = db.execute(
        "PRAGMA integrity_check"
    ).fetchone()[0]

    if integrity != "ok":
        report("FAIL", "SQLite integrity")
        sys.exit(1)

    report("PASS", "SQLite integrity")

    if db.execute("PRAGMA foreign_key_check").fetchall():
        report("FAIL", "Foreign-key integrity")
        sys.exit(1)

    report("PASS", "Foreign-key integrity")

    required = {
        "canonical_agents",
        "agent_identity_mappings",
        "agent_legacy_references",
        "agent_identity_conflicts",
    }

    existing = {
        row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }

    if not required.issubset(existing):
        report("FAIL", "F01 identity schema incomplete")
        sys.exit(1)

    report("PASS", "F01 identity schema")

    connections = db.execute("""
        SELECT id, label, auth_mode, scope_json,
               last_synced_at, last_error
        FROM provider_connections
        WHERE provider='google_agent_engine'
        ORDER BY label
    """).fetchall()

    print(f"\nGoogle connections found: {len(connections)}")

    if not connections:
        report("BLOCKED", "No Google Agent Engine connection configured")
        print("\nSTATUS: NOT READY")
        sys.exit(2)

    ready = 0
    has_adc = adc_available()
    print(f"Google ADC authentication available: {has_adc}")

    for conn in connections:
        print(f"\nConnection: {conn['label']}")
        print(f"  ID: {conn['id']}")
        print(f"  Authentication mode: {conn['auth_mode']}")

        try:
            scope = json.loads(conn["scope_json"])
        except (TypeError, ValueError):
            scope = {}

        valid_scope = bool(
            scope.get("project_id")
            and scope.get("location")
        )

        credential_count = db.execute("""
            SELECT COUNT(*)
            FROM provider_credentials
            WHERE connection_id=?
        """, (conn["id"],)).fetchone()[0]

        has_saved_credentials = credential_count > 0

        print(f"  Valid project/location scope: {valid_scope}")
        print(f"  Saved credentials present: {has_saved_credentials}")
        print(f"  Last synchronized: {conn['last_synced_at'] or 'Never'}")
        print(f"  Previous error recorded: {bool(conn['last_error'])}")

        # External credential modes may use workload identity or
        # environment credentials rather than saved local secrets.
        if valid_scope and (
            conn["auth_mode"] != "legacy"
            or has_saved_credentials
            or has_adc
        ):
            ready += 1
            report("PASS", "Connection configuration candidate")
        else:
            report("BLOCKED", "Connection needs configuration review")

print("\n" + "=" * 55)
print(f"Configured candidates: {ready}/{len(connections)}")

if ready:
    print("STATUS: CONFIGURATION READY")
    print("NOTE: Google authentication and permissions are not yet verified.")
    sys.exit(0)

print("STATUS: NOT READY")
sys.exit(2)
