# SPDX-License-Identifier: AGPL-3.0-only
"""F01: Tenant-scoped canonical agent identity foundation.

This module is additive and does not alter existing GAMe agent
records, provider credentials, or historical references.
"""

from __future__ import annotations

import sqlite3
from uuid import uuid4

from .db import iso, utc_now


class IdentityError(Exception):
    """Base exception for identity resolution failures."""


class IdentityUnverified(IdentityError):
    """Required authoritative identity information is missing."""


class IdentityConflict(IdentityError):
    """An identity cannot safely be resolved or reassigned."""


def initialize_identity_schema(db: sqlite3.Connection) -> None:
    """Create additive identity tables. Safe to invoke repeatedly."""

    db.executescript("""
        CREATE TABLE IF NOT EXISTS canonical_agents (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_id, id)
        );

        CREATE INDEX IF NOT EXISTS idx_canonical_agents_tenant
            ON canonical_agents(tenant_id);

        CREATE TABLE IF NOT EXISTS agent_identity_mappings (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            canonical_agent_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            scope_key TEXT NOT NULL,
            external_id TEXT NOT NULL,
            connection_id TEXT,
            verification_status TEXT NOT NULL
                CHECK (verification_status IN (
                    'verified', 'pending', 'conflicted'
                )),
            evidence_reference TEXT NOT NULL,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,

            UNIQUE (
                tenant_id, provider, scope_key, external_id
            ),

            FOREIGN KEY (tenant_id, canonical_agent_id)
                REFERENCES canonical_agents(tenant_id, id)
                ON DELETE RESTRICT
        );

        CREATE INDEX IF NOT EXISTS idx_identity_mapping_agent
            ON agent_identity_mappings(
                tenant_id, canonical_agent_id
            );

        CREATE TABLE IF NOT EXISTS agent_legacy_references (
            tenant_id TEXT NOT NULL,
            source_table TEXT NOT NULL
                CHECK (source_table IN (
                    'agents', 'discovered_agents'
                )),
            legacy_agent_id TEXT NOT NULL,
            canonical_agent_id TEXT NOT NULL,
            created_at TEXT NOT NULL,

            PRIMARY KEY (
                tenant_id, source_table, legacy_agent_id
            ),

            FOREIGN KEY (tenant_id, canonical_agent_id)
                REFERENCES canonical_agents(tenant_id, id)
                ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS agent_identity_conflicts (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            scope_key TEXT NOT NULL,
            external_id TEXT NOT NULL,
            conflict_type TEXT NOT NULL,
            evidence_reference TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'resolved')),
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            resolved_by TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_identity_conflicts_tenant
            ON agent_identity_conflicts(tenant_id, status);
    """)


def _required(value: str | None, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IdentityUnverified(
            f"Authoritative identity field '{field}' is required"
        )
    # Do not normalize case or rewrite provider-issued IDs.
    return value.strip()


def resolve_external_identity(
    db: sqlite3.Connection,
    *,
    tenant_id: str,
    provider: str,
    scope_key: str,
    external_id: str,
    evidence_reference: str,
    connection_id: str | None = None,
    expected_canonical_id: str | None = None,
) -> str:
    """Resolve or create one immutable canonical identity.

    Exact verified provider identity is the only automatic
    matching criterion.

    A connection ID is observational metadata and is not part
    of the authoritative identity key.

    The caller owns the transaction. A savepoint ensures an
    unsuccessful resolution does not leave a partial identity.
    """

    tenant_id = _required(tenant_id, "tenant_id")
    provider = _required(provider, "provider")
    scope_key = _required(scope_key, "scope_key")
    external_id = _required(external_id, "external_id")
    evidence_reference = _required(
        evidence_reference, "evidence_reference"
    )

    now = iso(utc_now())

    db.execute("SAVEPOINT f01_identity_resolution")
    try:
        row = db.execute(
            """
            SELECT canonical_agent_id, verification_status
            FROM agent_identity_mappings
            WHERE tenant_id=?
              AND provider=?
              AND scope_key=?
              AND external_id=?
            """,
            (tenant_id, provider, scope_key, external_id),
        ).fetchone()

        if row is not None:
            if row["verification_status"] != "verified":
                raise IdentityConflict(
                    "Existing identity mapping is not verified"
                )

            canonical_id = row["canonical_agent_id"]

            if (
                expected_canonical_id is not None
                and expected_canonical_id != canonical_id
            ):
                raise IdentityConflict(
                    "External identity is already mapped to "
                    "a different canonical agent"
                )

            db.execute(
                """
                UPDATE agent_identity_mappings
                SET last_seen=?
                WHERE tenant_id=?
                  AND provider=?
                  AND scope_key=?
                  AND external_id=?
                """,
                (
                    now, tenant_id, provider,
                    scope_key, external_id,
                ),
            )
        else:
            if expected_canonical_id is not None:
                raise IdentityConflict(
                    "Expected canonical identity does not "
                    "have an existing verified mapping"
                )

            canonical_id = "game-agt-" + uuid4().hex

            db.execute(
                """
                INSERT INTO canonical_agents
                    (id, tenant_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (canonical_id, tenant_id, now, now),
            )

            db.execute(
                """
                INSERT INTO agent_identity_mappings (
                    id, tenant_id, canonical_agent_id,
                    provider, scope_key, external_id,
                    connection_id, verification_status,
                    evidence_reference, first_seen, last_seen
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'verified', ?, ?, ?)
                """,
                (
                    "map-" + uuid4().hex,
                    tenant_id,
                    canonical_id,
                    provider,
                    scope_key,
                    external_id,
                    connection_id,
                    evidence_reference,
                    now,
                    now,
                ),
            )

        db.execute("RELEASE SAVEPOINT f01_identity_resolution")
        return canonical_id

    except sqlite3.IntegrityError as exc:
        db.execute("ROLLBACK TO SAVEPOINT f01_identity_resolution")
        db.execute("RELEASE SAVEPOINT f01_identity_resolution")
        raise IdentityConflict(
            "Canonical identity constraint conflict"
        ) from exc

    except Exception:
        db.execute("ROLLBACK TO SAVEPOINT f01_identity_resolution")
        db.execute("RELEASE SAVEPOINT f01_identity_resolution")
        raise


def backfill_legacy_references(
    db: sqlite3.Connection,
) -> dict[str, int]:
    """Associate existing legacy agents with immutable identities.

    Preconditions:
    - Existing GAMe schema has been initialized.
    - F01 identity tables have been initialized.
    - Caller controls the database transaction.

    This function never updates or deletes legacy rows and never
    infers provider identity from names or incomplete scopes.
    """

    created = 0
    existing = 0
    now = iso(utc_now())

    # A savepoint makes the whole backfill atomic, including when
    # the caller is already inside a larger transaction.
    db.execute("SAVEPOINT f01_legacy_backfill")

    try:
        for table in ("agents", "discovered_agents"):
            rows = db.execute(
                f"""
                SELECT id, tenant_id
                FROM {table}
                ORDER BY tenant_id, id
                """
            ).fetchall()

            for row in rows:
                tenant_id = _required(
                    row["tenant_id"], "tenant_id"
                )
                legacy_id = _required(
                    row["id"], "legacy_agent_id"
                )

                found = db.execute(
                    """
                    SELECT canonical_agent_id
                    FROM agent_legacy_references
                    WHERE tenant_id=?
                      AND source_table=?
                      AND legacy_agent_id=?
                    """,
                    (tenant_id, table, legacy_id),
                ).fetchone()

                if found:
                    existing += 1
                    continue

                canonical_id = "game-agt-" + uuid4().hex

                db.execute(
                    """
                    INSERT INTO canonical_agents (
                        id, tenant_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (canonical_id, tenant_id, now, now),
                )

                db.execute(
                    """
                    INSERT INTO agent_legacy_references (
                        tenant_id,
                        source_table,
                        legacy_agent_id,
                        canonical_agent_id,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        tenant_id,
                        table,
                        legacy_id,
                        canonical_id,
                        now,
                    ),
                )

                created += 1

        db.execute("RELEASE SAVEPOINT f01_legacy_backfill")

        return {
            "created": created,
            "existing": existing,
        }

    except Exception:
        db.execute("ROLLBACK TO SAVEPOINT f01_legacy_backfill")
        db.execute("RELEASE SAVEPOINT f01_legacy_backfill")
        raise


def validate_discovery_batch(items) -> int:
    """Reject incomplete or duplicate external identities.

    Validate the complete provider response before any inventory
    database writes. Duplicate identities fail closed even when
    their other fields appear identical.
    """
    seen = set()

    for item in items:
        external_id = getattr(item, "external_id", None)

        if not isinstance(external_id, str) or not external_id.strip():
            raise IdentityConflict(
                "Discovery contains an empty external identity"
            )

        if external_id in seen:
            raise IdentityConflict(
                "Discovery contains duplicate external identities"
            )

        seen.add(external_id)

    return len(seen)


def bind_discovered_legacy_identity(
    db: sqlite3.Connection,
    *,
    tenant_id: str,
    legacy_agent_id: str,
    evidence_reference: str,
) -> str:
    """Bind a discovered legacy agent to an authoritative identity.

    Preconditions:
    - F01 tables exist and legacy backfill has run.
    - The provider connection is trusted and was validated.
    - Evidence comes from successful provider discovery.
    - Caller owns the transaction.

    Does not create canonical agents or alter historical agent IDs.
    """
    import json

    from .identity_scope import authoritative_scope

    tenant_id = _required(tenant_id, "tenant_id")
    legacy_agent_id = _required(legacy_agent_id, "legacy_agent_id")
    evidence_reference = _required(
        evidence_reference, "evidence_reference"
    )

    row = db.execute("""
        SELECT a.external_id, a.tenant_id, a.connection_id,
               c.provider, c.scope_json, c.auth_mode,
               c.auth_config_json
        FROM discovered_agents a
        JOIN provider_connections c
          ON c.id = a.connection_id
         AND c.tenant_id = a.tenant_id
        WHERE a.id=? AND a.tenant_id=?
    """, (legacy_agent_id, tenant_id)).fetchone()

    if row is None:
        raise IdentityConflict(
            "Discovered agent or provider connection not found"
        )

    reference = db.execute("""
        SELECT canonical_agent_id
        FROM agent_legacy_references
        WHERE tenant_id=?
          AND source_table='discovered_agents'
          AND legacy_agent_id=?
    """, (tenant_id, legacy_agent_id)).fetchone()

    if reference is None:
        raise IdentityConflict(
            "Legacy backfill must complete before identity binding"
        )

    connection_info = {
        "provider": row["provider"],
        "scope": json.loads(row["scope_json"]),
        "auth_mode": row["auth_mode"],
        "auth_config": json.loads(row["auth_config_json"]),
    }
    scope_key = authoritative_scope(connection_info)
    provider = row["provider"]
    external_id = _required(row["external_id"], "external_id")
    canonical_id = reference["canonical_agent_id"]

    existing = db.execute("""
        SELECT canonical_agent_id, verification_status
        FROM agent_identity_mappings
        WHERE tenant_id=? AND provider=?
          AND scope_key=? AND external_id=?
    """, (
        tenant_id, provider, scope_key, external_id
    )).fetchone()

    if existing is not None:
        if (
            existing["canonical_agent_id"] != canonical_id
            or existing["verification_status"] != "verified"
        ):
            raise IdentityConflict(
                "External identity conflicts with an existing mapping"
            )
        return canonical_id

    now = iso(utc_now())

    db.execute("SAVEPOINT f01_bind_legacy")
    try:
        db.execute("""
            INSERT INTO agent_identity_mappings (
                id, tenant_id, canonical_agent_id,
                provider, scope_key, external_id,
                connection_id, verification_status,
                evidence_reference, first_seen, last_seen
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'verified', ?, ?, ?)
        """, (
            "map-" + uuid4().hex,
            tenant_id, canonical_id, provider,
            scope_key, external_id, row["connection_id"],
            evidence_reference, now, now
        ))
        db.execute("RELEASE SAVEPOINT f01_bind_legacy")
    except sqlite3.IntegrityError as exc:
        db.execute("ROLLBACK TO SAVEPOINT f01_bind_legacy")
        db.execute("RELEASE SAVEPOINT f01_bind_legacy")
        raise IdentityConflict(
            "External identity mapping constraint conflict"
        ) from exc

    return canonical_id
