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


def test_cross_connection_conflict_rolls_back_new_inventory(database):
    with connection() as db:
        persist(db, "conn-a", [agent("1")])

        with pytest.raises(IdentityConflict):
            persist(
                db, "conn-b",
                [agent("2"), agent("1")],
            )

        # Both newly discovered rows, their canonical identities
        # and any new mappings must be rolled back.
        assert count(db, "discovered_agents") == 1
        assert count(db, "canonical_agents") == 1
        assert count(db, "agent_legacy_references") == 1
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
