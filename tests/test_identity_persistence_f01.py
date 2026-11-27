# SPDX-License-Identifier: AGPL-3.0-only
"""F01: Inventory and identity must commit or rollback together."""

import json

import pytest

from game.connectors import DiscoveredAgent
from game.db import connection, initialize
from game.discovery_provenance import _issue_connector_receipt
from game.identity import (
    IdentityConflict,
    IdentityUnverified,
    initialize_identity_schema,
)
from game.identity_persistence import persist_verified_discovery_batch


PREFIX = (
    "projects/sample-project/locations/"
    "us-central1/reasoningEngines/"
)


def agent(value, name=None):
    return DiscoveredAgent(
        PREFIX + value,
        name or value,
        "Google Agent Engine",
    )


def configured(cid):
    return {
        "id": cid,
        "tenant_id": "local-dev",
        "provider": "google_agent_engine",
        "scope": {
            "project_id": "sample-project",
            "location": "us-central1",
        },
        "auth_mode": "legacy",
        "auth_config": {},
    }


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("GAME_DB_PATH", str(tmp_path / "atomic.db"))
    monkeypatch.setenv("GAME_DEMO_DATA", "false")
    initialize()

    with connection() as db:
        for cid in ("conn-a", "conn-b"):
            db.execute("""
                INSERT INTO provider_connections
                (id, provider, label, scope_json,
                 env_prefix, created_at, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                cid, "google_agent_engine", cid,
                json.dumps(configured(cid)["scope"]),
                "GAME_GOOGLE", "2026-11-27", "local-dev",
            ))

        # DDL initialization happens outside persistence transactions.
        initialize_identity_schema(db)


def persist(db, cid, agents, receipt=None):
    if receipt is None:
        receipt = _issue_connector_receipt(
            configured(cid), agents
        )
    return persist_verified_discovery_batch(
        db,
        tenant_id="local-dev",
        connection_id=cid,
        agents=agents,
        receipt=receipt,
        evidence_reference="test:completed-google-discovery",
    )


def count(db, table):
    return db.execute(
        f"SELECT COUNT(*) FROM {table}"
    ).fetchone()[0]


def test_new_verified_agent_creates_complete_association(database):
    with connection() as db:
        result = persist(db, "conn-a", [agent("1")])

        assert len(result) == 1
        assert count(db, "discovered_agents") == 1
        assert count(db, "canonical_agents") == 1
        assert count(db, "agent_legacy_references") == 1
        assert count(db, "agent_identity_mappings") == 1
        assert next(iter(result)).startswith("ext-")


def test_repeat_discovery_preserves_existing_ids(database):
    with connection() as db:
        first = persist(db, "conn-a", [agent("1")])
        second = persist(
            db, "conn-a", [agent("1", "Updated name")]
        )

        assert first == second
        assert count(db, "discovered_agents") == 1
        assert count(db, "canonical_agents") == 1
        assert count(db, "agent_identity_mappings") == 1

        assert db.execute(
            "SELECT name FROM discovered_agents"
        ).fetchone()[0] == "Updated name"


def test_cross_connection_reuses_verified_identity(database):
    with connection() as db:
        first = persist(db, "conn-a", [agent("1")])
        original_id = next(iter(first.values()))

        second = persist(
            db, "conn-b", [agent("2"), agent("1")]
        )

        assert len(second) == 2
        assert count(db, "discovered_agents") == 3
        assert count(db, "canonical_agents") == 2
        assert count(db, "agent_legacy_references") == 3
        assert count(db, "agent_identity_mappings") == 2

        shared = db.execute("""
            SELECT r.canonical_agent_id
            FROM agent_legacy_references r
            JOIN discovered_agents a
              ON a.id=r.legacy_agent_id
             AND a.tenant_id=r.tenant_id
            WHERE a.connection_id='conn-b'
              AND a.external_id=?
        """, (PREFIX + "1",)).fetchone()

        assert shared["canonical_agent_id"] == original_id


def test_conflicting_historical_reference_remains_protected(database):
    with connection() as db:
        persist(db, "conn-a", [agent("1")])

        # Create pre-existing historical inventory under connection B
        # and backfill it before verified reconciliation.
        db.execute("""
            INSERT INTO discovered_agents (
                id, connection_id, external_id, name,
                provider, discovered_at, discovery_last_seen,
                created_at, tenant_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "ext-historical-b", "conn-b", PREFIX + "1",
            "Historical B", "Google Agent Engine",
            "2026-11-27", "2026-11-27",
            "2026-11-27", "local-dev",
        ))

        from game.identity import backfill_legacy_references
        backfill_legacy_references(db)

        with pytest.raises(IdentityConflict):
            persist(db, "conn-b", [agent("1")])

        # A failed batch must not replace the original reference.
        assert count(db, "discovered_agents") == 2
        assert count(db, "canonical_agents") == 2
        assert count(db, "agent_legacy_references") == 2
        assert count(db, "agent_identity_mappings") == 1



def test_invalid_receipt_writes_nothing(database):
    with connection() as db:
        wrong = _issue_connector_receipt(
            configured("conn-b"), [agent("1")]
        )

        with pytest.raises(IdentityUnverified):
            persist(
                db, "conn-a", [agent("1")],
                receipt=wrong,
            )

        for table in (
            "discovered_agents",
            "canonical_agents",
            "agent_legacy_references",
            "agent_identity_mappings",
        ):
            assert count(db, table) == 0


def test_repeated_verified_discovery_refreshes_last_seen(
    database, monkeypatch
):
    import game.identity as identity

    with connection() as db:
        persist(db, "conn-a", [agent("1")])

        original = db.execute("""
            SELECT first_seen, last_seen
            FROM agent_identity_mappings
        """).fetchone()

        class Later:
            @staticmethod
            def now():
                from datetime import datetime, timezone
                return datetime(2027, 1, 1, tzinfo=timezone.utc)

        monkeypatch.setattr(identity, "utc_now", Later.now)

        persist(db, "conn-a", [agent("1")])

        updated = db.execute("""
            SELECT first_seen, last_seen
            FROM agent_identity_mappings
        """).fetchone()

        assert updated["first_seen"] == original["first_seen"]
        assert updated["last_seen"] > original["last_seen"]
        assert count(db, "agent_identity_mappings") == 1
