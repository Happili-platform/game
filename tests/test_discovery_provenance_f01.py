# SPDX-License-Identifier: AGPL-3.0-only
"""F01: Discovery receipt source and batch binding."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from game.discovery_provenance import (
    DiscoveryReceipt,
    _issue_connector_receipt,
    verify_discovery_receipt,
)
from game.identity import IdentityUnverified


PREFIX = (
    "projects/sample-project/locations/"
    "us-central1/reasoningEngines/"
)


def connection(**overrides):
    result = {
        "id": "conn-a",
        "tenant_id": "tenant-a",
        "provider": "google_agent_engine",
        "scope": {
            "project_id": "sample-project",
            "location": "us-central1",
        },
        "auth_mode": "legacy",
        "auth_config": {},
    }
    result.update(overrides)
    return result


def agents(*identifiers):
    return [
        SimpleNamespace(external_id=PREFIX + identifier)
        for identifier in identifiers
    ]


def test_matching_receipt_passes_contract():
    source = connection()
    batch = agents("1", "2")
    receipt = _issue_connector_receipt(source, batch)

    result = verify_discovery_receipt(
        source, list(reversed(batch)), receipt
    )

    assert result.eligible
    assert result.agent_count == 2


def test_missing_or_forged_receipt_fails():
    source = connection()
    batch = agents("1")

    with pytest.raises(IdentityUnverified):
        verify_discovery_receipt(source, batch, None)

    with pytest.raises(IdentityUnverified):
        DiscoveryReceipt(
            tenant_id="tenant-a",
            connection_id="conn-a",
            provider="google_agent_engine",
            scope_key="any",
            batch_fingerprint="fake",
            agent_count=1,
            _issuer=object(),
        )


@pytest.mark.parametrize(
    "change",
    [
        {"id": "conn-other"},
        {"tenant_id": "tenant-other"},
        {
            "scope": {
                "project_id": "other-project",
                "location": "us-central1",
            }
        },
    ],
)
def test_receipt_cannot_be_reused_for_another_source(change):
    source = connection()
    batch = agents("1")
    receipt = _issue_connector_receipt(source, batch)

    with pytest.raises(IdentityUnverified):
        verify_discovery_receipt(
            connection(**change), batch, receipt
        )


def test_receipt_cannot_be_reused_for_modified_batch():
    source = connection()
    receipt = _issue_connector_receipt(source, agents("1"))

    with pytest.raises(IdentityUnverified):
        verify_discovery_receipt(
            source, agents("1", "2"), receipt
        )


def test_invalid_resource_cannot_pass_with_internal_receipt():
    source = connection()
    invalid = [
        SimpleNamespace(external_id="agent-without-project")
    ]
    receipt = _issue_connector_receipt(source, invalid)

    with pytest.raises(IdentityUnverified):
        verify_discovery_receipt(source, invalid, receipt)


def test_tampered_receipt_fails():
    source = connection()
    batch = agents("1")
    receipt = _issue_connector_receipt(source, batch)

    with pytest.raises(IdentityUnverified):
        verify_discovery_receipt(
            source,
            batch,
            replace(receipt, batch_fingerprint="tampered"),
        )
