# SPDX-License-Identifier: AGPL-3.0-only
import io
import sys
import types
from urllib.error import HTTPError

import pytest
from game import connectors

CONFIG = {
    'provider': 'google_agent_engine',
    'scope': {'project_id': 'game-test-dev', 'location': 'us-central1'},
    'env_prefix': 'AC_GOOGLE',
}


class FakeCredentials:
    token = 'TEST-TOKEN-DO-NOT-USE'
    def refresh(self, _request):
        return None


@pytest.fixture(autouse=True)
def google_auth_stub(monkeypatch):
    """Exercise transport behavior even when Google SDK isn't installed in CI."""
    google = types.ModuleType('google')
    google.__path__ = []
    auth = types.ModuleType('google.auth')
    auth.__path__ = []
    transport = types.ModuleType('google.auth.transport')
    transport.__path__ = []
    requests = types.ModuleType('google.auth.transport.requests')
    requests.Request = lambda: object()
    oauth2 = types.ModuleType('google.oauth2')
    oauth2.__path__ = []
    service_account = types.ModuleType('google.oauth2.service_account')
    class Credentials:
        @staticmethod
        def from_service_account_info(key, scopes):
            return FakeCredentials()
    service_account.Credentials = Credentials
    oauth2.service_account = service_account
    google.auth = auth
    google.oauth2 = oauth2
    auth.transport = transport
    transport.requests = requests
    for name, module in {
        'google': google,
        'google.auth': auth,
        'google.auth.transport': transport,
        'google.auth.transport.requests': requests,
        'google.oauth2': oauth2,
        'google.oauth2.service_account': service_account,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)


def fake_creds(monkeypatch):
    from google.oauth2 import service_account
    monkeypatch.setattr(service_account.Credentials, 'from_service_account_info',
                        lambda key, scopes: FakeCredentials())


def test_google_uses_standard_https_transport_and_parses_agents(monkeypatch):
    fake_creds(monkeypatch)
    from urllib import request
    import json
    calls = []

    class Response:
        def __enter__(self):
            return io.BytesIO(json.dumps({'reasoningEngines': [
                {'name': 'projects/game-test-dev/locations/us-central1/reasoningEngines/123',
                 'displayName': 'Test Agent'}]}).encode())
        def __exit__(self, *a): pass

    def fake_urlopen(req, timeout=20):
        calls.append(req.full_url)
        assert 'Bearer TEST-TOKEN-DO-NOT-USE' == req.get_header('Authorization')
        return Response()

    monkeypatch.setattr(request, 'urlopen', fake_urlopen)
    found = connectors._google(CONFIG, google_credentials={'dummy': 'value'})
    assert len(found) == 1
    assert found[0].name == 'Test Agent'
    assert '/reasoningEngines?' in calls[0]


def test_google_http_permission_error_is_specific_without_secrets(monkeypatch):
    fake_creds(monkeypatch)
    from urllib import request
    def fail(req, timeout=20):
        raise HTTPError(req.full_url, 403, 'Sensitive detail', None, None)
    monkeypatch.setattr(request, 'urlopen', fail)
    with pytest.raises(connectors.DiscoveryError, match='HTTP 403') as err:
        connectors._google(CONFIG, google_credentials={'dummy': 'value'})
    assert 'Sensitive detail' not in str(err.value)


def test_google_oauth_failure_is_specific_and_sanitized(monkeypatch):
    from google.oauth2 import service_account
    class InvalidCredentials:
        token = None
        def refresh(self, request):
            raise RuntimeError('private_key=CONFIDENTIAL')
    monkeypatch.setattr(service_account.Credentials, 'from_service_account_info',
                        lambda key, scopes: InvalidCredentials())
    with pytest.raises(connectors.DiscoveryError, match='OAuth token exchange failed') as err:
        connectors._google(CONFIG, google_credentials={'dummy': 'value'})
    assert 'CONFIDENTIAL' not in str(err.value)
