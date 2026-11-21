# SPDX-License-Identifier: AGPL-3.0-only
"""F01: Authoritative source scope requirements."""

import pytest

from game.identity import IdentityUnverified
from game.identity_scope import authoritative_scope


def test_google_scope_is_deterministic():
    connection = {
        "provider": "google_agent_engine",
        "scope": {
            "project_id": "my-sample-project",
            "location": "us-central1",
        },
        "auth_mode": "google_impersonate",
    }
    result = authoritative_scope(connection)

    assert result == (
        "gcp:projects/my-sample-project/"
        "locations/us-central1/agent-engine"
    )


def test_google_scope_is_independent_of_connection_id():
    connection = {
        "provider": "google_agent_engine",
        "scope": {
            "project_id": "my-sample-project",
            "location": "us-central1",
        },
    }
    a = authoritative_scope({**connection, "id": "conn-a"})
    b = authoritative_scope({**connection, "id": "conn-b"})
    assert a == b


def test_google_missing_project_fails_closed():
    with pytest.raises(IdentityUnverified):
        authoritative_scope({
            "provider": "google_agent_engine",
            "scope": {"location": "us-central1"},
        })


def test_aws_assume_role_uses_account_region_and_service():
    result = authoritative_scope({
        "provider": "aws_agentcore",
        "scope": {"region": "us-west-2"},
        "auth_mode": "aws_assume_role",
        "auth_config": {
            "role_arn": (
                "arn:aws:iam::123456789012:role/"
                "GAMEDiscoveryRole"
            )
        },
    })
    assert result == (
        "aws:aws:123456789012:us-west-2:agentcore"
    )


def test_aws_without_verified_account_fails_closed():
    with pytest.raises(IdentityUnverified):
        authoritative_scope({
            "provider": "aws_agentcore",
            "scope": {"region": "us-west-2"},
            "auth_mode": "legacy",
            "auth_config": {},
        })


def test_foundry_endpoint_alone_is_insufficient():
    with pytest.raises(IdentityUnverified):
        authoritative_scope({
            "provider": "microsoft_foundry",
            "scope": {
                "project_endpoint": (
                    "https://example.services.ai.azure.com/"
                    "api/projects/test"
                )
            },
        })


def test_unsupported_provider_fails_closed():
    with pytest.raises(IdentityUnverified):
        authoritative_scope({
            "provider": "github_inventory",
            "scope": {"organization": "Happili-platform"},
        })
