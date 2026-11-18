# SPDX-License-Identifier: AGPL-3.0-only
"""Local recovery only: reset existing Admin password from the machine hosting SQLite.

For users with trusted operating-system access to the GAME database.
No public password-reset endpoint and no command-line password arguments.
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from game.db import connection, initialize, iso, utc_now
from game.local_accounts import hash_password, normalize_username, revoke_user_sessions


def main():
    initialize()
    name=normalize_username(input('Existing Admin username: '))
    with connection() as db:
        row=db.execute('SELECT id FROM local_users WHERE username=? AND role=? AND active=1',(name,'admin')).fetchone()
    if not row:
        raise SystemExit('An active Admin with this username was not found')
    if input('Type RESET to invalidate all its sessions and force a new password: ').strip()!='RESET':
        raise SystemExit('Cancelled')
    pw=getpass.getpass('New temporary password (15+ characters): ')
    if pw!=getpass.getpass('Confirm temporary password: '):
        raise SystemExit('Passwords do not match')
    try: hashed=hash_password(pw)
    except ValueError as exc: raise SystemExit(str(exc)) from None
    with connection() as db:
        db.execute('UPDATE local_users SET password_hash=?,must_change_password=1,password_changed_at=? WHERE id=?',
                   (hashed,iso(utc_now()),row['id']))
        revoke_user_sessions(db,row['id'])
        db.execute('INSERT INTO audit_events(id,tenant_id,actor,operation,resource_id,occurred_at) VALUES (?,?,?,?,?,?)',
                   ('aud-'+uuid4().hex[:16],'local-dev','local-operator','local-admin.password.recovery',row['id'],iso(utc_now())))
    print('Admin password reset. All sessions revoked; password change required on next login.')

if __name__=='__main__':main()
