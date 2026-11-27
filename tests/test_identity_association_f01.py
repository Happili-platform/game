# SPDX-License-Identifier: AGPL-3.0-only
"""F01: Atomic discovered-agent identity association."""

from types import SimpleNamespace

import pytest

from game.db import connection, initialize
from game.identity import (
    IdentityConflict,
    IdentityUnverified,
    backfill_legacy_references,
    initialize_identity_schema,
)
from game.identity_association import associate_discovered_batch
from game.discovery_provenance import _issue_connector_receipt


SCOPE = {
    "project_id": "sample-project",
    "location": "us-central1",
}

PREFIX = (
    "projects/sample-project/locations/"
    "us-central1/reasoningEngines/"
)


def agent(value):
    return SimpleNamespace(external_id=PREFIX + value)


def configured():
    return {
        "provider": "google_agent_engine",
        "scope": SCOPE,
        "auth_mode": "legacy",
        "auth_config": {},
    }


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    import json

    monkeypatch.setenv("GAME_DB_PATH", str(tmp_path / "f01.db"))
    monkeypatch.setenv("GAME_DEMO_DATA", "false")
    initialize()

    with connection() as db:
        for cid in ("conn-a", "conn-b"):
            db.execute("""
                INSERT INTO provider_connections
                (id, provider, label, scope_json, env_prefix,
                 created_at, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                cid, "google_agent_engine", cid,
                json.dumps(SCOPE), "GAME_GOOGLE",
                "2026-11-25", "local-dev",
            ))

        for legacy_id, cid, external_id in (
            ("ext-one", "conn-a", PREFIX + "1"),
            ("ext-two", "conn-a", PREFIX + "2"),
            ("ext-conflict", "conn-b", PREFIX + "1"),
        ):
            db.execute("""
                INSERT INTO discovered_agents
                (id, connection_id, external_id, name,
                 provider, discovered_at,
                 discovery_last_seen, created_at, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                legacy_id, cid, external_id, legacy_id,
                "Google Agent Engine", "2026-11-25",
                "2026-11-25", "2026-11-25", "local-dev",
            ))

        initialize_identity_schema(db)
        backfill_legacy_references(db)


def associate(db, agents, cid="conn-a", verified=True):
    receipt = (
        _issue_connector_receipt(
            {
                **configured(),
                "id": cid,
                "tenant_id": "local-dev",
            },
            agents,
        )
        if verified else None
    )

    return associate_discovered_batch(
        db,
        tenant_id="local-dev",
        connection_id=cid,
        agents=agents,
        receipt=receipt,
        evidence_reference="test:successful-provider-discovery",
    )


def mapping_count(db):
    return db.execute(
        "SELECT COUNT(*) FROM agent_identity_mappings"
    ).fetchone()[0]


def test_association_reuses_legacy_canonical_identity(prepared):
    with connection() as db:
        original = db.execute("""
            SELECT canonical_agent_id
            FROM agent_legacy_references
            WHERE legacy_agent_id='ext-one'
        """).fetchone()[0]

        result = associate(db, [agent("1")])

        assert result == {"ext-one": original}
        assert mapping_count(db) == 1
        assert db.execute(
            "SELECT id FROM discovered_agents "
            "WHERE id='ext-one'"
        ).fetchone() is not None


def test_repeated_batch_is_idempotent(prepared):
    with connection() as db:
        first = associate(db, [agent("1"), agent("2")])
        second = associate(db, [agent("1"), agent("2")])

        assert first == second
        assert len(first) == 2
        assert mapping_count(db) == 2

        # The backfilled canonicals were reused, not duplicated.
        assert db.execute(
            "SELECT COUNT(*) FROM canonical_agents"
        ).fetchone()[0] == 3


def test_conflicting_second_agent_rolls_back_entire_batch(prepared):
    with connection() as db:
        # Establish the authoritative identity through conn-b.
        associate(db, [agent("1")], cid="conn-b")
        before = mapping_count(db)

        # conn-a's first resource has a different legacy canonical.
        # Both resources must therefore remain unassociated.
        with pytest.raises(IdentityConflict):
            associate(db, [agent("2"), agent("1")])

        assert mapping_count(db) == before

        assert db.execute("""
            SELECT COUNT(*) FROM agent_identity_mappings
            WHERE connection_id='conn-a'
        """).fetchone()[0] == 0


def test_unverified_batch_cannot_create_mappings(prepared):
    with connection() as db:
        with pytest.raises(IdentityUnverified):
            associate(db, [agent("1")], verified=False)

        assert mapping_count(db) == 0


def test_missing_inventory_rolls_back_previous_mapping(prepared):
    with connection() as db:
        with pytest.raises(IdentityConflict):
            associate(db, [agent("1"), agent("missing")])

        assert mapping_count(db) == 0


def test_association_rejects_receipt_for_different_batch(prepared):
    from game.discovery_provenance import _issue_connector_receipt

    with connection() as db:
        receipt = _issue_connector_receipt(
            {
                **configured(),
                "id": "conn-a",
                "tenant_id": "local-dev",
            },
            [agent("1")],
        )

        # Same agent count, different resource identity.
        with pytest.raises(IdentityUnverified):
            associate_discovered_batch(
                db,
                tenant_id="local-dev",
                connection_id="conn-a",
                agents=[agent("2")],
                receipt=receipt,
                evidence_reference="test:provider-discovery",
            )

        assert mapping_count(db) == 0


def test_association_rejects_receipt_from_another_connection(prepared):
    from game.discovery_provenance import _issue_connector_receipt

    with connection() as db:
        receipt = _issue_connector_receipt(
            {
                **configured(),
                "id": "conn-a",
                "tenant_id": "local-dev",
            },
            [agent("1")],
        )

        with pytest.raises(IdentityUnverified):
            associate_discovered_batch(
                db,
                tenant_id="local-dev",
                connection_id="conn-b",
                agents=[agent("1")],
                receipt=receipt,
                evidence_reference="test:provider-discovery",
            )

        assert mapping_count(db) == 0
