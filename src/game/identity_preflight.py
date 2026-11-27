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
    verified_project_number: str | None = None,
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

    # F01.13.2: Only Google Agent Engine has a validated
    # provider-resource binding in this increment.
    # AWS requires runtime STS account attestation; a role ARN
    # from configuration is not sufficient on its own.
    if provider != "google_agent_engine":
        return IdentityPreflight(
            False, provider, scope_key,
            "Provider-specific authenticated resource verification pending",
            count,
        )

    import re

    scope = connection.get("scope") or {}
    project = scope.get("project_id", "")
    location = scope.get("location", "")

    allowed_projects = {project}
    if (
        isinstance(verified_project_number, str)
        and re.fullmatch(r"[1-9][0-9]*", verified_project_number)
    ):
        allowed_projects.add(verified_project_number)

    resource_pattern = re.compile(
        r"projects/([^/]+)/locations/([^/]+)/"
        r"reasoningEngines/([A-Za-z0-9_-]+)"
    )

    for agent in agents:
        external_id = agent.external_id
        match = (
            resource_pattern.fullmatch(external_id)
            if isinstance(external_id, str)
            else None
        )
        if not (
            match
            and match.group(1) in allowed_projects
            and match.group(2) == location
        ):
            return IdentityPreflight(
                False, provider, scope_key,
                "Discovered resource does not match authenticated scope",
                count,
            )

    return IdentityPreflight(
        True, provider, scope_key,
        "Identity preflight passed",
        count,
    )
