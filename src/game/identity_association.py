# SPDX-License-Identifier: AGPL-3.0-only
"""F01: Atomic identity association for existing discovered agents."""

from __future__ import annotations

import json
import sqlite3

from .identity import (
    IdentityConflict,
    IdentityUnverified,
    bind_discovered_legacy_identity,
    validate_discovery_batch,
)
from .identity_preflight import (
    IdentityPreflight,
    discovery_identity_preflight,
)


def associate_discovered_batch(
    db: sqlite3.Connection,
    *,
    tenant_id: str,
    connection_id: str,
    agents: list,
    preflight: IdentityPreflight,
    evidence_reference: str,
) -> dict[str, str]:
    """Associate an already-persisted discovery batch atomically.

    Requires existing F01 schema and legacy references.
    A trusted internal caller must establish source verification.

    This function does not create inventory rows, commit the
    caller's transaction, or change legacy agent identifiers.
    """
    if not preflight.eligible or not preflight.scope_key:
        raise IdentityUnverified(
            "Authenticated provider identity is not verified"
        )

    validate_discovery_batch(agents)

    if preflight.agent_count != len(agents):
        raise IdentityConflict("Discovery batch differs from preflight")

    row = db.execute("""
        SELECT provider, scope_json, auth_mode, auth_config_json
        FROM provider_connections
        WHERE id=? AND tenant_id=?
    """, (connection_id, tenant_id)).fetchone()

    if row is None:
        raise IdentityConflict("Provider connection not found")

    configured = {
        "provider": row["provider"],
        "scope": json.loads(row["scope_json"]),
        "auth_mode": row["auth_mode"],
        "auth_config": json.loads(row["auth_config_json"]),
    }

    # Revalidate the resource names and source scope against the
    # connection currently persisted in the database.
    checked = discovery_identity_preflight(
        configured,
        agents,
        authenticated_source_verified=True,
    )

    if (
        not checked.eligible
        or checked.provider != preflight.provider
        or checked.scope_key != preflight.scope_key
    ):
        raise IdentityConflict(
            "Provider identity differs from verified preflight"
        )

    if not isinstance(evidence_reference, str) or not evidence_reference.strip():
        raise IdentityUnverified("Source evidence reference is required")

    db.execute("SAVEPOINT f01_associate_batch")
    try:
        result = {}

        for agent in agents:
            external_id = agent.external_id
            found = db.execute("""
                SELECT id
                FROM discovered_agents
                WHERE tenant_id=? AND connection_id=?
                  AND external_id=?
            """, (
                tenant_id, connection_id, external_id
            )).fetchone()

            if found is None:
                raise IdentityConflict(
                    "Discovered agent is missing from inventory"
                )

            legacy_id = found["id"]

            canonical_id = bind_discovered_legacy_identity(
                db,
                tenant_id=tenant_id,
                legacy_agent_id=legacy_id,
                evidence_reference=evidence_reference,
            )

            result[legacy_id] = canonical_id

        db.execute("RELEASE SAVEPOINT f01_associate_batch")
        return result

    except Exception:
        db.execute("ROLLBACK TO SAVEPOINT f01_associate_batch")
        db.execute("RELEASE SAVEPOINT f01_associate_batch")
        raise
