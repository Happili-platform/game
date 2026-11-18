# SPDX-License-Identifier: AGPL-3.0-only
"""Tenant identity for local development and independently verified OIDC API tokens.

Never accept a tenant ID from a caller without checking tenant membership in SQLite.
The local mode is loopback-only and deliberately *not* a multi-tenant SaaS login.
"""
from __future__ import annotations

import os
import json
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

from fastapi import HTTPException, Request

from .db import connection
from . import rbac, local_accounts

LOCAL_TENANT = 'local-dev'


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    subject: str
    role: str
    scope: dict | None = None
    capabilities: frozenset[str] | None = None


def _mode() -> str:
    mode = os.getenv('GAME_AUTH_MODE', 'password').lower()
    if mode not in ('local', 'oidc', 'password'):
        raise RuntimeError('GAME_AUTH_MODE must be password, local, or oidc')
    if mode == 'local' and os.getenv('GAME_ALLOW_INSECURE_LOCAL') != 'true':
        raise RuntimeError('Insecure local bypass is disabled; use password mode or explicitly opt in for tests')
    return mode


@lru_cache(maxsize=8)
def _get_jwk_client(jwks_url: str):
    from jwt import PyJWKClient
    return PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=300)


def _oidc_claims(request: Request) -> tuple[str, str]:
    # OIDC access token must be issued FOR GAME, not an arbitrary ID token.
    try:
        import jwt
        from jwt import PyJWKClient
    except ImportError:
        raise HTTPException(503, 'OIDC JWT verifier dependency missing') from None
    issuer = os.getenv('GAME_OIDC_ISSUER', '').rstrip('/')
    audience = os.getenv('GAME_OIDC_AUDIENCE', '')
    jwks_url = os.getenv('GAME_OIDC_JWKS_URL', '')
    if not (issuer and audience and jwks_url):
        raise HTTPException(503, 'OIDC verifier is not configured')
    origin = urlparse(jwks_url)
    if origin.scheme != 'https' or not origin.hostname or origin.username or origin.password or origin.port not in (None, 443):
        raise HTTPException(503, 'OIDC JWKS URL must be HTTPS')
    if not issuer.startswith('https://'):
        raise HTTPException(503, 'OIDC issuer must be HTTPS')
    header = request.headers.get('authorization', '')
    if not header.startswith('Bearer ') or not header[7:].strip():
        raise HTTPException(401, 'An OIDC Bearer access token is required', headers={'WWW-Authenticate': 'Bearer'})
    token = header[7:].strip()
    try:
        # Never allow unsigned JWTs, token-selected URLs, or caller-selected algorithms.
        key = _get_jwk_client(jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=['RS256'], issuer=issuer, audience=audience,
                            options={'require': ['exp', 'iat', 'sub', 'iss', 'aud']}, leeway=30)
    except Exception:
        raise HTTPException(401, 'OIDC access token invalid or expired') from None
    subject = claims.get('sub')
    if not isinstance(subject, str) or not subject:
        raise HTTPException(401, 'OIDC subject missing')
    return issuer, subject


def current_principal(request: Request) -> Principal:
    if _mode() == 'password':
        row = local_accounts.session_user(request)
        if request.method.upper() not in ('GET', 'HEAD', 'OPTIONS'):
            local_accounts.check_csrf(request, row)
        return Principal(LOCAL_TENANT, 'local-user:' + row['id'], row['role'], json.loads(row['scope_json']),
                         frozenset(json.loads(row['capabilities_json'])) if row.get('capabilities_json') is not None else None)
    if _mode() == 'local':
        client = request.client.host if request.client else ''
        host = request.url.hostname or ''
        is_local = client in ('127.0.0.1', '::1') and host in ('localhost', '127.0.0.1', '::1')
        is_test = client == 'testclient' and (os.getenv('GAME_TESTING') == 'true' or bool(os.getenv('PYTEST_CURRENT_TEST')))
        if not (is_local or is_test):
            raise HTTPException(403, 'Local development mode is restricted to loopback')
        return Principal(LOCAL_TENANT, 'local-development', 'admin', {'kind': 'all'})

    issuer, subject = _oidc_claims(request)
    tenant_header = request.headers.get('x-game-tenant')
    with connection() as db:
        rows = db.execute('''SELECT m.tenant_id, m.role, m.scope_json FROM tenant_memberships m
             JOIN tenants t ON t.id=m.tenant_id WHERE m.issuer=? AND m.subject=?
             AND m.active=1 AND t.active=1''', (issuer, subject)).fetchall()
    if tenant_header:
        rows = [r for r in rows if r['tenant_id'] == tenant_header]
    if not rows:
        raise HTTPException(403, 'No active membership for this tenant')
    if len(rows) != 1:
        raise HTTPException(400, 'Set X-GAME-Tenant to an authorized tenant ID')
    return Principal(rows[0]['tenant_id'], subject, rows[0]['role'], json.loads(rows[0]['scope_json']))


LEGACY_REQUIRE = {
    'viewer': 'agents.view',
    'analyst': 'agents.register',
    'connection_admin': 'connections.manage',
    'tenant_admin': 'members.manage',
}


def permits_resource(actor: Principal, connection_id: str | None = None, agent_id: str | None = None) -> bool:
    scope = actor.scope or {'kind': 'all'}
    if scope.get('kind') == 'all':
        return True
    if scope.get('kind') != 'selected':
        return False
    return bool((connection_id and connection_id in scope.get('connection_ids', []))
                or (agent_id and agent_id in scope.get('agent_ids', [])))


def require(request: Request, minimum: str = 'viewer') -> Principal:
    principal = current_principal(request)
    capability = LEGACY_REQUIRE.get(minimum, minimum)
    if capability not in (principal.capabilities if principal.capabilities is not None else rbac.effective_capabilities(principal.role)):
        raise HTTPException(403, 'Insufficient company permission')
    return principal


def require_resource(actor: Principal, connection_id: str | None = None, agent_id: str | None = None) -> None:
    if not permits_resource(actor, connection_id, agent_id):
        raise HTTPException(404, 'Resource not found')

