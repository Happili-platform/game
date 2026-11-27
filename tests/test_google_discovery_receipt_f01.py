# SPDX-License-Identifier: AGPL-3.0-only
"""F01: Google receipts require completed authenticated discovery."""

import io
import json
import sys
import types

import pytest

from game import connectors
from game.discovery_provenance import verify_discovery_receipt


PREFIX = (
    "projects/sample-project/locations/"
    "us-central1/reasoningEngines/"
)


def configured():
    return {
        "id": "conn-google",
        "tenant_id": "local-dev",
        "provider": "google_agent_engine",
        "scope": {
            "project_id": "sample-project",
            "location": "us-central1",
        },
        "auth_mode": "legacy",
        "auth_config": {},
        "env_prefix": "GAME_GOOGLE",
    }


def fake_google_auth(monkeypatch, *, fail_refresh=False):
    """Install isolated test doubles; never contact Google."""
    google = types.ModuleType("google")
    google.__path__ = []

    auth = types.ModuleType("google.auth")
    auth.__path__ = []

    transport = types.ModuleType("google.auth.transport")
    transport.__path__ = []

    requests = types.ModuleType(
        "google.auth.transport.requests"
    )
    requests.Request = lambda: object()

    oauth2 = types.ModuleType("google.oauth2")
    oauth2.__path__ = []

    service_account = types.ModuleType(
        "google.oauth2.service_account"
    )

    class Credentials:
        token = None

        def refresh(self, request):
            if fail_refresh:
                raise RuntimeError("Simulated token failure")
            self.token = "test-only-token"

    auth.default = lambda **kwargs: (Credentials(), "sample-project")
    transport.requests = requests
    auth.transport = transport
    oauth2.service_account = service_account
    google.auth = auth
    google.oauth2 = oauth2

    for module in (
        google, auth, transport, requests, oauth2, service_account
    ):
        monkeypatch.setitem(sys.modules, module.__name__, module)


def test_google_receipt_after_complete_paginated_discovery(monkeypatch):
    fake_google_auth(monkeypatch)

    import urllib.request

    responses = [
        {
            "reasoningEngines": [
                {"name": PREFIX + "1", "displayName": "First"}
            ],
            "nextPageToken": "page-two",
        },
        {
            "reasoningEngines": [
                {"name": PREFIX + "2", "displayName": "Second"}
            ],
        },
    ]

    def fake_urlopen(request, timeout):
        assert request.get_header("Authorization") == (
            "Bearer test-only-token"
        )
        assert timeout == 20
        return io.BytesIO(json.dumps(responses.pop(0)).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    source = configured()
    agents, receipt = connectors.discover_google_with_provenance(
        source
    )

    assert len(agents) == 2
    assert not responses
    assert verify_discovery_receipt(
        source, agents, receipt
    ).eligible


def test_google_authentication_failure_issues_no_receipt(monkeypatch):
    fake_google_auth(monkeypatch, fail_refresh=True)

    import urllib.request

    def forbidden_network(*args, **kwargs):
        raise AssertionError(
            "Provider API must not run after failed authentication"
        )

    monkeypatch.setattr(
        urllib.request, "urlopen", forbidden_network
    )

    with pytest.raises(
        connectors.DiscoveryError,
        match="OAuth token exchange failed",
    ):
        connectors.discover_google_with_provenance(configured())


def test_second_page_failure_does_not_return_receipt(monkeypatch):
    fake_google_auth(monkeypatch)

    import urllib.request

    calls = 0

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            return io.BytesIO(json.dumps({
                "reasoningEngines": [
                    {"name": PREFIX + "1"}
                ],
                "nextPageToken": "next",
            }).encode())
        raise OSError("Simulated provider outage")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(
        connectors.DiscoveryError,
        match="HTTPS request failed",
    ):
        connectors.discover_google_with_provenance(configured())

    assert calls == 2


def test_repeated_page_token_fails_closed(monkeypatch):
    fake_google_auth(monkeypatch)

    import urllib.request

    def fake_urlopen(request, timeout):
        return io.BytesIO(json.dumps({
            "reasoningEngines": [],
            "nextPageToken": "same-token",
        }).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(
        connectors.DiscoveryError,
        match="repeated pagination token",
    ):
        connectors.discover_google_with_provenance(configured())


def test_non_google_provider_cannot_issue_google_receipt():
    source = configured()
    source["provider"] = "aws_agentcore"

    with pytest.raises(
        connectors.DiscoveryError,
        match="not enabled",
    ):
        connectors.discover_google_with_provenance(source)


def test_verified_numeric_google_project_alias(monkeypatch):
    fake_google_auth(monkeypatch)

    import urllib.request

    numeric_resource = (
        "projects/268096427189/locations/us-central1/"
        "reasoningEngines/112461622701719552"
    )
    calls = []

    def fake_urlopen(request, timeout):
        url = request.full_url
        calls.append(url)
        assert request.get_header("Authorization") == (
            "Bearer test-only-token"
        )

        if "cloudresourcemanager.googleapis.com" in url:
            payload = {
                "projectId": "sample-project",
                "name": "projects/268096427189",
            }
        else:
            payload = {
                "reasoningEngines": [
                    {
                        "name": numeric_resource,
                        "displayName": "GAMe F01 Validation Agent",
                    }
                ]
            }
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(
        urllib.request, "urlopen", fake_urlopen
    )

    source = configured()
    agents, receipt = connectors.discover_google_with_provenance(
        source
    )

    assert len(agents) == 1
    assert agents[0].external_id == numeric_resource
    assert receipt.verified_project_number == "268096427189"
    assert verify_discovery_receipt(
        source, agents, receipt
    ).eligible
    assert len(calls) == 2


def test_unrelated_numeric_project_is_rejected(monkeypatch):
    fake_google_auth(monkeypatch)

    import urllib.request

    def fake_urlopen(request, timeout):
        if "cloudresourcemanager.googleapis.com" in request.full_url:
            payload = {
                "projectId": "sample-project",
                "name": "projects/268096427189",
            }
        else:
            payload = {
                "reasoningEngines": [{
                    "name": (
                        "projects/999999999999/locations/us-central1/"
                        "reasoningEngines/12345"
                    ),
                }]
            }
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(
        urllib.request, "urlopen", fake_urlopen
    )

    with pytest.raises(
        connectors.DiscoveryError,
        match="project identity mismatch",
    ):
        connectors.discover_google_with_provenance(configured())


def test_numeric_project_wrong_location_rejected(monkeypatch):
    fake_google_auth(monkeypatch)

    import urllib.request

    def fake_urlopen(request, timeout):
        assert "cloudresourcemanager" not in request.full_url
        return io.BytesIO(json.dumps({
            "reasoningEngines": [{
                "name": (
                    "projects/268096427189/locations/europe-west1/"
                    "reasoningEngines/12345"
                )
            }]
        }).encode())

    monkeypatch.setattr(
        urllib.request, "urlopen", fake_urlopen
    )

    with pytest.raises(
        connectors.DiscoveryError,
        match="different location",
    ):
        connectors.discover_google_with_provenance(configured())


def test_project_identity_lookup_mismatch_rejected(monkeypatch):
    fake_google_auth(monkeypatch)

    import urllib.request

    def fake_urlopen(request, timeout):
        if "cloudresourcemanager.googleapis.com" in request.full_url:
            payload = {
                "projectId": "other-project",
                "name": "projects/268096427189",
            }
        else:
            payload = {
                "reasoningEngines": [{
                    "name": (
                        "projects/268096427189/locations/us-central1/"
                        "reasoningEngines/12345"
                    )
                }]
            }
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(
        urllib.request, "urlopen", fake_urlopen
    )

    with pytest.raises(
        connectors.DiscoveryError,
        match="does not match configured scope",
    ):
        connectors.discover_google_with_provenance(configured())
