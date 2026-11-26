# SPDX-License-Identifier: AGPL-3.0-only
"""F01: Safe identity reconciliation across provider connections."""

import pytest

from game.identity import (
    IdentityConflict,
    IdentityUnverified,
    initialize_identity_schema,
    resolve_external_identity,
)


@pytest.fixture
def db():
    import sqlite3

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    initialize_identity_schema(connection)
    yield connection
    connection.close()


def resolve(db, *, tenant="tenant-a", provider="google_agent_engine",
            scope="gcp:projects/sample-project/locations/us-central1/agent-engine",
            external="agent-123", conn="conn-a", expected=None):
    return resolve_external_identity(
        db,
        tenant_id=tenant,
        provider=provider,
        scope_key=scope,
        external_id=external,
        evidence_reference="test:verified-source",
        connection_id=conn,
        expected_canonical_id=expected,
    )


def test_two_connections_reuse_verified_identity(db):
    first = resolve(db, conn="conn-a")
    second = resolve(db, conn="conn-b")

    assert first == second
    assert db.execute(
        "SELECT COUNT(*) FROM canonical_agents"
    ).fetchone()[0] == 1


def test_different_authoritative_scopes_remain_separate(db):
    first = resolve(db, scope="project-a")
    second = resolve(db, scope="project-b")

    assert first != second


def test_same_external_id_in_different_tenants_remains_separate(db):
    first = resolve(db, tenant="tenant-a")
    second = resolve(db, tenant="tenant-b")

    assert first != second


def test_conflicting_canonical_identity_cannot_replace_mapping(db):
    first = resolve(db)

    with pytest.raises(IdentityConflict):
        resolve(db, expected="game-agt-different")

    assert resolve(db) == first


def test_missing_authoritative_scope_cannot_create_identity(db):
    with pytest.raises(IdentityUnverified):
        resolve(db, scope="")

    assert db.execute(
        "SELECT COUNT(*) FROM canonical_agents"
    ).fetchone()[0] == 0


def test_same_external_id_different_provider_remains_separate(db):
    first = resolve(db, provider="google_agent_engine")
    second = resolve(db, provider="aws_agentcore")

    assert first != second
