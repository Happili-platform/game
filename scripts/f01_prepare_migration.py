# SPDX-License-Identifier: AGPL-3.0-only
"""Prepare a validated F01 database copy without modifying the source."""

from __future__ import annotations

import argparse
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from game.identity import (
    initialize_identity_schema,
    backfill_legacy_references,
)

LEGACY = ("agents", "discovered_agents")
IDENTITY = (
    "canonical_agents",
    "agent_legacy_references",
    "agent_identity_mappings",
    "agent_identity_conflicts",
)


def counts(db, tables):
    return {
        table: db.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        for table in tables
    }


def legacy_rows(db):
    """Capture complete legacy rows for exact comparison."""
    return {
        table: [
            tuple(row)
            for row in db.execute(
                f"SELECT * FROM {table} ORDER BY id"
            )
        ]
        for table in LEGACY
    }


def prepare(source: Path, output: Path):
    source = source.resolve()
    output = output.resolve()

    if source == output:
        raise ValueError("Source and output must differ")

    if not source.is_file():
        raise FileNotFoundError("Source database does not exist")

    if output.exists() or output.is_symlink():
        raise FileExistsError("Output already exists; refusing overwrite")

    if not output.parent.is_dir():
        raise FileNotFoundError("Output directory does not exist")

    created = False

    try:
        # Create the destination exclusively with restrictive permissions.
        fd = os.open(
            output,
            os.O_CREAT | os.O_EXCL | os.O_RDWR,
            0o600,
        )
        os.close(fd)
        created = True

        # Read-only source; SQLite backup produces a consistent snapshot.
        source_uri = source.as_uri() + "?mode=ro"

        with closing(sqlite3.connect(source_uri, uri=True)) as src:
            with closing(sqlite3.connect(output)) as dst:
                src.backup(dst)

        with closing(sqlite3.connect(output)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")

            before_rows = legacy_rows(db)
            before_counts = counts(db, LEGACY)

            # Schema initialization uses executescript().
            # Complete DDL before starting the backfill transaction.
            initialize_identity_schema(db)

            db.execute("BEGIN IMMEDIATE")
            try:
                first = backfill_legacy_references(db)
                db.commit()
            except Exception:
                db.rollback()
                raise

            db.execute("BEGIN IMMEDIATE")
            try:
                second = backfill_legacy_references(db)
                db.commit()
            except Exception:
                db.rollback()
                raise

            after_counts = counts(db, LEGACY)
            identity_counts = counts(db, IDENTITY)

            integrity = db.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]

            foreign_keys = db.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()

            if before_rows != legacy_rows(db):
                raise RuntimeError(
                    "Historical legacy records changed"
                )

            if before_counts != after_counts:
                raise RuntimeError(
                    "Historical inventory counts changed"
                )

            if second["created"] != 0:
                raise RuntimeError(
                    "Migration is not idempotent"
                )

            if integrity != "ok" or foreign_keys:
                raise RuntimeError(
                    "Database integrity validation failed"
                )

            expected = sum(after_counts.values())
            if identity_counts["agent_legacy_references"] != expected:
                raise RuntimeError(
                    "Legacy identity reference count mismatch"
                )

        # Verify staged changes are checkpointed before single-file cutover.
        # This check runs after the migration connection has closed.
        with closing(sqlite3.connect(output)) as verified:
            if verified.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0] != "ok":
                raise RuntimeError("Staged database integrity failed")

            tables = {
                row[0] for row in verified.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table'"
                )
            }
            if not set(IDENTITY).issubset(tables):
                raise RuntimeError(
                    "Staged database missing identity tables"
                )

            if verified.execute(
                "PRAGMA foreign_key_check"
            ).fetchall():
                raise RuntimeError(
                    "Staged database foreign-key validation failed"
                )

            # Ensure WAL pages are transferred into the main database.
            checkpoint = verified.execute(
                "PRAGMA wal_checkpoint(TRUNCATE)"
            ).fetchone()
            if checkpoint and checkpoint[0] != 0:
                raise RuntimeError(
                    "Staged SQLite WAL checkpoint was blocked"
                )

        if Path(str(output) + "-wal").exists():
            raise RuntimeError(
                "Staged WAL file still exists after checkpoint"
            )

        return {
            "before": before_counts,
            "after": after_counts,
            "first": first,
            "second": second,
            "identity": identity_counts,
            "integrity": integrity,
            "foreign_key_violations": len(foreign_keys),
        }

    except Exception:
        if created:
            output.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = prepare(
        Path(args.source),
        Path(args.output),
    )

    print("F01 STAGED MIGRATION: PASS")
    print("Original inventory:", result["before"])
    print("Staged inventory:", result["after"])
    print("First backfill:", result["first"])
    print("Second backfill:", result["second"])
    print("Identity counts:", result["identity"])
    print("Integrity:", result["integrity"])
    print(
        "Foreign-key violations:",
        result["foreign_key_violations"],
    )
    print("Original database was opened read-only.")
    print("Staged output:", args.output)
