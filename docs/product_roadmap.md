# GAMe — Product Roadmap

**Updated:** 2026-11-06  
**Delivered baseline:** v0.3.3 runtime foundation (partial)  
**Next targeted release:** v0.3.3 — Real source-to-UI provider telemetry validation  
**Scope:** single-company first; no Global/Super Admin reintroduction. Roadmap milestones represent plans, **not shipping commitments**.

## Product north star

**One enterprise control plane to discover and govern AI agents, observe their behavior, attribute their costs, and understand their access to enterprise SaaS systems.**

Four synchronized investment pillars: **Governance & Accountability**, **Runtime Observability**, **Agentic FinOps**, and **Enterprise SaaS MCP Governance**. Runtime and FinOps are **first-class workstreams**, not postponed until after SaaS MCP integrations.

## Release plan and outcomes

| Release | Status | Product outcome | Minimum release gate |
|---|---|---|---|
| **v0.3.2.3** | **Implemented local baseline** | Single-company RBAC, Business Owner approvals, agent inventory/provider connections, 10 advisory policies, manual CVE evidence, Audit Log | Existing tested behavior; not production SaaS |
| **v0.3.3** | **Foundation implemented; live provider proof pending** | **Runtime Observability Foundation:** normalized agent runs, trace/span schema, tool calls, latency/failures and evidence/freshness dashboards | One real telemetry source fully ingested, correlated and displayed; idempotent and least-privilege |
| **v0.3.4** | **Planned** | **Agentic FinOps Foundation:** real usage, cost attribution, cost per execution, budget checks and source reconciliation | At least one real usage/cost stream and a reproducible reconciliation report; unknown amounts labeled Not tracked |
| **v0.3.5** | **Planned; design can run in parallel** | **Enterprise SaaS MCP Governance:** common connector model with Atlassian, GitHub, ServiceNow and Salesforce as equal P1 targets | Verified capability matrix, authorized read-only discovery for each ready provider, mapped tool risks and accurate coverage limitations |
| **v0.3.6** | **Planned** | **Unified agent intelligence:** correlate runs, tools, cost, policy findings, Business Owner authorization and validated business outcomes | Evidence-backed cross-pillar views; no invented ROI or implied enforcement |

The version numbers above are **planning boundaries**; connector and FinOps groundwork should proceed alongside v0.3.3 schema design. Do not treat a provider-specific API test as a fully delivered connector.

## P0 — v0.3.3 runtime observability work packages

- [x] Define normalized `agent_run`, `trace_span`, `tool_call`, `model_usage`, `run_outcome` and `ingestion_source` contracts with the existing registry IDs.
- [ ] Establish event identifiers, timestamps (source vs collection), trace correlation, event freshness, partial-data and unknown-state semantics.
- [~] Build authenticated, scoped, idempotent ingestion: implemented loopback collector secret, replay handling and payload minimization; per-source scopes, retries/checkpoints and dead-letter queue remain pending.
- [ ] Add a version-pinned OpenTelemetry mapping and **one** real available provider/collector adapter; record unsupported signal types explicitly.
- [x] Persist runs and spans in a migration-safe schema, with rollback and DB backup instructions; preserve existing users, encrypted connections, approvals and audit history.
- [x] Runtime Observability screen: Runs and Trace Detail; summary KPIs: executions, failures, latency, tool use and freshness, with source evidence links.
- [ ] Publish telemetry coverage and permission matrix for Microsoft Foundry, AWS AgentCore and Google Agent Engine; distinguish source capability from verified end-to-end ingestion.
- [ ] Security controls: least privilege; never collect prompts, answers, tool payloads, tokens or secrets by default; RBAC at ingestion and read paths.
- [x] Automated tests: duplicate event replay, out-of-order/partial spans, unauthorized requests, redaction, legacy DB migration, zero/unknown separation.
- [ ] Real-data demonstration: one trace/run mapped to an existing real registered/discovered agent; no seeded fictional records.

**v0.3.3 definition of done:** source-to-UI reproducible execution evidence, explicit coverage gaps, safe persistence, auditability, no accidental cost claims, regression tests passing.

## P0 — Parallel FinOps design, then v0.3.4 delivery

- [ ] Define a normalized usage/cost ledger keyed to agent/run/provider/model/tool/cost center and Billing period.
- [ ] Maintain source class: provider-billed, provider-reported, observed-but-estimated, manually recorded, unavailable.
- [ ] Capture rate-card effective dates, currency, token classes, runtime measures, allocation rules, missing values and corrections.
- [ ] Select at least one authorized real provider billing/usage source and document granularity/limitations.
- [ ] Implement source reconciliation, variance, aggregation, double-count prevention and auditable adjustments.
- [ ] Show cost per run/successful run only where numerator and denominator are evidenced.
- [ ] Compare costs to Business Owner-approved budgets; offer advisory alerts without suggesting billing hard-stop.
- [ ] Build per-agent, per-provider, per-cost-center and period trend views with freshness and confidence labels.

**v0.3.4 definition of done:** demonstrably real cost data, reproducible allocations and reconciliation, recorded gaps/unallocated spend, no fabricated zero cost or ROI.

## P1 — Enterprise SaaS MCP integrations, targeting v0.3.5

**Equal Priority 1 providers:**

| SaaS provider | Scope for first validation | Integration evidence to seek |
|---|---|---|
| Atlassian | Jira, Confluence, Jira Service Management | Authenticated MCP tool catalog, account-specific scope, available admin/audit feeds |
| GitHub | Repositories, PRs, Actions, enterprise environments | Hosted/on-prem MCP deployment differences, toolsets, role/scope, audit signals |
| ServiceNow | ITSM, CMDB, change-management workflows | Supported MCP interfaces, integration identities, tool inventory and traceable audit |
| Salesforce | CRM and Agentforce-adjacent workflows | Supported MCP access, identity permission model, tool inventory and event telemetry |

- [ ] Shared SaaS connector contract: discovery capability, permissions, freshness, supported access modes and audit-feed coverage.
- [ ] Read-only registration and MCP `tools/list` interrogation where authorized; no tool executions that mutate external services.
- [ ] Catalog MCP servers, named tools, scopes and tool action risk; preserve evidence that discovery is **identity-scoped**.
- [ ] Map agent-to-tool *configured/granted* access separately from *observed* tool calls.
- [ ] Extend advisory policies to high-risk, unapproved and unknown-owner MCP integrations, with explainable evidence.
- [ ] Correlate captured MCP tool calls to v0.3.3 execution records and v0.3.4 usage/cost records, when IDs permit.
- [ ] Maintain provider capability matrix: available, unavailable, requires customer admin, unverified; never imply organization-wide MCP visibility from one credential.

**v0.3.5 definition of done:** consistent model and auditability across the four targeted SaaS ecosystems; delivered connector capabilities must be listed individually and supported by live validation. If a provider lacks authorized access, its connector remains explicitly unverified rather than being marked complete.

## P1 — v0.3.6 unified intelligence

- [ ] End-to-end agent → run → model/tool → usage/cost → Business Owner → policy evidence lineage.
- [ ] Business outcome evidence model separate from execution success; report efficiency only with validated denominator.
- [ ] Tool access and behavioral findings prioritized by exposure, activity, criticality and business impact.
- [ ] Risk exception approvals/expiry with separation of duties; design independent risk acceptance authority.
- [ ] Exportable governance, trace and FinOps reporting with permissions and provenance.

## Non-functional and enterprise readiness gates (cross-release)

- [ ] Enterprise browser SSO (OIDC authorization code + PKCE), JML, certification and scoped authorization.
- [ ] Secrets-vault/KMS, TLS, credential rotation, secure webhook/ingestion authentication and threat model.
- [ ] Durable PostgreSQL migrations, automated backups/restore, HA/recovery, retained audits and privacy/retention controls.
- [ ] Collector queues, quotas, backpressure, provider rate-limit handling, failure alerting and health dashboards.
- [ ] Formal security review, dependency vulnerability scanning, connector permission tests and customer data classification.
- [ ] Independent inventory completeness tests, telemetry coverage checks and financial reconciliation before customer claims.
- [ ] Multi-company SaaS isolation / separate Global Admin **deferred** until single-company feature and security maturity is proven.

## Deferred / exploratory (not current commitments)

- Automated CVE/CVSS/CISA KEV/EPSS enrichment backed by actual component inventory.
- Behavioral quality, drift, contamination and safety evaluations (beyond deterministic advisory checks).
- Third-party agent marketplaces, acquisition and procurement flows.
- Controlled write-back / enforcement through external gateways or provider APIs, subject to approval and audit.
- Optional agent/MCP gateway or proxy only if enterprise use cases justify a runtime dependency.

## Prioritization and evidence rules

1. **Observed ≠ configured:** `tools/list` does not prove a call; a registered agent does not prove it executed.
2. **Provider billing ≠ trace estimate:** expose source and reconciliation variance, never silently merge incompatible amounts.
3. **Missing ≠ zero/compliant:** unavailable telemetry is Not tracked or Unknown.
4. **Technical Admin ≠ Business Owner:** spending approval stays with the assigned Business Owner.
5. **Advisory ≠ enforcement:** policies surface and track risk; no automatic remote modification.
6. **Real data only:** no demo record injection into live development databases.
7. **Single-company first:** multitenant SaaS is a later architectural expansion, not this release train.

## Document navigation and history

- [`architecture.md`](architecture.md) — current-vs-target architecture and v0.3.3 contracts.
- [`backlog.md`](backlog.md) — redirect to this canonical roadmap.
- [`backlog-legacy.md`](backlog-legacy.md) — historical v0.1/v0.3.0 requirements retained for traceability; superseded where they conflict with the active single-company roadmap.
- [`security-gaps.md`](security-gaps.md) and existing domain docs — deeper limitations and implementation details.

All milestones are subject to validation against supported provider APIs and real enterprise telemetry, not derived from a proprietary analyst report as a development specification.

### v0.3.3 enhancement increment — Runtime telemetry operationalization (2026-11-09)

Implemented in this increment: period and agent filters, historical-vs-period counts, daily execution history, read-only Azure request outcome enrichment, success-only collection heartbeat, and opt-in macOS launchd polling. Follow-on work: reliable unattended workload identity, failure-alerting, durable incremental checkpoints and long-range backfill, provider-specific root execution semantics, AWS/Google adapters, and production retention/archival.


### v0.3.3 automatic Foundry mapping
A collector-authenticated localhost inventory-sync operation refreshes configured Microsoft Foundry connections and maps unique provider IDs/names to stored discovered agents, without per-agent local JSON configuration. Name collisions or missing identifying metadata are deliberately skipped; existing connections and read-only credentials are still prerequisites. See `docs/sysadmin_coadmin_guide.md`.


## v0.3.4.0 — Agentic FinOps Foundation (implemented)

Delivered: agent-linked model token evidence, authenticated Azure collector extraction, idempotent storage, model-specific administrator-documented estimate rate cards, read-only FinOps dashboard with period and agent breakdown, partial-data coverage and Business Owner-approved budgets. Not yet delivered: verified Azure billed charges, cross-provider cost reconciliation, fully reliable scheduled service, unit economics for all tool/compute costs, or SaaS MCP costing. Runtime Observability refresh delay remains a low-priority optimization.

### v0.3.4.1 — Azure ActualCost scope evidence (implemented)

- Read-only Azure Cost Management query using existing Azure CLI authentication
- Daily resource/scope/currency cost records with replay-safe adjustments and separate reporting
- Agent attribution remains unknown unless authoritative evidence becomes available
- Outstanding: invoice reconciliation, amortization/discount handling, reliable scheduled collection, pagination, allocation policies and cost-center chargeback

### v0.3.4.2 — RBAC hardening and permission editing (implemented)

- Separate runtime history, observed tokens, estimated costs, resource-scope ActualCost and rate administration.
- Edit existing local users' permissions, auto-select inherited role permissions and capability prerequisites.
- Retain Admin/Business Owner separation of duties, enforce resource scope server-side, and hide restricted UI sections.
- Pending: enterprise browser SSO and advanced delegated cost-center financial administration.
