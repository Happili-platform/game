# SPDX-License-Identifier: AGPL-3.0-only
"""Single-company password login, account administration, and RBAC boundaries."""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from game.db import connection
from game.local_accounts import create_user
from game.main import app

ADMIN_PW='AdminControl-Secure-Passphrase-2026'
USER_PW='ViewerAccount-Secure-Passphrase-2026'

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('GAME_AUTH_MODE','password')
    monkeypatch.setenv('GAME_DB_PATH',str(tmp_path/'db.sqlite'))
    monkeypatch.setenv('GAME_VAULT_KEY_PATH',str(tmp_path/'vault.key'))
    with TestClient(app) as c:
        create_user('admin',ADMIN_PW,'admin',scope={'kind':'all'},must_change=False)
        yield c


def login(c,name='admin',password=ADMIN_PW):
    r=c.post('/api/auth/login',json={'username':name,'password':password})
    assert r.status_code==200,r.text
    return r.json()['csrf_token']


def test_login_requires_cookie_and_session_csrf(client):
    c=client
    assert c.get('/',follow_redirects=False).status_code==303
    assert c.get('/api/agents').status_code==401
    assert c.get('/api/local-users').status_code==401
    assert c.post('/api/auth/login',json={'username':'admin','password':'bad'}).status_code==401
    csrf=login(c)
    assert c.get('/').status_code==200
    assert c.get('/api/me').json()['role']=='admin'
    assert c.get('/api/local-users').status_code==200
    assert c.post('/api/connections',json={'provider':'aws_agentcore','label':'AWS','scope':{'region':'us-west-2'},'env_prefix':'AC_AWS'}).status_code==403
    assert c.post('/api/auth/logout',headers={'X-CSRF-Token':csrf}).status_code==200
    assert c.get('/api/agents').status_code==401


def test_password_change_requires_current_and_invalidates_session(client):
    c=client
    login(c)
    csrf=c.get('/api/auth/session').json()['csrf_token']
    assert c.post('/api/auth/change-password',headers={'X-CSRF-Token':csrf},json={'current_password':'wrong','new_password':USER_PW}).status_code==400
    assert c.post('/api/auth/change-password',headers={'X-CSRF-Token':csrf},json={'current_password':ADMIN_PW,'new_password':'short'}).status_code==422
    assert c.post('/api/auth/change-password',headers={'X-CSRF-Token':csrf},json={'current_password':ADMIN_PW,'new_password':USER_PW}).status_code==200
    assert c.get('/api/me').status_code==401
    assert c.post('/api/auth/login',json={'username':'admin','password':ADMIN_PW}).status_code==401
    login(c,'admin',USER_PW)


def test_admin_user_create_scoped_viewer_and_password_reset(client):
    c=client
    csrf=login(c)
    h={'X-CSRF-Token':csrf}
    r=c.post('/api/local-users',headers=h,json={
        'username':'viewer','display_name':'Viewer V','email':'viewer@example.test',
        'initial_password':USER_PW,'role':'viewer','scope':{'kind':'selected','connection_ids':[],'agent_ids':[]}})
    assert r.status_code==201,r.text
    user_id=r.json()['id']
    assert c.get('/api/local-users').json()[1]['username']=='viewer'
    assert 'password_hash' not in str(c.get('/api/local-users').json())
    c.post('/api/auth/logout',headers=h)
    vc=login(c,'viewer',USER_PW)
    assert c.get('/',follow_redirects=False).status_code==303
    assert '/password' in c.get('/',follow_redirects=False).headers['location']
    assert c.get('/api/me').status_code==403
    assert c.get('/api/local-users').status_code==403
    new='A-New-Great-Password-2026'
    assert c.post('/api/auth/change-password',headers={'X-CSRF-Token':vc},json={'current_password':USER_PW,'new_password':new}).status_code==200
    login(c,'viewer',new)
    assert c.get('/api/local-users').status_code==403
    c.cookies.clear()
    ac=login(c)
    assert c.post(f'/api/local-users/{user_id}/reset-password',headers={'X-CSRF-Token':ac},json={'temporary_password':'AnotherSecure-TempPass-2026'}).status_code==200
    assert c.patch(f'/api/local-users/{user_id}',headers={'X-CSRF-Token':ac},json={'active':False}).status_code==200
    assert c.post('/api/auth/login',json={'username':'viewer','password':'AnotherSecure-TempPass-2026'}).status_code==401


def test_admin_cannot_disable_or_demote_self_and_scope_is_validated(client):
    c=client
    csrf=login(c)
    h={'X-CSRF-Token':csrf}
    admin_id=c.get('/api/local-users').json()[0]['id']
    assert c.patch(f'/api/local-users/{admin_id}',headers=h,json={'active':False}).status_code==409
    assert c.patch(f'/api/local-users/{admin_id}',headers=h,json={'role':'viewer'}).status_code==409
    assert c.post('/api/local-users',headers=h,json={'username':'bad-scope','initial_password':USER_PW,'role':'viewer',
        'scope':{'kind':'selected','connection_ids':['nonexistent'],'agent_ids':[]}}).status_code==422


def test_sessions_survive_process_function_scope_not_plaintext(client):
    c=client
    csrf=login(c)
    r=c.get('/api/auth/session')
    assert r.json()['csrf_token']==csrf
    assert 'httponly' in c.post('/api/auth/login',json={'username':'admin','password':ADMIN_PW}).headers['set-cookie'].lower()
    with connection() as db:
        session=db.execute('SELECT * FROM local_sessions').fetchone()
        user=db.execute("SELECT * FROM local_users WHERE username='admin'").fetchone()
    assert session['token_hash'] and len(session['token_hash'])==64
    assert ADMIN_PW not in user['password_hash']
    assert user['password_hash'].startswith('$argon2id$')
    assert c.get('/api/auth/session').status_code==200


def test_login_attempts_are_throttled(client):
    c=client
    for i in range(8):
        assert c.post('/api/auth/login',json={'username':'admin','password':'bad'}).status_code==401
    assert c.post('/api/auth/login',json={'username':'admin','password':'bad'}).status_code==429
    assert c.post('/api/auth/login',json={'username':'admin','password':ADMIN_PW}).status_code==429
