# SPDX-License-Identifier: AGPL-3.0-only
"""F01: Bind verified discovered identities without changing history."""

import pytest

from game.db import connection, initialize
from game.identity import (
    IdentityConflict,
    initialize_identity_schema,
    backfill_legacy_references,
    bind_discovered_legacy_identity,
)

SCOPE = '{"project_id":"my-sample-project","location":"us-central1"}'


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("GAME_DB_PATH", str(tmp_path / "binding.db"))
    monkeypatch.setenv("GAME_DEMO_DATA", "false")
    initialize()
    with connection() as db:
        db.execute("""
            INSERT INTO provider_connections
            (id, provider, label, scope_json, env_prefix,
             created_at, tenant_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "conn-a", "google_agent_engine", "Google A", SCOPE,
            "GAME_GOOGLE", "2026-11-20", "local-dev"
        ))
        db.execute("""
            INSERT INTO discovered_agents
            (id, connection_id, external_id, name, provider,
             discovered_at, discovery_last_seen, created_at, tenant_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "ext-existing", "conn-a", "agent-123", "Agent One",
            "Google Agent Engine", "2026-11-20",
            "2026-11-20", "2026-11-20", "local-dev"
        ))
        initialize_identity_schema(db)
        backfill_legacy_references(db)
    return True


def bind(db, legacy="ext-existing"):
    return bind_discovered_legacy_identity(
        db,
        tenant_id="local-dev",
        legacy_agent_id=legacy,
        evidence_reference="test:provider-discovery",
    )


def test_binding_reuses_existing_canonical_identity(database):
    with connection() as db:
        original = db.execute("""
            SELECT canonical_agent_id FROM agent_legacy_references
            WHERE legacy_agent_id='ext-existing'
        """).fetchone()[0]

        assert bind(db) == original
        assert bind(db) == original

        assert db.execute("""
            SELECT COUNT(*) FROM canonical_agents
        """).fetchone()[0] == 1

        assert db.execute("""
            SELECT COUNT(*) FROM agent_identity_mappings
        """).fetchone()[0] == 1

        assert db.execute("""
            SELECT id FROM discovered_agents
        """).fetchone()[0] == "ext-existing"


def test_second_legacy_agent_cannot_steal_mapping(database):
    with connection() as db:
        first = bind(db)

        db.execute("""
            INSERT INTO provider_connections
            (id, provider, label, scope_json, env_prefix,
             created_at, tenant_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "conn-b", "google_agent_engine", "Google B", SCOPE,
            "GAME_GOOGLE_B", "2026-11-20", "local-dev"
        ))

        db.execute("""
            INSERT INTO discovered_agents
            (id, connection_id, external_id, name, provider,
             discovered_at, discovery_last_seen, created_at, tenant_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "ext-second", "conn-b", "agent-123",
            "Same Agent", "Google Agent Engine",
            "2026-11-20", "2026-11-20",
            "2026-11-20", "local-dev"
        ))

        backfill_legacy_references(db)

        with pytest.raises(IdentityConflict):
            bind(db, "ext-second")

        assert bind(db) == first

        assert db.execute("""
            SELECT COUNT(*) FROM agent_identity_mappings
        """).fetchone()[0] == 1


def test_unbackfilled_agent_cannot_be_bound(database):
    with connection() as db:
        db.execute("""
            DELETE FROM agent_legacy_references
            WHERE legacy_agent_id='ext-existing'
        """)
        with pytest.raises(IdentityConflict):
            bind(db)

        assert db.execute("""
            SELECT COUNT(*) FROM agent_identity_mappings
        """).fetchone()[0] == 0
