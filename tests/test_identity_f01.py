# SPDX-License-Identifier: AGPL-3.0-only
"""F01 canonical identity: isolated, test-first contract."""

import sqlite3

import pytest

from game.identity import (
    IdentityConflict,
    IdentityUnverified,
    initialize_identity_schema,
    resolve_external_identity,
)


@pytest.fixture
def db():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    initialize_identity_schema(connection)
    yield connection
    connection.close()


def resolve(db, tenant="tenant-a", provider="microsoft_foundry",
            scope="azure-project-001", external="agent-001",
            evidence="provider:agent-001", connection_id=None):
    return resolve_external_identity(
        db,
        tenant_id=tenant,
        provider=provider,
        scope_key=scope,
        external_id=external,
        evidence_reference=evidence,
        connection_id=connection_id,
    )


def test_repeated_discovery_preserves_identity(db):
    first = resolve(db)
    second = resolve(db)

    assert first == second
    assert db.execute(
        "SELECT COUNT(*) FROM canonical_agents"
    ).fetchone()[0] == 1


def test_same_external_id_different_scopes(db):
    first = resolve(db, scope="project-a")
    second = resolve(db, scope="project-b")

    assert first != second


def test_same_external_id_different_tenants(db):
    first = resolve(db, tenant="tenant-a")
    second = resolve(db, tenant="tenant-b")

    assert first != second


def test_different_connections_same_authoritative_identity(db):
    first = resolve(db, connection_id="conn-one")
    second = resolve(db, connection_id="conn-two")

    assert first == second


def test_incomplete_authoritative_identity_fails_closed(db):
    with pytest.raises(IdentityUnverified):
        resolve(db, scope="")

    assert db.execute(
        "SELECT COUNT(*) FROM canonical_agents"
    ).fetchone()[0] == 0


def test_conflicting_verified_identity_fails_closed(db):
    canonical_id = resolve(db)

    # Simulate a corrupted/contradictory mapping attempt.
    # Resolver must reject it rather than silently remapping
    # existing historical identity.
    with pytest.raises(IdentityConflict):
        resolve_external_identity(
            db,
            tenant_id="tenant-a",
            provider="microsoft_foundry",
            scope_key="azure-project-001",
            external_id="agent-001",
            evidence_reference="provider:agent-001",
            expected_canonical_id="different-canonical-id",
        )

    assert resolve(db) == canonical_id
