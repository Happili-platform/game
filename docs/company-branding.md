# GAMe 0.3.2.2 — Company Branding

**Status:** Implemented in 0.3.2.1 and included in the current 0.3.2.2 release. An Admin can set a persisted company display name for the local single-company browser experience. This does not add a Global Admin or multi-company administration.

## Configure the company name

1. Log in with an GAMe **Admin** account.
2. Open **Administration → Admin · Users & roles**.
3. In **Company settings**, enter a name (2–80 characters), e.g. `Happili FIRE`.
4. Select **Save company name**.
5. Sign out: the sign-in page will say **Happili FIRE Access**.

The sign-in footer reads exactly **Supported by Happili Platform.** and the empty `<div id="authError">` remains immediately below the Sign in button to display login errors. The password-change screen receives the same company branding and footer for consistency.

A new installation shows **Company Access** until configured. On upgrade, only the old default tenant label `Legacy / Local Development` is replaced with `Company`; any previously customized company name is preserved. The database record `tenants(id='local-dev')` stores the display name and is not reset on restart. Authentication and authorization continue to rely on immutable tenant IDs rather than the display name.

## API surface and security

- `GET /api/branding`: public, returns **only** `{"company_name":"..."}` for the login page (no other configuration, users, identities, or credentials).
- `GET /api/company/settings`: requires authenticated Admin with `members.manage`.
- `PATCH /api/company/settings`: requires Admin plus CSRF session protection in local-password mode. Body: `{"company_name":"Happili FIRE"}`. Validates length and disallows markup and control characters; changes are audit-logged as `company.settings.update`.
- Client renders the company name using `textContent`, never `innerHTML`.

The login page loads the name via `GET /api/branding`. This is a display preference only; it does not grant any permissions or create a company.

## Current release and upgrades

The current application version is `0.3.2.2`, reported by `src/VERSION` and `/api/health`. Follow the repository [README](../README.md) for a fresh local setup. Before applying an update to an existing installation, stop the app and back up both the SQLite database and its separate encryption key. Keep password mode enabled and bind the development server to `127.0.0.1`.
