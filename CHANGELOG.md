## v0.3.5 — Provider filter and Trust Graph zoom (Nov 11, 2026)
- Added dynamically populated provider selector, resource text search and filtered row counts for GitHub/Atlassian provider inventory, including multiple connections of each type.
- Added Trust Graph Zoom In, Zoom Out and Fit to View controls, with responsive, scrollable graph viewport and percentage readout.
- Preserved all evidence/inventory data, authentication and provider connectors. No database migrations or API changes.
- Included missing `src/VERSION` in source release to satisfy existing version contract.

## v0.3.5 — Trust Graph UI increment (Nov 11, 2026)
- Added Trust Graph to Workspace navigation with role-aware `agents.view` visibility.
- Added read-only Graph, Inventory and Evidence tabs with evidence filters, search and selectable nodes.
- Added truthful empty/error states, source reference labels, provider connection attribution and bounded graph layout.
- No new provider access, API writes, automated execution claims, or fake telemetry.
- Asset cache-busting updated without changing database schema.

## 0.3.5 — Trust Graph foundation increment (2026-11-11)

- Added tenant-scoped, read-only Trust Graph query API and authenticated provider tool snapshot/agent evidence link ingestion.
- Added deterministic tool identity, upsert/deduplication, audit events and scoped access enforcement.
- Added GitHub/Atlassian provider configuration guide, clearly separating proposed native integrations from completed API foundation.
- No remote provider connectors, tool invocations, automated enforcement, or inferred usage evidence.

## v0.3.5 — Azure Foundry telemetry completeness (2026-11-11)

- Preserve v0.3.4.2 RBAC, FinOps, agent registry, and automatic discovery as the release baseline.
- Automatically subdivide saturated Azure Monitor Logs query windows into bounded, half-open time ranges.
- Fail closed when a one-second window still reaches the query cap, the query budget is exhausted, or a subdivision fails; do not silently import incomplete results.
- Retain existing collector deduplication, identity ambiguity rejection, metadata allowlist and collection heartbeat.
- No new providers, hosted production authentication, durable cursor, or live-cloud verification claimed in this release.

## v0.3.4.1 — Azure Cost Management ActualCost (2026-11-10)

- Added read-only Azure ARM Cost Management query CLI for resource-scope daily ActualCost.
- Added tenant-scoped UPSERT storage and authenticated ingestion, cost retrieval API and an independent FinOps resource cost table.
- Costs remain separate from Foundry agent usage and configured rate estimates. Does not represent final invoicing or per-agent attribution.
- Added documentation and deterministic regression tests. Preserved existing runtime collection, approval rules, frontend theme, and GitHub Actions.

## v0.3.4.0 — FinOps data foundation (2026-11-09)

- Azure Application Insights model token usage ingestion, linked to actual runtime traces and deduplicated.
- Scoped FinOps API/dashboard; explicit partial-data and Not tracked presentation.
- Admin-configured documented estimate rates, no automatic pricing assumptions and no invoice-reconciled charges.
- Separate Business Owner-approved budget reporting, original RBAC, runtime traces and Happili branding preserved.
- No demo seeded records. Live Azure token telemetry integration pending verification.

## v0.3.3 — Runtime Observability Foundation (November 2026)
- Rebased on the user-supplied v0.3.2.2 source; retained `.github/workflows/python-app.yml` unchanged and preserved original locally modified tests.
- Carries forward v0.3.2.3 Advisory Policy and CVE features as required by the runtime release.
- Additive, company-scoped runtime runs/spans metadata persisted in SQLite; no seeded executions.
- Collector-token-authenticated, loopback-only normalized run ingestion, replay deduplication and partial spans.
- Scoped read APIs plus Runtime observability dashboard for actual runs, outcome coverage, p95 latency and traces.
- Unknown metrics remain Not tracked; business approvals, policy rules and existing provider credentials unchanged.
- Provider collectors, OTLP translation and live Microsoft/AWS/Google telemetry validation are NOT shipped in this increment.
- Footer remains `GAMe 0.3.3 · Supported by Happili Platform`.

## v0.3.2.3 — Advisory Policy Framework and CVE reference linking

- Replaced the static Policy Checks list with an Admin-configurable catalog of 10 deterministic advisory rules. Rules support enable/disable and severity; inactivity days are configurable for the stale-agent rule.
- Recorded policy-evaluation snapshots and finding history, with evidence, timestamps, resolving state, and audited remediation notes/due dates. Remediation does not automatically suppress findings or act on provider agents.
- Added optional CVE references per agent: identifier, component/version, assessment status, evidence source, authorized editor and an official NVD link.
- A link under review is informational. Only a user-reported affected component with a version and supporting evidence triggers `REPORTED_AFFECTED_CVE`; this is not a verified security scan.
- Does not fetch CVSS scores yet, automatically match vulnerable versions, or determine actual exploitability. See `docs/advisory-policy-and-vulnerability-intelligence.md` for the NVD/CVSS/KEV/EPSS roadmap.
- Discovered agents with no usage integration show **Not tracked**, not misleading `$0` spend; unknown provider metadata is not treated as proof of compliance.
- No seeded demo agents; preserved Business Owner approval, audit log, persistent credentials and `Supported by Happili Platform` branding.

# Changelog

## v0.3.2.1 — company branding (November 2026)

- Admin-only company name setting, persisted to the existing single-company tenant record.
- Dynamic `Company Name Access` login label and consistent password-change branding.
- Sign-in footer changed to `Supported by Happili Platform.`
- Application footer updated to `GAMe 0.3.2.1 · Supported by Happili Platform`.
- Public read-only branding endpoint, authenticated/CSRF-protected setting update, audit trail.
- Retains existing sessions, user accounts, provider connections and encrypted credentials.


## v0.3.2 — Single-company login and password administration (November 2026)

- Added login and password change pages with Argon2id local password accounts.
- Added one-time operator CLI for creating the first Admin account (no default password).
- Placed Users & Roles under an Admin-only section and added create/edit/disable/reset for local users.
- Added secure cookie sessions, CSRF protection, login throttling, mandatory initial password change and session revocation.
- Preserved the v0.3.1 single-company role/capability hierarchy and resource-scoped APIs.
- Kept existing provider connections, encrypted credentials and agent inventory through additive migration; no demo seeding.
- Password mode is localhost-only for development. Enterprise SSO remains required for hosted use.

## 0.3.2.2 — Business approvals and Admin audit log
- Added independent `Business Owner` role with no approval inheritance to technical Admin.
- Admin/Provider Admin may assign accountable Business Owners; requesters submit cost center, requested monthly budget and business justification.
- Only assigned, active Business Owner can approve or reject pending requests; decisions and reasons are audited.
- Added **Administration → Audit Log** for technical Admin and Auditor with action filters and search.
- Business-approval metadata is stored separately from provider-reported metadata; registration cannot self-approve.
- Preserved the footer: `GAMe 0.3.2.2 · Supported by Happili Platform`.
- Existing provider connections, secrets, accounts and sessions are retained by an additive SQLite migration.

### v0.3.3 — Azure Foundry telemetry collector increment (2026-11-06)

- Added `scripts/collect_azure_foundry.py`, a **read-only Azure Monitor Logs API** collector using Azure CLI or client-credential Entra authentication.
- Maps actual Foundry agent trace metadata to existing GAMe agent IDs via explicit local JSON mapping; skips unknown and ambiguous traces.
- Normalizes timestamp, observed status and trace/span metadata for `POST /api/runtime/ingest`; dry-run, deduplication and bounded query windows; no fabricated runtime data.
- Added `docs/azure-foundry-telemetry-collector.md` and collector unit tests. Azure tenant live integration remains unverified.
- Retained the existing user-provided GitHub Actions workflow and all single-company governance/branding features.

### v0.3.3 — Runtime Observability enhancements (2026-11-09)
- Added historical totals vs selected periods (24 hours, 7 days, 30 days, all), UTC daily execution trends, clearer unknown outcome counts, and per-agent filters.
- Added additive SQLite `runtime_collection_status` with authenticated collector heartbeat; zero-row collections are tracked without deleting previously imported traces.
- Extended Azure request outcome detection using `ResultCode` only when `Success` is missing; no business-success inference from tool calls.
- Added opt-in macOS launchd helper and overlap polling; see `docs/runtime-observability-enhancements.md`.
- Existing GitHub Actions workflow, user identities, provider connections, secret vault and branding retained.

- v0.3.3: automatic Microsoft Foundry inventory synchronization and unique agent-identity matching for Azure runtime collection. Legacy manual mapping is optional; macOS scheduler no longer requires it.

## 0.3.4.2 — Financial access and permission editing
- Split runtime, token-usage, estimate, and enterprise Azure ActualCost read permissions.
- Editable existing local-user capability restrictions with automatic prerequisite selection and server validation.
- Hide restricted navigation/sections; enforce business-owner assignment and agent scope on API responses.

## v0.3.5 — GitHub + Atlassian Provider Inventory (read-only increment)
- Added GitHub App provider connection with numeric App ID, encrypted private key PEM, automatic installation-ID lookup, repository metadata and organization app-installation inventory.
- Added Atlassian Rovo MCP v2 provider connection with encrypted service-account API key, initialize and tools/list metadata retrieval (no tools/call).
- Added tenant-scoped provider-resource inventory endpoint/table under Trust Graph, without fabricating AI-agent relationships.
- Connection Test leaves inventory unchanged; Discover Now performs idempotent upserts with audit logging. All API calls use fixed provider hosts/scopes.
- Added regression tests and provider setup documentation. Production OAuth / SaaS credential flows, dynamic Rovo tool discovery, runtime evidence correlation and stale-record reconciliation remain future work.
