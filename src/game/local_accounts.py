# SPDX-License-Identifier: AGPL-3.0-only
"""Single-company local password accounts: Argon2id, opaque DB-backed sessions, CSRF.

Development-only password identity provider. Never store passwords or session cookies in plaintext.
Do not confuse this with production SSO/MFA readiness.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import timedelta
from uuid import uuid4

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import HTTPException, Request

from .db import connection, iso, utc_now
from . import rbac

PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16, type=Type.ID)
COOKIE = 'game_session'
SESSION_HOURS = 8
IDLE_MINUTES = 60
MAX_PASSWORD_LENGTH = 256


def normalize_username(username: str) -> str:
    name = username.strip().casefold()
    if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{2,63}', name):
        raise ValueError('Username must contain 3–64 letters, digits, dots, underscores or hyphens')
    return name


def validate_password(value: str) -> None:
    # No prescriptive complexity: longer, unique passwords are easier to use safely.
    if not 15 <= len(value) <= MAX_PASSWORD_LENGTH:
        raise ValueError('Password must contain 15–256 characters')
    if value.strip() != value or '\x00' in value:
        raise ValueError('Password must not start or end with whitespace or contain null characters')
    if value.casefold() in ('passwordpassword', 'game12345', '123456789012345', 'qwertyuiopasdfg'):
        raise ValueError('Choose a less common password')


def hash_password(value: str) -> str:
    validate_password(value)
    return PASSWORD_HASHER.hash(value)


def verify_password(encoded: str, value: str) -> bool:
    try:
        return bool(PASSWORD_HASHER.verify(encoded, value))
    except (VerifyMismatchError, VerificationError, ValueError, TypeError):
        return False


def token_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_user(username: str, password: str, role: str, *, display_name: str = '', email: str = '',
                scope: dict | None = None, must_change: bool = True) -> dict:
    name = normalize_username(username)
    role = rbac.normalized_role(role)
    if role not in rbac.ROLES:
        raise ValueError('Invalid role')
    scope = scope or ({'kind':'all'} if role in ('admin','auditor') else {'kind':'selected','connection_ids':[],'agent_ids':[]})
    if role in ('admin','auditor') and scope.get('kind') != 'all':
        raise ValueError('Admin and Auditor require company-wide scope')
    secret_hash = hash_password(password)
    user_id = 'usr-' + uuid4().hex[:16]
    with connection() as db:
        db.execute('''INSERT INTO local_users (id, username, display_name, email, password_hash,
             role, scope_json, active, must_change_password, created_at, password_changed_at)
             VALUES (?,?,?,?,?,?,?,1,?,?,?)''',
             (user_id, name, display_name.strip()[:120], email.strip()[:254], secret_hash,
              role, json.dumps(scope), int(must_change), iso(utc_now()), iso(utc_now())))
    return {'id': user_id, 'username': name, 'role': role}


def session_user(request: Request, *, enforce_password_change: bool = True):
    raw = request.cookies.get(COOKIE, '')
    if not raw or len(raw) > 200:
        raise HTTPException(401, 'Login required')
    hashed = token_digest(raw)
    now = iso(utc_now())
    idle = iso(utc_now() - timedelta(minutes=IDLE_MINUTES))
    with connection() as db:
        row = db.execute('''SELECT u.*,s.csrf_token,s.expires_at FROM local_sessions s
              JOIN local_users u ON u.id=s.user_id
              WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>?
              AND s.last_seen_at>? AND u.active=1''', (hashed, now, idle)).fetchone()
        if not row:
            raise HTTPException(401, 'Login expired; sign in again')
        db.execute('UPDATE local_sessions SET last_seen_at=? WHERE token_hash=?', (now, hashed))
    if enforce_password_change and row['must_change_password']:
        raise HTTPException(403, 'Change your initial password before using GAME')
    return dict(row)


def check_csrf(request: Request, row: dict) -> None:
    value = request.headers.get('x-csrf-token', '')
    if not value or not hmac.compare_digest(value, row['csrf_token']):
        raise HTTPException(403, 'Invalid or missing CSRF token')
    origin = request.headers.get('origin')
    if origin:
        from urllib.parse import urlparse
        uri = urlparse(origin)
        if uri.scheme != request.url.scheme or uri.netloc != request.headers.get('host'):
            raise HTTPException(403, 'Cross-origin requests are not permitted')


def start_session(user_id: str):
    raw = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    now = utc_now()
    with connection() as db:
        db.execute('''INSERT INTO local_sessions(token_hash, user_id, csrf_token, created_at,
                last_seen_at, expires_at) VALUES (?,?,?,?,?,?)''',
                (token_digest(raw), user_id, csrf, iso(now), iso(now), iso(now + timedelta(hours=SESSION_HOURS))))
        db.execute('UPDATE local_users SET last_login_at=? WHERE id=?', (iso(now), user_id))
    return raw, csrf


def revoke_user_sessions(db, user_id: str):
    db.execute('UPDATE local_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL',
               (iso(utc_now()),user_id))


def login_attempt_key(username: str, ip: str) -> str:
    return token_digest(f'{username[:64]}|{ip[:70]}')


def authenticate(username: str, password: str, ip: str):
    # Limit both per username+IP and per client IP. Failed login never reveals which element was incorrect.
    name = username.strip().casefold()
    fingerprint = login_attempt_key(name, ip)
    ip_key = login_attempt_key('*', ip)
    since = iso(utc_now() - timedelta(minutes=15))
    with connection() as db:
        db.execute('DELETE FROM local_login_failures WHERE created_at<?', (since,))
        for key, limit in ((fingerprint, 8), (ip_key, 40)):
            count = db.execute('SELECT COUNT(*) FROM local_login_failures WHERE fingerprint=? AND created_at>=?', (key, since)).fetchone()[0]
            if count >= limit:
                raise HTTPException(429, 'Too many login attempts. Try again later')
        row = db.execute('SELECT * FROM local_users WHERE username=?', (name,)).fetchone()
        valid = row is not None and row['active'] and verify_password(row['password_hash'],password)
        if not valid:
            for key in (fingerprint, ip_key):
                db.execute('INSERT INTO local_login_failures(fingerprint,created_at) VALUES (?,?)',(key,iso(utc_now())))
        else:
            db.execute('DELETE FROM local_login_failures WHERE fingerprint=?', (fingerprint,))
    if not valid:
        raise HTTPException(401, 'Invalid username or password')
    return dict(row)


def public_user(row: dict):
    return {k: row[k] for k in ('id','username','display_name','email','role','active','must_change_password','created_at','last_login_at') if k in row}
