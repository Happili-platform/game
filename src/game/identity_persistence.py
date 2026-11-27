# SPDX-License-Identifier: AGPL-3.0-only
"""F01: Atomic persistence of verified discovery and identity."""

from __future__ import annotations

import json
import sqlite3
from uuid import uuid4

from .db import iso, utc_now
from .discovery_provenance import (
    DiscoveryReceipt,
    verify_discovery_receipt,
)
from .identity import IdentityConflict
from .identity_scope import authoritative_scope
from .identity_association import associate_discovered_batch


def persist_verified_discovery_batch(
    db: sqlite3.Connection,
    *,
    tenant_id: str,
    connection_id: str,
    agents: list,
    receipt: DiscoveryReceipt,
    evidence_reference: str,
) -> dict[str, str]:
    """Persist inventory and canonical associations as one unit.

    Preconditions:
      - Normal GAMe database schema exists.
      - F01 identity schema already exists.
      - Receipt originates from trusted connector discovery.
      - Caller manages the surrounding database transaction.

    This function never executes DDL or commits the connection.
    """
    row = db.execute("""
        SELECT provider, scope_json, auth_mode, auth_config_json
        FROM provider_connections
        WHERE id=? AND tenant_id=?
    """, (connection_id, tenant_id)).fetchone()

    if row is None:
        raise IdentityConflict("Provider connection not found")

    configured = {
        "id": connection_id,
        "tenant_id": tenant_id,
        "provider": row["provider"],
        "scope": json.loads(row["scope_json"]),
        "auth_mode": row["auth_mode"],
        "auth_config": json.loads(row["auth_config_json"]),
    }

    # Verify the entire receipt before writing any inventory.
    verify_discovery_receipt(configured, agents, receipt)

    if not isinstance(evidence_reference, str) or not evidence_reference.strip():
        raise IdentityConflict("Discovery evidence reference is required")

    now = iso(utc_now())

    db.execute("SAVEPOINT f01_verified_persistence")
    try:
        for agent in agents:
            legacy_id = "ext-" + uuid4().hex

            db.execute("""
                INSERT INTO discovered_agents (
                    id, connection_id, external_id, name,
                    provider, description, provider_status,
                    discovered_at, discovery_last_seen,
                    created_at, tenant_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(connection_id, external_id)
                DO UPDATE SET
                    name=excluded.name,
                    provider=excluded.provider,
                    description=excluded.description,
                    provider_status=excluded.provider_status,
                    discovery_last_seen=excluded.discovery_last_seen
            """, (
                legacy_id,
                connection_id,
                agent.external_id,
                agent.name[:100],
                agent.provider[:100],
                agent.description[:500],
                agent.provider_status[:100],
                now, now, now, tenant_id,
            ))

            existing = db.execute("""
                SELECT id FROM discovered_agents
                WHERE connection_id=? AND tenant_id=?
                  AND external_id=?
            """, (
                connection_id, tenant_id, agent.external_id
            )).fetchone()

            if existing is None:
                raise IdentityConflict(
                    "Discovered inventory association failed"
                )

            legacy_id = existing["id"]

            reference = db.execute("""
                SELECT canonical_agent_id
                FROM agent_legacy_references
                WHERE tenant_id=?
                  AND source_table='discovered_agents'
                  AND legacy_agent_id=?
            """, (tenant_id, legacy_id)).fetchone()

            if reference is None:
                scope_key = authoritative_scope(configured)

                mapped = db.execute("""
                    SELECT canonical_agent_id, verification_status
                    FROM agent_identity_mappings
                    WHERE tenant_id=? AND provider=?
                      AND scope_key=? AND external_id=?
                """, (
                    tenant_id, configured["provider"],
                    scope_key, agent.external_id,
                )).fetchone()

                if mapped is not None:
                    if mapped["verification_status"] != "verified":
                        raise IdentityConflict(
                            "Existing external identity is not verified"
                        )
                    canonical_id = mapped["canonical_agent_id"]
                else:
                    canonical_id = "game-agt-" + uuid4().hex

                    db.execute("""
                        INSERT INTO canonical_agents
                        (id, tenant_id, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                    """, (canonical_id, tenant_id, now, now))

                db.execute("""
                    INSERT INTO agent_legacy_references
                    (tenant_id, source_table, legacy_agent_id,
                     canonical_agent_id, created_at)
                    VALUES (?, 'discovered_agents', ?, ?, ?)
                """, (
                    tenant_id, legacy_id, canonical_id, now
                ))

        associated = associate_discovered_batch(
            db,
            tenant_id=tenant_id,
            connection_id=connection_id,
            agents=agents,
            receipt=receipt,
            evidence_reference=evidence_reference,
        )

        db.execute("RELEASE SAVEPOINT f01_verified_persistence")
        return associated

    except Exception:
        db.execute("ROLLBACK TO SAVEPOINT f01_verified_persistence")
        db.execute("RELEASE SAVEPOINT f01_verified_persistence")
        raise
