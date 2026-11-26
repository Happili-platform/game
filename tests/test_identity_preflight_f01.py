# SPDX-License-Identifier: AGPL-3.0-only
"""F01: Automatic mapping must be gated by trusted evidence."""

import pytest

from game.identity import IdentityConflict
from game.identity_preflight import discovery_identity_preflight


class Agent:
    def __init__(self, external_id):
        self.external_id = external_id


GOOGLE = {
    "provider": "google_agent_engine",
    "scope": {
        "project_id": "sample-project",
        "location": "us-central1",
    },
    "auth_config": {},
}


def test_configuration_alone_is_not_verified():
    result = discovery_identity_preflight(
        GOOGLE, [Agent("agent-1")]
    )
    assert not result.eligible
    assert result.scope_key is not None


def test_trusted_verified_source_is_eligible():
    result = discovery_identity_preflight(
        GOOGLE,
        [Agent("projects/sample-project/locations/us-central1/reasoningEngines/12345")],
        authenticated_source_verified=True,
    )
    assert result.eligible
    assert result.agent_count == 1


def test_foundry_fails_closed_even_with_verification_flag():
    result = discovery_identity_preflight(
        {
            "provider": "microsoft_foundry",
            "scope": {
                "project_endpoint": "https://example.azure.com"
            },
            "auth_config": {},
        },
        [Agent("agent-1")],
        authenticated_source_verified=True,
    )
    assert not result.eligible


def test_github_inventory_is_not_treated_as_agent_identity():
    result = discovery_identity_preflight(
        {"provider": "github_inventory", "scope": {}},
        [Agent("repo-1")],
        authenticated_source_verified=True,
    )
    assert not result.eligible


def test_duplicate_external_ids_are_rejected():
    with pytest.raises(IdentityConflict):
        discovery_identity_preflight(
            GOOGLE,
            [Agent("agent-1"), Agent("agent-1")],
            authenticated_source_verified=True,
        )


def test_google_rejects_different_project():
    result = discovery_identity_preflight(
        GOOGLE,
        [Agent(
            "projects/other-project/locations/"
            "us-central1/reasoningEngines/12345"
        )],
        authenticated_source_verified=True,
    )
    assert not result.eligible


def test_google_rejects_different_location():
    result = discovery_identity_preflight(
        GOOGLE,
        [Agent(
            "projects/sample-project/locations/"
            "europe-west1/reasoningEngines/12345"
        )],
        authenticated_source_verified=True,
    )
    assert not result.eligible


def test_google_rejects_malformed_resource():
    result = discovery_identity_preflight(
        GOOGLE,
        [Agent("agent-123")],
        authenticated_source_verified=True,
    )
    assert not result.eligible


def test_google_rejects_extra_resource_path():
    result = discovery_identity_preflight(
        GOOGLE,
        [Agent(
            "projects/sample-project/locations/"
            "us-central1/reasoningEngines/12345/extra"
        )],
        authenticated_source_verified=True,
    )
    assert not result.eligible


def test_aws_stays_disabled_without_sts_attestation():
    result = discovery_identity_preflight(
        {
            "provider": "aws_agentcore",
            "scope": {"region": "us-east-1"},
            "auth_mode": "aws_assume_role",
            "auth_config": {
                "role_arn": (
                    "arn:aws:iam::123456789012:role/GAMeReadOnly"
                )
            },
        },
        [Agent(
            "arn:aws:bedrock-agentcore:us-east-1:"
            "123456789012:runtime/example"
        )],
        authenticated_source_verified=True,
    )
    assert not result.eligible
