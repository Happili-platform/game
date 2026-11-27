# SPDX-License-Identifier: AGPL-3.0-only
"""F01: Non-destructive backfill of legacy GAMe identities."""

from game.db import connection, initialize
from game.identity import (
    initialize_identity_schema,
    backfill_legacy_references,
)


def seed_database(tmp_path, monkeypatch):
    monkeypatch.setenv("GAME_DB_PATH", str(tmp_path / "migration.db"))
    monkeypatch.setenv("GAME_DEMO_DATA", "false")
    initialize()

    with connection() as db:
        db.execute("""
            INSERT INTO agents (
                id, name, provider, environment, approval_status,
                lifecycle_status, created_at, tenant_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "agt-legacy-1", "Manual Agent", "Custom / Python",
            "production", "pending", "active",
            "2026-11-01", "local-dev"
        ))

        db.execute("""
            INSERT INTO provider_connections (
                id, provider, label, scope_json,
                env_prefix, created_at, tenant_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "conn-legacy-1", "microsoft_foundry",
            "Existing Foundry", '{"project":"test"}',
            "GAME_TEST", "2026-11-01", "local-dev"
        ))

        db.execute("""
            INSERT INTO discovered_agents (
                id, connection_id, external_id, name, provider,
                discovered_at, discovery_last_seen,
                created_at, tenant_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "ext-legacy-1", "conn-legacy-1", "provider-agent-1",
            "Foundry Agent", "Microsoft Foundry",
            "2026-11-01", "2026-11-01",
            "2026-11-01", "local-dev"
        ))

        db.execute("""
            INSERT INTO usage_events (
                id, agent_id, occurred_at, cost_usd, outcome,
                tenant_id
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            "usage-legacy-1", "agt-legacy-1",
            "2026-11-02", 12.50, "success", "local-dev"
        ))


def test_backfill_preserves_legacy_identity_and_usage(
    tmp_path, monkeypatch
):
    seed_database(tmp_path, monkeypatch)

    with connection() as db:
        initialize_identity_schema(db)

        before_usage = [
            tuple(r) for r in db.execute(
                "SELECT id, agent_id, cost_usd FROM usage_events"
            )
        ]

        result = backfill_legacy_references(db)

        assert result["created"] == 2

        references = db.execute("""
            SELECT source_table, legacy_agent_id, canonical_agent_id
            FROM agent_legacy_references
            ORDER BY source_table
        """).fetchall()

        assert len(references) == 2
        assert len({r["canonical_agent_id"] for r in references}) == 2

        assert db.execute(
            "SELECT COUNT(*) FROM agents"
        ).fetchone()[0] == 1

        assert db.execute(
            "SELECT COUNT(*) FROM discovered_agents"
        ).fetchone()[0] == 1

        after_usage = [
            tuple(r) for r in db.execute(
                "SELECT id, agent_id, cost_usd FROM usage_events"
            )
        ]

        assert before_usage == after_usage

        # Unverified provider identities must not be merged.
        assert db.execute(
            "SELECT COUNT(*) FROM agent_identity_mappings"
        ).fetchone()[0] == 0


def test_backfill_is_idempotent(tmp_path, monkeypatch):
    seed_database(tmp_path, monkeypatch)

    with connection() as db:
        initialize_identity_schema(db)

        first = backfill_legacy_references(db)

        original = [
            tuple(r) for r in db.execute("""
                SELECT source_table, legacy_agent_id,
                       canonical_agent_id
                FROM agent_legacy_references
                ORDER BY source_table
            """)
        ]

        second = backfill_legacy_references(db)

        repeated = [
            tuple(r) for r in db.execute("""
                SELECT source_table, legacy_agent_id,
                       canonical_agent_id
                FROM agent_legacy_references
                ORDER BY source_table
            """)
        ]

        assert first["created"] == 2
        assert second["created"] == 0
        assert original == repeated

        assert db.execute(
            "SELECT COUNT(*) FROM canonical_agents"
        ).fetchone()[0] == 2


def test_backfill_preserves_tenant_boundaries(
    tmp_path, monkeypatch
):
    seed_database(tmp_path, monkeypatch)

    with connection() as db:
        db.execute("""
            INSERT INTO tenants (id, name, created_at)
            VALUES (?, ?, ?)
        """, ("other-company", "Other Company", "2026-11-01"))

        db.execute("""
            INSERT INTO agents (
                id, name, provider, environment, approval_status,
                lifecycle_status, created_at, tenant_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "agt-other", "Other Tenant Agent", "Custom / Python",
            "production", "pending", "active",
            "2026-11-01", "other-company"
        ))

        initialize_identity_schema(db)
        backfill_legacy_references(db)

        rows = db.execute("""
            SELECT tenant_id, legacy_agent_id, canonical_agent_id
            FROM agent_legacy_references
        """).fetchall()

        assert len(rows) == 3
        assert len({r["canonical_agent_id"] for r in rows}) == 3

        for row in rows:
            canonical = db.execute("""
                SELECT tenant_id FROM canonical_agents
                WHERE id=?
            """, (row["canonical_agent_id"],)).fetchone()

            assert canonical["tenant_id"] == row["tenant_id"]
