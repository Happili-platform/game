# SPDX-License-Identifier: AGPL-3.0-only
"""Legacy API tests explicitly exercise the previous loopback-local mode.
New password-auth tests override to password mode.
"""
import pytest

@pytest.fixture(autouse=True)
def legacy_auth_mode_for_test(monkeypatch):
    monkeypatch.setenv('GAME_TESTING', 'true')
    monkeypatch.setenv('GAME_AUTH_MODE','local')
    monkeypatch.setenv('GAME_ALLOW_INSECURE_LOCAL','true')
