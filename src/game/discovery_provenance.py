# SPDX-License-Identifier: AGPL-3.0-only
"""F01: Internal discovery receipt contract.

Receipts bind a completed discovery batch to its source.
They are not cryptographic attestations or proof of authentication.
Only trusted connector code may issue receipts after verifying its
provider-specific authentication and discovery requirements.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from .identity import IdentityUnverified, validate_discovery_batch
from .identity_preflight import (
    IdentityPreflight,
    discovery_identity_preflight,
)
from .identity_scope import authoritative_scope


_RECEIPT_ISSUER = object()


def _fingerprint(agents: list) -> str:
    validate_discovery_batch(agents)
    identifiers = sorted(agent.external_id for agent in agents)
    encoded = json.dumps(
        identifiers, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class DiscoveryReceipt:
    tenant_id: str
    connection_id: str
    provider: str
    scope_key: str
    batch_fingerprint: str
    agent_count: int
    _issuer: object
    verified_project_number: str | None = None

    def __post_init__(self):
        if self._issuer is not _RECEIPT_ISSUER:
            raise IdentityUnverified(
                "Discovery receipt was not issued internally"
            )


def _issue_connector_receipt(
    connection: dict,
    agents: list,
    *,
    verified_project_number: str | None = None,
) -> DiscoveryReceipt:
    """Internal issuance interface for future trusted connectors.

    Do NOT call directly from API routes, request data, tests that
    simulate authentication, or ordinary inventory ingestion.

    F01.13.4b will connect issuance to authenticated Google
    discovery. Until then this function is not used in production.
    """
    tenant_id = connection.get("tenant_id")
    connection_id = connection.get("id")
    provider = connection.get("provider")

    if not all(
        isinstance(value, str) and value.strip()
        for value in (tenant_id, connection_id, provider)
    ):
        raise IdentityUnverified(
            "Complete connection identity is required"
        )

    scope_key = authoritative_scope(connection)

    return DiscoveryReceipt(
        tenant_id=tenant_id,
        connection_id=connection_id,
        provider=provider,
        scope_key=scope_key,
        batch_fingerprint=_fingerprint(agents),
        agent_count=len(agents),
        _issuer=_RECEIPT_ISSUER,
        verified_project_number=verified_project_number,
    )


def verify_discovery_receipt(
    connection: dict,
    agents: list,
    receipt: DiscoveryReceipt | None,
) -> IdentityPreflight:
    """Verify exact receipt binding and resource eligibility."""
    if not isinstance(receipt, DiscoveryReceipt):
        raise IdentityUnverified(
            "Trusted discovery receipt is required"
        )

    if receipt._issuer is not _RECEIPT_ISSUER:
        raise IdentityUnverified("Untrusted discovery receipt")

    if (
        receipt.tenant_id != connection.get("tenant_id")
        or receipt.connection_id != connection.get("id")
        or receipt.provider != connection.get("provider")
        or receipt.scope_key != authoritative_scope(connection)
        or receipt.agent_count != len(agents)
        or receipt.batch_fingerprint != _fingerprint(agents)
    ):
        raise IdentityUnverified(
            "Discovery receipt does not match the source or batch"
        )

    result = discovery_identity_preflight(
        connection,
        agents,
        authenticated_source_verified=True,
        verified_project_number=receipt.verified_project_number,
    )

    if not result.eligible:
        raise IdentityUnverified(result.reason)

    return result
