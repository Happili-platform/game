# SPDX-License-Identifier: AGPL-3.0-only
"""Single-company branding is persistent, authenticated for edits and public only by name."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from game.db import connection, initialize
from game.local_accounts import create_user
from game.main import app
from game.version import __version__

PW = 'Valid-Long-Admin-Password-2026'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('GAME_AUTH_MODE', 'password')
    monkeypatch.setenv('GAME_DB_PATH', str(tmp_path / 'data.sqlite'))
    monkeypatch.setenv('GAME_VAULT_KEY_PATH', str(tmp_path / 'vault.key'))
    with TestClient(app) as c:
        create_user('administrator', PW, 'admin', scope={'kind': 'all'}, must_change=False)
        create_user('readerview', PW + '-viewer', 'viewer',
                    scope={'kind': 'selected', 'connection_ids': [], 'agent_ids': []}, must_change=False)
        yield c


def signin(c, username='administrator', pw=PW):
    response = c.post('/api/auth/login', json={'username': username, 'password': pw})
    assert response.status_code == 200
    return response.json()['csrf_token']


def test_branding_defaults_and_exact_login_wording(client):
    c = client
    response = c.get('/api/branding')
    assert response.status_code == 200
    assert response.json() == {'company_name': 'Company'}
    assert c.get('/api/company/settings').status_code == 401
    login = c.get('/login')
    assert login.status_code == 200
    assert 'id="companyAccessLabel">Company Access</p>' in login.text
    assert '<p class="auth-note">Supported by Happili Platform.' in login.text
    assert 'href="https://github.com/Happili-platform/game"' in login.text
    assert 'Source code (AGPLv3)</a>' in login.text
    assert 'SINGLE-COMPANY ACCESS' not in login.text
    assert 'First installation?' not in login.text


def test_admin_can_edit_and_name_survives_reinitialize(client):
    c = client
    csrf = signin(c)
    assert c.get('/api/company/settings').json()['company_name'] == 'Company'
    resp = c.patch('/api/company/settings', headers={'X-CSRF-Token': csrf},
                   json={'company_name': 'Happili & Co.'})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {'company_name': 'Happili & Co.'}
    assert c.get('/api/branding').json() == {'company_name': 'Happili & Co.'}
    assert c.get('/api/me').json()['tenant_name'] == 'Happili & Co.'
    # Rerun database startup migration, which must not reset the saved name.
    initialize()
    assert c.get('/api/branding').json() == {'company_name': 'Happili & Co.'}
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE operation='company.settings.update'").fetchone()[0] == 1


def test_company_branding_requires_admin_and_csrf(client):
    c = client
    assert c.patch('/api/company/settings', json={'company_name': 'X Corp'}).status_code == 401
    csrf = signin(c)
    assert c.patch('/api/company/settings', json={'company_name': 'X Corp'}).status_code == 403
    assert c.patch('/api/company/settings', headers={'X-CSRF-Token': csrf},
                   json={'company_name': '<script>alert(1)</script>'}).status_code == 422
    assert c.patch('/api/company/settings', headers={'X-CSRF-Token': csrf},
                   json={'company_name': 'A'}).status_code == 422
    assert c.get('/api/branding').json()['company_name'] == 'Company'
    assert c.post('/api/auth/logout', headers={'X-CSRF-Token': csrf}).status_code == 200
    signin(c, 'readerview', PW + '-viewer')
    assert c.get('/api/company/settings').status_code == 403
    assert c.patch('/api/company/settings', headers={'X-CSRF-Token': c.get('/api/auth/session').json()['csrf_token']},
                   json={'company_name': 'Other Corp'}).status_code == 403
    assert c.get('/api/branding').json()['company_name'] == 'Company'


def test_form_is_admin_area_and_use_text_content(client):
    root = Path(__file__).resolve().parents[1]
    index = (root/'static/index.html').read_text()
    script = (root/'static/app.js').read_text()
    assert index.index('<section id="usersView"') < index.index('id="companySettingsForm"') < index.index('id="localUsersPanel"')
    assert "$('#companyAccessPreview').textContent" in script
    assert "method:'PATCH'" in script
    assert f'/static/style.css?v={__version__}' in index


def test_auth_pages_use_current_stylesheet_version():
    root = Path(__file__).resolve().parents[1]
    for name in ('login.html', 'password.html'):
        html = (root / 'static' / name).read_text()
        assert f'/static/style.css?v={__version__}' in html
