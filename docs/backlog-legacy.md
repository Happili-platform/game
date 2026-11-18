# Prioritized backlog and release gates

## Sprint 0 — Completed prototype baseline

- [x] Simple responsive dashboard
- [x] Persistent local agent registry
- [x] Manual agent registration
- [x] Five transparent, advisory checks
- [x] Manual usage events and cost aggregation
- [x] Risk drilldown and cost visualization
- [x] API and automated smoke/unit tests
- [x] Docker Compose and local setup guide

## P0 — Required before *any* enterprise pilot with real data

- [ ] Identify buyer, data classification and pilot boundaries; secure sponsor and two candidate platforms.
- [ ] OIDC/SAML SSO, authorization/RBAC and per-user audit trail.
- [ ] Production-grade PostgreSQL and tenant boundary design.
- [ ] Secrets vault integration, TLS, retention and backups.
- [ ] Security review, threat model, vulnerability and dependency scanning.
- [ ] Public API schema, input validation, safe import/reconciliation and idempotent ingestion.
- [ ] Source provenance, last-synchronized status, evidence and stale/unknown semantics.
- [ ] Connector design for platform 1 and its least-privilege permission matrix.
- [ ] Connector design for platform 2 and its least-privilege permission matrix.
- [ ] Spending record reconciliation to provider billing systems.
- [ ] Agent ownership review/attestation workflow.

## P1 — Evidence-based production MVP

- [ ] Agent-to-application and agent-to-cost-center mapping.
- [ ] Structured OpenTelemetry adapter and version pinning.
- [ ] Policy configurability, review queue, exception expiry and evidence attachments.
- [ ] CSV/JSON export, SIEM event stream and Jira/ServiceNow ticket creation.
- [ ] Organization-level reporting, dashboard permissions, budget thresholds and alerts.
- [ ] Data reconciliation and automated end-to-end connector tests.

## P2 — Later differentiators

- [ ] Agent dependency graph (tools, MCP servers, data sources, models).
- [ ] Agent behavior and outcome evaluation with clear limitations.
- [ ] Provider-aware disable/pause integration where APIs safely support it, approval required.
- [ ] Evidence-backed cost per successful outcome and business KPI.
- [ ] Multi-tenant managed service and customer-operated deployment options.

## First pilot gate: evidence required

1. At least two supported agent ecosystems and a documented list of unsupported discovery scenarios.
2. Validated registry coverage against independent source inventories.
3. Security sign-off for connected privileges and enterprise data handling.
4. Reproducible, reconciled spend for one billing cycle.
5. Documented false positives/false negatives and limitations of risk rules.


## v0.3.0 tenant foundation — implemented, not production ready
- [x] Tenant-safe API scopes, roles, OIDC access-token verification, audit events
- [x] AWS STS cross-account assume role, generated external ID
- [x] Google host ADC service-account impersonation
- [x] Shared multi-tenant Microsoft Entra app token acquisition
- [x] Self-hosted registry authenticated push metadata ingestion
- [ ] Browser OIDC PKCE + production database RLS + security review
- [ ] Scheduled discovery, queue, retry, quota and operator dashboards
- [ ] Real multi-cloud pilot for all renewable auth paths
