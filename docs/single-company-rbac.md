# GAMe 0.3.2.2 — Roles and Resource Scopes

**Status:** Implemented. The local password-authenticated browser experience manages one company workspace. The separate OIDC API mode can resolve memberships across tenant IDs, but there is no multi-company browser console or Global Admin portal.

## Roles and automatic inheritance

| Selected role | Automatically included lower roles | Core abilities |
|---|---|---|
| Admin | Provider Admin, User / Agent Owner, Auditor, Viewer | Manage company users, all providers and agents; read audit trail |
| Provider Admin | User / Agent Owner, Viewer | Manage approved provider connections, run discovery, register agents |
| User / Agent Owner | Viewer | Register/manual-record activity for permitted agents; view own scope |
| Auditor | Viewer | Company-wide read and audit trail; cannot edit |
| Viewer | — | Read authorized connections, agents, governance findings and recorded costs |

In the **Users & roles** screen, choosing one primary role automatically checks *all* inherited roles and effective capabilities. These inherited checkboxes are read-only because they represent centrally defined and server-enforced access, not independently editable permissions. Roles are **not** simply a single ordinal hierarchy: Auditor is a separate read-only branch, which Admin also inherits. For example, Provider Admin does not automatically inherit Auditor's company-wide audit trail access.

The backend maintains a dependency graph. E.g. **Manage connections** ⇒ **Discover agents** ⇒ **View connections** and **View agents**. This is calculated server-side on every request; the browser does not submit a caller-selected capability set.

## Resource scopes

- `all`: full company scope. Mandatory for Admin and Auditor.
- `selected`: allowlisted connection IDs and/or agent IDs. A connection grant includes the discovered and manually linked agents in that connection. An agent grant allows that one agent, not its parent connection.
- A connection-scoped Provider Admin can manage/discover its assigned connections but cannot create new connections unless granted company-wide provider scope. **Removing a connection requires Admin**, even when scoped Provider Admin can edit it.
- A connection-scoped User / Agent Owner can register a manual agent only under an assigned connection. An Admin may create standalone manual inventory records.
- API authorization, resource list filtering, direct object access, recorded usage, and audit access are enforced on the backend. UI hiding is for ergonomics only.

## Authenticated user identities

The default browser flow uses local password accounts with Argon2id hashes for localhost development. Only Admin can create/disable users and manage roles. See [local-password-login.md](local-password-login.md). The separate OIDC mode validates API bearer tokens and uses database memberships; it does not provide interactive OIDC browser login.

Password mode is the default. The legacy `GAME_AUTH_MODE=local` bypass requires `GAME_ALLOW_INSECURE_LOCAL=true`, is loopback-restricted, and should only be used for controlled tests. It creates a local development Admin principal rather than logging in as a persisted user. You can inspect the role catalog at `/api/rbac/catalog` and the current effective permissions at `/api/me`.

For OIDC API testing, configure `GAME_AUTH_MODE=oidc` and the issuer, JWKS URL, and audience per [saas-architecture.md](saas-architecture.md), then use an authorized OIDC API client. Do **not** expose the local dashboard publicly; production browser SSO remains future work.

## Data preservation / seed behavior

- Existing SQLite provider connections, encrypted secrets, agents, usage and tenant membership IDs survive the in-place upgrade.
- The schema migration adds a scope to member records (existing roles default to company-wide for compatibility), and an optional `connection_id` to manual agents.
- Existing v0.3 roles `tenant_admin`, `connection_admin` and `analyst` continue working as aliases for Admin, Provider Admin and User / Agent Owner respectively.
- Demo seeding code is removed. New databases start empty regardless of `GAME_DEMO_DATA`. Existing demo rows are not deleted automatically because removing stored data during upgrade can be risky. Back up the database before manually cleaning legacy demo rows.
- Your local development credential master key remains separate under `~/.config/game/master.key` unless `GAME_VAULT_KEY_PATH` specifies another path. Back up both the database and key before upgrade.

## Current boundaries

This is still a local development and OIDC API prototype; no cross-company console, production hosted sign-in, production secret manager, PostgreSQL row-level security or automated credential provisioning. OIDC browser administration is not yet available. Capabilities that don't have implemented actions (such as policy editing and cloud agent shutdown) are deliberately excluded.

## Tests

`PYTHONPATH=src python -m pytest -q`

The current automated suite focuses on connector validation and discovery behavior, credential handling, API health/version reporting, and company branding. It does not constitute a complete authorization or production security assessment.
