# SPDX-License-Identifier: AGPL-3.0-only
"""Run once on the server: PYTHONPATH=src python scripts/create_local_admin.py"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from game.db import connection, initialize
from game.local_accounts import create_user


def main():
    initialize()
    with connection() as db:
        if db.execute("SELECT COUNT(*) FROM local_users WHERE role='admin' AND active=1").fetchone()[0]:
            raise SystemExit('An active local Admin already exists. Use Admin > Users & Roles to add others.')
    username=input('Initial Admin username: ').strip()
    password=getpass.getpass('Initial password (15+ characters): ')
    confirmation=getpass.getpass('Confirm password: ')
    if password != confirmation:
        raise SystemExit('Passwords do not match')
    try:
        created=create_user(username,password,'admin',scope={'kind':'all'},must_change=True)
    except Exception as exc:
        raise SystemExit(f'Admin not created: {exc}') from None
    print(f"Created Admin account: {created['username']}. Password change required on first sign-in.")

if __name__=='__main__':
    main()
