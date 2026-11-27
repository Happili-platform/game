# SPDX-License-Identifier: AGPL-3.0-only

import pytest
from starlette.requests import Request

from game.local_network import permitted_local_request


def request(client, host="127.0.0.1:8000"):
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/health",
        "scheme": "http",
        "headers": [(b"host", host.encode())],
        "client": (client, 50000),
        "server": ("127.0.0.1", 8000),
        "query_string": b"",
    })


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("GAME_AUTH_MODE", "password")
    monkeypatch.setenv(
        "GAME_LOCAL_DOCKER_GATEWAY", "172.18.0.1"
    )


def test_docker_gateway_allowed():
    assert permitted_local_request(request("172.18.0.1"))


def test_normal_loopback_allowed():
    assert permitted_local_request(request("127.0.0.1"))


def test_other_container_rejected():
    assert not permitted_local_request(request("172.18.0.2"))


def test_remote_host_header_rejected():
    assert not permitted_local_request(
        request("172.18.0.1", "example.com")
    )


def test_unconfigured_gateway_rejected(monkeypatch):
    monkeypatch.delenv("GAME_LOCAL_DOCKER_GATEWAY")
    assert not permitted_local_request(request("172.18.0.1"))


def test_non_password_mode_rejected(monkeypatch):
    monkeypatch.setenv("GAME_AUTH_MODE", "oidc")
    assert not permitted_local_request(request("172.18.0.1"))


def test_invalid_gateway_rejected(monkeypatch):
    monkeypatch.setenv(
        "GAME_LOCAL_DOCKER_GATEWAY", "not-an-ip"
    )
    assert not permitted_local_request(request("172.18.0.1"))


def test_testclient_requires_testing_flag(monkeypatch):
    monkeypatch.delenv("GAME_TESTING", raising=False)

    assert not permitted_local_request(
        request("testclient", "testserver")
    )


def test_testclient_permitted_only_in_testing_mode(monkeypatch):
    monkeypatch.setenv("GAME_TESTING", "true")

    assert permitted_local_request(
        request("testclient", "testserver")
    )


def test_testclient_rejects_unexpected_host(monkeypatch):
    monkeypatch.setenv("GAME_TESTING", "true")

    assert not permitted_local_request(
        request("testclient", "example.com")
    )
