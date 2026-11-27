# SPDX-License-Identifier: AGPL-3.0-only
"""Restricted local access for password-mode Docker deployments."""

import ipaddress
import os


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def permitted_local_request(request):
    client = request.client.host if request.client else ""
    host = request.url.hostname or ""

    if client == "testclient":
        return (
            os.getenv("GAME_TESTING") == "true"
            and host == "testserver"
        )

    if host not in LOCAL_HOSTS:
        return False

    if client in ("127.0.0.1", "::1"):
        return True

    gateway = os.getenv("GAME_LOCAL_DOCKER_GATEWAY", "").strip()

    if not gateway:
        return False

    try:
        configured = ipaddress.ip_address(gateway)
        actual = ipaddress.ip_address(client)
    except ValueError:
        return False

    return (
        configured == actual
        and configured.version == 4
        and configured.is_private
        and not configured.is_loopback
        and os.getenv("GAME_AUTH_MODE", "password").lower()
            == "password"
    )
