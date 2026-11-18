# Security Status and Production Release Gates

**Applies to:** GAMe 0.3.2.2 | **Status:** Development prototype. Do not expose it as a publicly accessible, paid multi-tenant service.

## Implemented in the Current Release

- Local password authentication for the browser, with hashed passwords, session controls, CSRF checks, login throttling, and local operator bootstrap/recovery.
- Server-enforced roles and resource scopes for application requests.
- OIDC bearer-token validation and database-backed tenant membership for API mode. OIDC does not provide browser SSO.
- Tenant-scoped application queries, scoped provider connections, and authenticated private-registry ingestion.
- Encrypted local storage for provider credentials, with the key held separately from SQLite.
- Application audit events and a local audit view. The audit view is not tamper-evident or independently retained.

These are prototype controls, not a security certification or assurance that the service is safe for internet exposure.

## Required Before Production Hosting

1. Implement browser SSO with OIDC Authorization Code and PKCE, MFA, secure session lifecycle, account recovery, and enterprise identity lifecycle management.
2. Replace local SQLite with a production database architecture, including tenant-aware constraints, row-level security, least-privilege database roles, migrations, backup/restore, and per-tenant deletion.
3. Use a managed secrets and key service with tenant-aware policies, rotation, monitoring, and recovery. The local master key is not a production vault.
4. Configure and validate renewable host workload identities and least-privilege provider permissions in real customer environments. Current connector tests do not replace live integration testing.
5. Add scheduled discovery workers with bounded retry/backoff, rate limits, job ownership, cancellation, quotas, and operator visibility.
6. Add deployment-level egress controls and defense in depth for outbound provider calls, with explicit controls against unsafe destinations and credential exposure.
7. Implement ingress abuse controls, request-size limits, rate limiting, security headers, operational metrics, alerting, and incident response.
8. Provide tamper-evident audit retention/export, retention and deletion policies, and external audit or SIEM integration.
9. Complete independent testing for tenant isolation, authorization bypass, injection, CSRF, XSS, credential handling, and cloud confused-deputy risks.
10. Define production availability, disaster recovery, data residency, privacy, licensing, support, and compliance operations.

## Operational Guidance

- Keep password-mode development bound to `127.0.0.1`; do not expose the development server directly to the internet.
- OIDC tenant headers are selectors, not authorization. The server must validate the signed token and confirm active membership for every request.
- Prefer read-only provider roles. Discovery is on-demand and does not suspend or modify provider-side agents.
- Treat recorded costs and governance approvals as application-entered advisory data unless independently reconciled or integrated with the relevant external system.
- Back up the SQLite database and its encryption key separately. Without the matching key, encrypted provider credentials cannot be recovered.
