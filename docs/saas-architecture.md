# OIDC API and Tenant Model — GAMe 0.3.2.2

**Status:** OIDC bearer-token validation and tenant-scoped API access are implemented. This document describes the current API mode and the production architecture still required; it does not describe a production-ready SaaS service. The browser experience uses local password accounts and does not provide OIDC sign-in.

## Current Tenant and Authorization Model

- Tenant IDs and memberships are provisioned in the database. A caller cannot create membership by supplying a tenant ID.
- Tenant-owned inventory, usage, provider connections, credentials, and audit records carry a tenant ID. API queries and mutations apply tenant and resource authorization in the application.
- OIDC access tokens are validated using the configured issuer, audience, and HTTPS JWKS endpoint. GAMe uses the verified issuer and subject to find active database memberships; caller-supplied role claims do not grant permissions.
- `X-GAME-Tenant` selects one of the caller's authorized memberships when the subject belongs to more than one tenant. The server verifies that membership before handling the request.
- Roles, capabilities, and resource scopes are enforced server-side. See [single-company-rbac.md](single-company-rbac.md) for the current role model.

This application-level tenant scoping is not a substitute for production database isolation, such as PostgreSQL row-level security and least-privilege database roles.

## OIDC API Configuration

Configure these values only in a controlled server environment:

```bash
GAME_AUTH_MODE=oidc
GAME_OIDC_ISSUER=https://your-trusted-idp.example/issuer
GAME_OIDC_AUDIENCE=api://game
GAME_OIDC_JWKS_URL=https://your-trusted-idp.example/.well-known/jwks.json
GAME_DB_PATH=/secured/path/game.db
```

The issuer and JWKS endpoint must be trusted operator configuration; the JWKS endpoint must use HTTPS. Use access tokens issued for the GAMe API. OIDC mode does not provide browser sessions or interactive enterprise login.

## Tenant Provisioning

The local operator script can provision a tenant and its initial OIDC membership:

```bash
python scripts/bootstrap_tenant.py \
  --tenant-id acme \
  --name 'Acme Corp' \
  --issuer 'https://your-trusted-idp.example/issuer' \
  --subject 'real-oidc-sub-from-verified-access-token'
```

The `--subject` value must match the subject (`sub`) in a verified token. Keep this script and the database available only to authorized operators. OIDC API members and audit endpoints are available only after valid authentication and authorization.

## Provider Connections

The current connector layer includes explicit-scope discovery for Microsoft Foundry, AWS Bedrock AgentCore, AWS Bedrock Agents Classic, and Google Agent Engine. Renewable AWS role assumption, Google service-account impersonation, and Microsoft shared-app token acquisition are implemented. The private registry supports authenticated inventory push. See [provider-workload-onboarding.md](provider-workload-onboarding.md) for prerequisites.

Connector implementations and mocked tests do not establish live provider compatibility, complete inventory coverage, or production workload identity readiness. Validate permissions and behavior with each authorized provider environment before a pilot.

## Production Work Still Required

- Browser OIDC Authorization Code with PKCE, MFA, secure session management, account lifecycle, and recovery.
- Production PostgreSQL, tenant-aware constraints, row-level security, migrations, backup/restore, and tenant deletion.
- Managed secret storage, key rotation, renewable host identity, and production credential operations.
- Scheduled connector workers with retry limits, quotas, monitoring, and incident handling.
- Rate limiting, deployment-level network controls, operational logs/metrics, retention policy, and security review.
- A tamper-evident audit archive, collector identity lifecycle, and customer-facing operational processes.

See [security-gaps.md](security-gaps.md) for the current production release gates.
