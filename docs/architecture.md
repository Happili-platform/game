# GAMe — Product & Technical Architecture

**Document baseline:** 2026-11-06  
**Current implemented release:** v0.3.3 runtime foundation (single-company, developer deployment; live provider telemetry still pending)  
**Next planned increment:** v0.3.3 — Runtime Observability Foundation  
**Status convention:** **Implemented** describes existing source; **Planned** describes roadmap requirements, not shipped features.

## 1. Product intent and boundary

GAMe is a vendor-neutral **enterprise control plane for AI agents**: discovery and inventory; accountable ownership and business approval; explainable governance; runtime observability; agentic FinOps; and governance of access to enterprise SaaS capabilities through MCP and provider-native APIs.

The focus is a heterogeneous *agentic workforce*, not a comprehensive inventory of all predictive machine-learning systems. GAMe complements enterprise AI governance programs (AIGPs) and API/AI gateways while concentrating on agent life cycle, behavior, tool access, and financial accountability. **GAMe is not itself an AI gateway, agent builder, or runtime enforcement proxy.** Initial integrations are advisory and read-only.

Four product pillars:

1. **Governance & accountability:** unified agent catalog, role- and scope-based access, Business Owner approvals, advisory policies, remediation, audit evidence.
2. **Runtime observability:** agent execution records, trace correlation, tool/model calls, failures, latency, outcomes, coverage and provenance.
3. **Agentic FinOps:** measured provider usage, actual and estimated costs, allocation, approved budgets, unit economics and reconciliation.
4. **Enterprise SaaS MCP governance:** catalog SaaS MCP servers/tools and map agent-to-tool authorization and observed use; integrate Atlassian, GitHub, ServiceNow and Salesforce as **equal Priority 1** targets.

**Guiding rule:** inventory/configured access, actual observed activity, inferred conclusions and business approval are different facts and must never be conflated.

## 2. Current implementation — v0.3.2.3

The source is a FastAPI application with browser frontend and persistent SQLite storage, runnable on localhost. It contains single-company user login and scoped RBAC, with the fixed roles **Admin, Provider Admin, User/Agent Owner, Auditor, Viewer and Business Owner**. The Business Owner role is independent of technical Admin inheritance and is solely authorized to approve or reject requests for their assigned agents. Business budget and cost center are captured during requests. Platform actions and approval decisions are written to an Administration Audit Log.

The registry supports manual registration and cloud-provider discovery connections for Microsoft Foundry, AWS AgentCore and Google Agent Engine, plus private-registry metadata ingestion paths. Individual API success or connector tests do **not** establish complete inventory coverage for every provider. Provider credentials can be retained using the local encrypted credential store; production-scale secret management remains a gap.

The existing Advisory Policy Framework provides 10 configurable deterministic advisory checks, recorded evaluations, finding history and remediation tracking. Agent details support manually supplied CVE/component references with explicit assessment evidence and an NVD link. **There is no independent vulnerability scanning or automatic CVSS, KEV or EPSS enrichment.**

Costs already recorded in the application are not equivalent to reconciled provider billing. Missing provider usage or cost data must display **Not tracked**, not $0. Current runtime observability, full MCP SaaS discovery and provider-derived per-execution FinOps are **not implemented**.

**Security limitation:** this remains a developer/local deployment. Browser enterprise SSO, production HA, hardened tenancy isolation, PostgreSQL/RLS, workload scheduling, enterprise secrets vault, and regulated retention are not complete. The prior v0.3.0 tenant-aware design is architectural groundwork, **not** authorization to reinstate a multi-company Super Admin UI. Single-company completeness is the immediate target.

## 3. Target logical architecture (planned)

```text
+--------------------------------------------------------------------------+
| GAMe UI / API — one enterprise company                            |
| Agent Registry | Governance | Runtime Observability | Agentic FinOps      |
| SaaS MCP Governance | Administration Audit | Coverage / Evidence         |
+-----------------------------+--------------------------------------------+
                              |
                              v
+--------------------------------------------------------------------------+
| Common identity, RBAC/scope, policy, ownership, provenance and audit       |
+-----------------------------+--------------------------------------------+
                              |
          +-------------------+----------------------+------------------+
          |                   |                      |                  |
          v                   v                      v                  v
+------------------+ +-------------------+ +------------------+ +------------------+
| Inventory /      | | Observability     | | Usage / Billing  | | SaaS MCP and     |
| Provider Adapters| | Ingestion Adapters| | Ingestion Adapters| | Admin API Adapters|
+------------------+ +-------------------+ +------------------+ +------------------+
          |                   |                      |                  |
    Foundry, AWS,      OpenTelemetry /        Provider usage,       Atlassian, GitHub,
    Google, private    provider telemetry     invoice/export APIs   ServiceNow, Salesforce
          +-------------------+----------------------+------------------+
                              |
                              v
+--------------------------------------------------------------------------+
| Normalized records: agents, runs, trace spans, tool calls, usage, prices, |
| allocated costs, MCP servers/tools, relationships, source evidence       |
+-----------------------------+--------------------------------------------+
                              |
                              v
+--------------------------------------------------------------------------+
| Storage, reconciliation, retention, audit, job state, failure quarantine |
| DEV: SQLite where suitable | PRODUCTION TARGET: PostgreSQL + collectors |
+--------------------------------------------------------------------------+
```

The diagram shows a **target design**, not a statement that every adapter or record type exists today.

## 4. v0.3.3 — Runtime Observability Foundation (planned)

**Goal:** establish an evidence-backed per-agent execution ledger that later FinOps and MCP connectors can reuse, without blocking an agent's execution path.

### 4.1 Normalized telemetry entities

| Entity | Minimum core fields | Notes |
|---|---|---|
| `agent_run` | internal run ID, provider run ID, agent ID, provider/environment, start/end UTC, status, duration, source, observed-at | Deduplicate provider events; statuses must include unknown/incomplete. |
| `trace_span` | trace ID, span ID, parent ID, run ID, name/type, timestamps, outcome, source | Preserve propagation IDs; some sources provide partial traces. |
| `tool_call` | span/run ID, MCP server/tool ID or native tool name, outcome, duration, provider correlation IDs | Tool configuration is not proof of invocation. |
| `model_usage` | run/span ID, model ID, input/output/cached tokens where supplied, source | Unknown token counts remain null. |
| `run_outcome` | run ID, outcome type, asserted by, evidence reference and verification state | A successful API response is not necessarily a successful business outcome. |
| `ingestion_source` | integration, scope, event ID, collected-at, event-at, freshness and coverage | Show per-field provenance and stale/unsupported scenarios. |

All records must be company-scoped and access-controlled, with stable links to the existing agent registry. Support partial and late-arriving events; do not force missing model/tool data into empty-string or zero values.

### 4.2 Planned data collection

- **OpenTelemetry (OTel):** adopt a version-pinned, documented trace/metric ingest contract. Accept only authenticated, authorized ingest requests. Default to metadata and measurements; **do not collect prompts, responses, secret headers, raw source code or sensitive tool payloads**.
- **Cloud providers:** adapters for available Foundry, AgentCore and Agent Engine execution/monitoring APIs or approved export paths. Publish a per-connector capability matrix; not every platform exposes the same granularity.
- **SaaS MCP:** reserve normalized fields and trace links for future Atlassian/GitHub/ServiceNow/Salesforce tool events. Initial v0.3.3 is a schema foundation, **not** a claim that these SaaS adapters are available.
- **Ingestion operations:** idempotency by source event ID, pagination/checkpointing, retry/backoff, bounded buffering, duplicate detection, rate-limit handling, redaction, and quarantine of malformed events.

### 4.3 Planned observability UI

Per-agent **Runs**, **Trace Details**, **Tool Calls**, **Failures**, **Latency**, and **Data Coverage** views. Support filtering by time range, provider, environment, agent, status, trace and tool. Separate collected timestamps from provider event timestamps. Dashboards must visually distinguish measured, provider-reported, manually recorded, inferred and unavailable information.

### 4.4 v0.3.3 acceptance gates

- At least **one real, authorized telemetry source** end-to-end: collect, deduplicate, persist, correlate to an existing agent, and render execution details.
- Status, duration and failure indicators match the source evidence; missing fields remain unknown.
- Correlation schema accommodates tool/MCP and billable usage events without restructuring agent IDs.
- Security tests show unauthorized ingestion rejected and sensitive payload fields excluded by default.
- A replay of the same event does not double-count runs or later usage.
- UI labels coverage gaps, unsupported events and ingestion freshness clearly.
- No dummy or fabricated live production telemetry; any test fixtures remain test-only.

## 5. v0.3.4 — Agentic FinOps Foundation (planned)

- Ingest real usage and billing data through supported provider interfaces and/or authorized telemetry. Maintain **actual / provider-reported / estimated / manually recorded / not tracked** distinctions.
- Normalize units (tokens, requests, runtime seconds, tool invocations), currency, billing period, pricing version and effective dates. Attribution is performed to **agent, run, model, tool, provider, cost center and Business Owner** when the evidence permits.
- Calculate unit economics only with a defined denominator: cost/run, cost/successful run, cost/tool call, and later cost/verified business outcome. Expose unallocated spend rather than inventing attribution.
- Reconcile aggregates against source invoices/exports with period boundaries, adjustments, rounding and documented variance. Track cost confidence and freshness.
- Compare observed spend against **Business Owner-approved monthly budgets** and recorded cost centers. Alerts are advisory; do not promise immediate provider hard stops.
- FinOps requires runtime ingestion **and** provider/billing reconciliation; traces alone are not financial truth.

## 6. v0.3.5 — Priority-1 Enterprise SaaS MCP (planned)

**All Priority 1 (equal product priority):** Atlassian (Jira, Confluence, JSM), GitHub (including GHEC/GHES deployment distinctions), ServiceNow (ITSM/CMDB/changes), Salesforce (CRM/Agentforce context). Prioritize integration readiness based on available authorized APIs and test accounts, not a business-level ranking among these four.

Common model: `saas_connection`, `mcp_server`, `mcp_tool`, `identity_or_grant`, `agent_tool_relationship`, `observed_tool_call`, and `policy_finding`; reference existing agents, runs, user roles, business approvals and audit events.

Discovery via `tools/list` is scoped to **the authenticated identity** and cannot, by itself, prove enterprise-wide access, historical use or grant ownership. Supplement with provider admin APIs and audit feeds when supported. Classify tool actions by read, create/write, delete, execute and administer, and record confidence/evidence. Never invoke destructive or write tools as part of discovery. Initial policy findings are advisory; gateway enforcement remains external and optional.

## 7. v0.3.6 — Unified governance and business outcomes (planned)

Correlate an agent's business approval and budget with observed runs, tool activity, policy/risk evidence, billable usage and **independently validated** business outcomes. Support exception and risk-acceptance governance with separation of duties; no auto-remediation or agent-disablement without explicit design, approvals and provider support. Do not label technical uptime or run success as ROI.

## 8. Cross-cutting safety, security and operations

- **Identity / RBAC:** preserve Business Owner-only spending approvals and scopes; a technical Admin must not inherit approval. Harden browser SSO/PKCE for enterprise use in a separate milestone.
- **Collection privileges:** read-only, least-privilege provider accounts and explicit permission matrices. Authentication to GAMe is independent of source-provider permissions.
- **Privacy:** minimum metadata, default payload exclusion/redaction, configurable retention, data classification, restricted audit access, encryption at rest/transit and secret rotation.
- **Integrity:** deterministic source IDs, evidence and timestamps, immutable decision-event intent; operational audit logs are not a substitute for a tamper-evident production audit store.
- **Accuracy:** report coverage, stale data, unknown statuses, provider limitations, currency/timezone boundaries and source reconciliation. Never show unavailable spend as $0.
- **Operability:** queued collectors, retries, quotas, checkpoints, metrics/alerts, recovery, migration tests, backup and restore are required for production readiness.
- **Deployment scope:** single-company first; centrally hosted multi-tenant/Super Admin roadmap is deferred until single-company capability and security gates are met.

## 9. Reference decisions and source of truth

- **ADR-001:** Single-company scope through current release series; no global Super Admin interface.
- **ADR-002:** Business Owner alone approves/rejects agent business spending; Admin and Provider Admin retain technical responsibilities.
- **ADR-003:** Advisory findings do not directly enforce runtime actions.
- **ADR-004:** GAMe observes and governs SaaS MCP connections; it is not an MCP/AI gateway by default.
- **ADR-005:** Runtime telemetry and provider-reconciled FinOps share IDs, provenance and evidence but are distinct data streams.
- **ADR-006:** Atlassian, GitHub, ServiceNow and Salesforce are all Priority 1 SaaS MCP targets.

See [`product_roadmap.md`](product_roadmap.md) for delivery order and acceptance gates; [`security-gaps.md`](security-gaps.md), [`single-company-rbac.md`](single-company-rbac.md), [`business-approval-and-audit.md`](business-approval-and-audit.md), and [`advisory-policy-and-vulnerability-intelligence.md`](advisory-policy-and-vulnerability-intelligence.md) for existing implementation-specific detail. Older `saas-architecture.md` describes a prior tenant-aware foundation, **not** the active single-company interface or production readiness.


## Implemented v0.3.3 runtime foundation (November 2026)

The company-scoped SQLite database now contains `runtime_runs` (run ID, source, mapped agent, trace ID, outcome, UTC start/end/duration and ingestion freshness) and `runtime_spans` (trace/span/parent IDs, operation type/name, status and duration). `POST /api/runtime/ingest` accepts a restricted normalized JSON contract with a localhost-only collector credential; it **is not an OTLP/HTTP endpoint**. Collector adapters and live provider mappings are not implemented. `GET /api/runtime/runs`, `/api/runtime/runs/{id}` and `/api/runtime/summary` use existing user RBAC and resource scopes. The Runtime observability page displays recorded evidence and honest unknown values.

**Security / deployment boundary:** first-release collector token is company-wide rather than per-agent scoped, loopback-only. Never expose it outside localhost; migrate to per-integration workload credentials and trust boundaries for hosted deployment. No prompts, tool arguments or responses are accepted, but adapters must still sanitize operation names. Runtime metadata never changes Business Owner approvals, policy decisions, or usage billing events. See `docs/runtime-observability.md`.

### Runtime observability operationalization — v0.3.3 enhancement

The Azure Logs collector reads `AppRequests`/`AppDependencies` metadata, maps only verified agent identifiers, then posts normalized run evidence to localhost collector-ingestion endpoints. `runtime_runs` and `runtime_spans` remain append/update-only with deduplication; absence of new Azure records never deletes stored telemetry. A distinct `runtime_collection_status` table tracks last successful collection and the queried time window even when zero runs are imported. The UI distinguishes historical totals from the selected period and plots daily runs from persisted facts. macOS launchd is an optional polling driver (15 min default, 60 min overlapping window), not a hosted scheduler. Status derived from Azure request HTTP ResultCode is a technical request outcome only, not business-task evaluation. Agentic FinOps remains a future milestone.


### v0.3.3 automatic Foundry mapping
A collector-authenticated localhost inventory-sync operation refreshes configured Microsoft Foundry connections and maps unique provider IDs/names to stored discovered agents, without per-agent local JSON configuration. Name collisions or missing identifying metadata are deliberately skipped; existing connections and read-only credentials are still prerequisites. See `docs/sysadmin_coadmin_guide.md`.


## v0.3.4.0 — FinOps evidence ingestion (implemented foundation)

The Azure runtime collector now extracts standard aggregate model token counts from attributed `AppDependencies` spans; it submits normalized, replay-safe records to `finops_usage`. `finops_rate_cards` contains optional, administrator-documented, effective-dated USD-per-million-token rates for **estimates only**. Separate `billed_usd` remains untracked pending provider invoice reconciliation. No inference of missing tokens or prices. Access remains scoped by agent and role. The existing Business Owner is authoritative for spending approval; technical administrators cannot approve. See [`agentic-finops.md`](agentic-finops.md).

## v0.3.4.1 — Azure Cost Management reconciliation boundary

The optional Azure `ActualCost` collector (`scripts/collect_azure_costs.py`) independently pulls **resource-scoped daily cost** from the Azure Cost Management REST API using a read-only Entra identity. It submits normalized resource/day/currency amounts to the collector-authenticated `/api/finops/azure-costs/ingest` endpoint and stores them in `finops_azure_scope_costs` using an idempotent UPSERT. Agent-based OpenTelemetry token usage and model-rate estimates remain in the separate `finops_usage` and `finops_rate_cards` tables. They are **not joined or auto-allocated** without trustworthy agent-specific billing evidence. Customer-provided rates produce **estimates**; Azure `ActualCost` is scope evidence **subject to adjustments**, not final invoiced charges. The UI shows both independently. No scope data means `Not tracked`, not `$0`.

## v0.3.4.2 — Financial access authorization

The RBAC server distinguishes `runtime.view`, `finops.usage.view`, `finops.estimates.view`, `finops.billing.view` and `finops.rates.manage`. Financial data is filtered on the server by company, resource scope, and Business Owner assignment. Azure resource-scope billing is available only to Admin/Auditor. Local user capability restrictions are stored as nullable JSON and never exceed their role ceiling. Existing users retain full original preset permissions until changed; the new Viewer defaults remove detailed runtime and FinOps access. See `rbac-finops-0342.md`.
