#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Operator-only, offline tenant bootstrap. Never expose this as an unauthenticated API."""
import argparse
import os
import re
import sys
from pathlib import Path

# Runs from any directory after installing requirements; sets the source root for imports.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from game.db import connection, initialize, iso, utc_now  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description='Provision an isolated GAME tenant and first admin membership')
    parser.add_argument('--tenant-id', required=True, help='Unique slug e.g. example-corp')
    parser.add_argument('--name', required=True, help='Customer display name')
    parser.add_argument('--issuer', required=True, help='OIDC access token issuer (HTTPS)')
    parser.add_argument('--subject', required=True, help='OIDC access token sub for first tenant admin')
    args = parser.parse_args()
    issuer = args.issuer.rstrip('/')
    if not re.fullmatch(r'[a-z][a-z0-9-]{2,62}', args.tenant_id):
        parser.error('tenant-id must be a lower-case 3–63 character slug')
    if not issuer.startswith('https://') or not args.subject or len(args.subject)>300:
        parser.error('Issuer must be HTTPS and subject must be nonempty (max 300)')
    configured_issuer = os.getenv('GAME_OIDC_ISSUER', '').rstrip('/')
    if configured_issuer and configured_issuer != issuer:
        parser.error('Bootstrap issuer must match GAME_OIDC_ISSUER')
    if len(args.name) > 120:
        parser.error('Customer name too long')
    initialize()
    with connection() as db:
        existing = db.execute('SELECT id FROM tenants WHERE id=?', (args.tenant_id,)).fetchone()
        if existing:
            parser.error('Tenant already exists: refusing to modify its membership')
        db.execute('INSERT INTO tenants(id,name,created_at) VALUES(?,?,?)',
                   (args.tenant_id, args.name, iso(utc_now())))
        db.execute('INSERT INTO tenant_memberships(tenant_id,issuer,subject,role,active) VALUES(?,?,?,?,1)',
                   (args.tenant_id, issuer, args.subject, 'tenant_admin'))
    print(f'Tenant created: {args.tenant_id}\nRole: tenant_admin\nIssuer: {issuer}\nAdmin subject: {args.subject}')
    print('No passwords, cloud keys, or bearer tokens were generated.')


if __name__ == '__main__':
    main()
