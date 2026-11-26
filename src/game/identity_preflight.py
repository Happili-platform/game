# SPDX-License-Identifier: AGPL-3.0-only
"""F01: Conservative eligibility checks for automatic identity mapping."""

from __future__ import annotations

from dataclasses import dataclass

from .identity import IdentityUnverified, validate_discovery_batch
from .identity_scope import authoritative_scope


@dataclass(frozen=True)
class IdentityPreflight:
    eligible: bool
    provider: str
    scope_key: str | None
    reason: str
    agent_count: int


def discovery_identity_preflight(
    connection: dict,
    agents: list,
    *,
    authenticated_source_verified: bool = False,
) -> IdentityPreflight:
    """Inspect discovery identity eligibility without database changes.

    The verification flag must originate from trusted server-side
    authentication evidence, never from a browser or caller payload.
    """
    validate_discovery_batch(agents)

    provider = connection.get("provider", "")
    count = len(agents)

    if provider in (
        "github_inventory",
        "atlassian_rovo_mcp",
        "custom_registry",
    ):
        return IdentityPreflight(
            False, provider, None,
            "Provider is not eligible for automatic agent identity mapping",
            count,
        )

    try:
        scope_key = authoritative_scope(connection)
    except IdentityUnverified:
        return IdentityPreflight(
            False, provider, None,
            "Authoritative provider scope is not established",
            count,
        )

    if not authenticated_source_verified:
        return IdentityPreflight(
            False, provider, scope_key,
            "Authenticated source identity has not been verified",
            count,
        )

    return IdentityPreflight(
        True, provider, scope_key,
        "Identity preflight passed",
        count,
    )
