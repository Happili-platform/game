# SPDX-License-Identifier: AGPL-3.0-only
"""Verify stable canonical identity across real Google discovery runs."""

import json
import sqlite3
import sys
from pathlib import Path

DB = Path.home() / ".local/share/game/game.db"
BASELINE = Path.home() / ".local/share/game/f01-google-baseline.json"

CONNECTION = "conn-23b8daff7fa0"
RESOURCE = (
    "projects/268096427189/locations/us-central1/"
    "reasoningEngines/112461622701719552"
)

TABLES = (
    "discovered_agents",
    "canonical_agents",
    "agent_legacy_references",
    "agent_identity_mappings",
    "agent_identity_conflicts",
)


def snapshot():
    with sqlite3.connect(
        DB.resolve().as_uri() + "?mode=ro", uri=True
    ) as db:
        db.row_factory = sqlite3.Row

        rows = db.execute("""
            SELECT a.id AS legacy_id, a.tenant_id,
                   r.canonical_agent_id,
                   m.id AS mapping_id,
                   m.verification_status
            FROM discovered_agents a
            JOIN agent_legacy_references r
              ON r.tenant_id=a.tenant_id
             AND r.source_table='discovered_agents'
             AND r.legacy_agent_id=a.id
            JOIN agent_identity_mappings m
              ON m.tenant_id=a.tenant_id
             AND m.canonical_agent_id=r.canonical_agent_id
             AND m.connection_id=a.connection_id
             AND m.external_id=a.external_id
            WHERE a.connection_id=?
              AND a.external_id=?
        """, (CONNECTION, RESOURCE)).fetchall()

        return {
            "matching_rows": len(rows),
            "legacy_id": rows[0]["legacy_id"] if len(rows) == 1 else None,
            "canonical_id": (
                rows[0]["canonical_agent_id"]
                if len(rows) == 1 else None
            ),
            "mapping_id": rows[0]["mapping_id"] if len(rows) == 1 else None,
            "mapping_verified": (
                rows[0]["verification_status"] == "verified"
                if len(rows) == 1 else False
            ),
            "counts": {
                t: db.execute(
                    f"SELECT COUNT(*) FROM {t}"
                ).fetchone()[0]
                for t in TABLES
            },
            "integrity": db.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0],
            "foreign_keys_valid": not bool(
                db.execute("PRAGMA foreign_key_check").fetchall()
            ),
        }


if len(sys.argv) != 2 or sys.argv[1] not in ("capture", "verify"):
    raise SystemExit("Usage: f01_google_idempotency.py capture|verify")

current = snapshot()

if sys.argv[1] == "capture":
    if current["matching_rows"] != 1 or not current["mapping_verified"]:
        raise SystemExit("FAIL: Expected one verified Google identity")

    if BASELINE.exists():
        raise SystemExit(
            "STOP: Baseline already exists; refusing to overwrite"
        )

    BASELINE.write_text(json.dumps(current, indent=2))
    BASELINE.chmod(0o600)

    print("PASS: Baseline captured")
    print("Canonical ID:", current["canonical_id"])
    print("Next: Run Google discovery once more in GAMe")
    sys.exit(0)

if not BASELINE.exists():
    raise SystemExit("FAIL: Baseline not captured")

before = json.loads(BASELINE.read_text())

checks = {
    "Exactly one Google resource": current["matching_rows"] == 1,
    "Verified mapping retained": current["mapping_verified"],
    "Legacy ID unchanged":
        current["legacy_id"] == before["legacy_id"],
    "Canonical ID unchanged":
        current["canonical_id"] == before["canonical_id"],
    "Mapping ID unchanged":
        current["mapping_id"] == before["mapping_id"],
    "No new inventory or identities":
        current["counts"] == before["counts"],
    "No identity conflicts":
        current["counts"]["agent_identity_conflicts"] == 0,
    "SQLite integrity":
        current["integrity"] == "ok",
    "Foreign keys valid":
        current["foreign_keys_valid"],
}

print("\nGAMe F01 — GOOGLE IDEMPOTENCY")
print("=" * 50)

for name, passed in checks.items():
    print(f"[{'PASS' if passed else 'FAIL'}] {name}")

print("=" * 50)
print(f"RESULT: {sum(checks.values())}/{len(checks)} passed")

if not all(checks.values()):
    raise SystemExit(1)
