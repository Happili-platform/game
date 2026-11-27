# SPDX-License-Identifier: AGPL-3.0-only
"""F01 migration rehearsal on a disposable SQLite backup only."""

from __future__ import annotations

import argparse
import sqlite3
import tempfile
from pathlib import Path

from game.identity import (
    initialize_identity_schema,
    backfill_legacy_references,
)

IDENTITY_TABLES = (
    "canonical_agents",
    "agent_legacy_references",
    "agent_identity_mappings",
    "agent_identity_conflicts",
)

LEGACY_TABLES = ("agents", "discovered_agents")


def count(db, table):
    return db.execute(
        f"SELECT COUNT(*) FROM {table}"
    ).fetchone()[0]


def run(source_path: Path):
    if not source_path.is_file():
        raise SystemExit(
            f"Database not found: {source_path}"
        )

    with tempfile.TemporaryDirectory(
        prefix="game-f01-rehearsal-"
    ) as temporary:
        backup_path = Path(temporary) / "rehearsal.db"

        # Open the original database read-only.
        original = sqlite3.connect(
            source_path.resolve().as_uri() + "?mode=ro",
            uri=True,
        )

        try:
            with sqlite3.connect(backup_path) as backup:
                original.backup(backup)
        finally:
            original.close()

        with sqlite3.connect(backup_path) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")

            initial = {
                table: count(db, table)
                for table in LEGACY_TABLES
            }

            print("Original inventory snapshot:", initial)

            # DDL is intentionally outside the write transaction.
            initialize_identity_schema(db)

            db.execute("BEGIN IMMEDIATE")
            first = backfill_legacy_references(db)
            db.commit()

            print("First migration:", first)

            db.execute("BEGIN IMMEDIATE")
            second = backfill_legacy_references(db)
            db.commit()

            print("Second migration:", second)

            final_legacy = {
                table: count(db, table)
                for table in LEGACY_TABLES
            }
            identity = {
                table: count(db, table)
                for table in IDENTITY_TABLES
            }

            integrity = db.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]

            foreign_keys = db.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()

            print("Final inventory snapshot:", final_legacy)
            print("Identity table counts:", identity)
            print("SQLite integrity:", integrity)
            print("Foreign-key violations:", len(foreign_keys))

            assert initial == final_legacy, (
                "Legacy inventory changed during rehearsal"
            )
            assert second["created"] == 0, (
                "Migration is not idempotent"
            )
            assert integrity == "ok"
            assert not foreign_keys

            expected_references = sum(initial.values())
            assert identity["agent_legacy_references"] == (
                expected_references
            ), "Unexpected legacy reference count"

            print("F01 MIGRATION REHEARSAL: PASS")

    print(
        "Disposable backup removed. "
        "Original database was not modified by this script."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        default="data/game.db",
        help="Existing GAMe database; opened read-only",
    )
    args = parser.parse_args()
    run(Path(args.source))
