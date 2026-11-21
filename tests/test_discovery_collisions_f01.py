# SPDX-License-Identifier: AGPL-3.0-only
"""F01: Reject ambiguous provider discovery batches."""

import pytest
from game.connectors import DiscoveredAgent
from game.identity import IdentityConflict, validate_discovery_batch


def test_duplicate_external_id_rejected():
    items = [
        DiscoveredAgent("agent-1", "Agent A", "Microsoft Foundry"),
        DiscoveredAgent("agent-1", "Agent B", "Microsoft Foundry"),
    ]

    with pytest.raises(IdentityConflict):
        validate_discovery_batch(items)


def test_unique_external_ids_accepted():
    items = [
        DiscoveredAgent("agent-1", "Agent A", "Microsoft Foundry"),
        DiscoveredAgent("agent-2", "Agent B", "Microsoft Foundry"),
    ]

    assert validate_discovery_batch(items) == 2


def test_empty_external_id_rejected():
    items = [
        DiscoveredAgent("", "Unnamed", "Microsoft Foundry"),
    ]

    with pytest.raises(IdentityConflict):
        validate_discovery_batch(items)


def test_empty_batch_accepted():
    assert validate_discovery_batch([]) == 0
