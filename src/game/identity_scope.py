# SPDX-License-Identifier: AGPL-3.0-only
"""F01: Conservative authoritative provider scope resolution."""

from __future__ import annotations

import re

from .identity import IdentityUnverified


def authoritative_scope(connection: dict) -> str:
    """Return a stable scope or reject insufficient evidence.

    This function accepts trusted, previously validated connection
    configuration, not arbitrary unauthenticated client input.

    It does not create canonical identities or modify SQLite.
    """

    provider = connection.get("provider")
    scope = connection.get("scope") or {}
    auth_config = connection.get("auth_config") or {}

    if not isinstance(scope, dict):
        raise IdentityUnverified("Invalid provider scope")

    if provider == "google_agent_engine":
        project = scope.get("project_id", "")
        location = scope.get("location", "")

        if not (
            isinstance(project, str)
            and re.fullmatch(r"[a-z][a-z0-9-]{4,62}", project)
            and isinstance(location, str)
            and re.fullmatch(r"[a-z0-9-]{2,64}", location)
        ):
            raise IdentityUnverified(
                "Google project and location are required"
            )

        return (
            f"gcp:projects/{project}/"
            f"locations/{location}/agent-engine"
        )

    if provider in ("aws_agentcore", "aws_bedrock_classic"):
        if connection.get("auth_mode") != "aws_assume_role":
            raise IdentityUnverified(
                "AWS account identity is not verified"
            )

        arn = auth_config.get("role_arn", "")
        region = scope.get("region", "")

        if not isinstance(arn, str) or not isinstance(region, str):
            raise IdentityUnverified("Invalid AWS identity metadata")

        match = re.fullmatch(
            r"arn:(aws|aws-us-gov|aws-cn):iam::"
            r"(\d{12}):role/[A-Za-z0-9+=,.@_/-]{1,300}",
            arn,
        )

        if not match or not re.fullmatch(
            r"[a-z]{2}(?:-[a-z]+)+-\d+", region
        ):
            raise IdentityUnverified(
                "AWS account and region are required"
            )

        partition, account = match.groups()
        service = (
            "agentcore" if provider == "aws_agentcore"
            else "bedrock-classic"
        )

        return f"aws:{partition}:{account}:{region}:{service}"

    raise IdentityUnverified(
        "Authoritative source scope is not established "
        "for this provider"
    )
