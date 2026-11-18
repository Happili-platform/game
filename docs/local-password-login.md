# GAMe 0.3.2.2 — Local Password Login

**Status:** Implemented for local development. The browser experience uses local password accounts in a single-company workspace. OIDC is available separately for API bearer authentication; browser-based enterprise SSO is not implemented. Do not expose password mode beyond loopback.

This guide covers the sign-in screen, Admin-only Users & Roles, operator-assisted Admin recovery, and self-service password changes. There is no Global/Super Admin or multi-company browser administration. A hosted production service requires enterprise SSO with MFA and additional security controls.

## Existing Installation Upgrade

1. Stop the running application. Back up `data/game.db` and the existing encryption key (`~/.config/game/master.key`, unless you configured a custom location).
2. Update the application source using your repository's normal update workflow. Preserve `data/` and `.venv/`.
3. From the repository root, activate `.venv`, run `python -m pip install -r requirements-connectors.txt`, and explicitly use password mode. Override any previous `GAME_AUTH_MODE=local` setting.
4. **One time only:** create your first Admin interactively. The script does not accept a password as a command-line argument and it does not print the password.

```bash
# Run these commands from the repository root.
source .venv/bin/activate
python -m pip install -r requirements-connectors.txt
PYTHONPATH=src python scripts/create_local_admin.py
GAME_AUTH_MODE=password PYTHONPATH=src python -m uvicorn game.main:app --host 127.0.0.1 --port 8000 --reload
```

Open `http://127.0.0.1:8000` and sign in. You will be forced to change the initial password, then sign in again. The login screen is at `/login`; the password-change screen is at `/password`.

## Roles and administration

- **Admin** alone sees **ADMINISTRATION → Admin · Users & Roles**, and alone can invoke `/api/local-users` CRUD/reset APIs.
- **Provider Admin, User / Agent Owner, Auditor, Viewer** see permitted company resources based on server-validated role inheritance and scopes. The existing connections and agents are unchanged.
- The Admin creates users with a temporary password (15+ characters). Their first login requires a change. Admins can edit role/scope and enable/disable accounts, or reset a password. Disabling an account revokes open sessions. Admins cannot deactivate or demote themselves or the last active Admin.
- Each user has **My password** and **Sign out** controls. Password changes invalidate all active sessions for that user.
- The Admin section is hidden from other roles **and** guarded by server-side RBAC, regardless of URL or frontend modifications.

## Security implementation

- Argon2id password hashes in SQLite; neither plaintext nor retrievable passwords are stored.
- Browser login uses an opaque random session ID with only its SHA-256 digest stored in SQLite; HttpOnly, SameSite=Strict cookie. `Secure` is set for HTTPS. Local HTTP on `127.0.0.1` is the sole development exception.
- Sessions have an 8-hour absolute lifetime and a 60-minute inactivity timeout.
- All mutating authenticated API calls require a CSRF header tied to the authenticated session.
- Database-backed failed-login throttling: eight failures per username/client IP, with an additional client-IP ceiling over 15 minutes.
- Initial Admin bootstrap is a local CLI operation, not a public API endpoint. There are no default usernames/passwords and no seeded users/agents.
- Audit records are written for user creation, change, password reset and password change. Credentials, password hashes and session IDs are excluded from public account responses.
- Explicit legacy local-admin bypass is restricted to loopback **and** requires `GAME_ALLOW_INSECURE_LOCAL=true`; do not enable it outside regression tests.
- No public password recovery email, MFA, identity-provider federation, invitation emails, or production password policy administration. Use OIDC mode for future hosted enterprise identity; full browser OIDC support remains a separate milestone.

## Development status and migration

`/api/health` and `src/VERSION` report `0.3.2.2`. Existing connection records, encrypted provider credentials, audit records, discovered agents and OIDC tenant memberships are retained by additive schema migrations. No database replacement is required. Existing records are not deleted during upgrade, and new databases are not seeded with demo records.

**Do not expose this development server directly to the Internet.** Before production SaaS, implement enterprise SSO with MFA, reset/invitation mail verification, session revocation monitoring, TLS termination, centralized secret management, security review, and PostgreSQL tenant isolation.

### Recovering the only Admin account

If the sole Admin forgets its password, a trusted operator with access to the **local server and SQLite database** can run:

```bash
PYTHONPATH=src python scripts/reset_local_admin_password.py
```

This requires interactive confirmation and a new password, marks it for change at next login, revokes sessions and writes an audit event. This is **not** an Internet-accessible password-reset API.
