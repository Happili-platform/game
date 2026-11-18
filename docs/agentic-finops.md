# GAMe v0.3.4.0 — Agentic FinOps Foundation

**Status:** Local, single-company development increment. Source-backed token accounting is implemented; Azure billing reconciliation and end-to-end live Foundry token usage verification are not yet complete.

## Boundaries and semantics

GAMe does **not** infer model pricing or claim the Azure invoice amount from Application Insights. It keeps:

1. **Observed tokens:** Only integer `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens` from an attributed `AppDependencies` model-operation span; absent values remain `NULL`. AppRequests are excluded from usage accounting to avoid counting rolled-up totals twice. These attributes are consistent with OpenTelemetry GenAI semantic conventions, but availability depends on the Foundry instrumentation.
2. **Configured estimates:** Only when the operator has recorded an exact `source` + `model_id` rate for the usage event's effective date with an HTTPS documentation reference; complete input *and* output counts are required. Estimated charges are **not** billed charges, and an admin-supplied URL is an audit reference, not independently verified pricing.
3. **Billed cost:** **Not tracked** in v0.3.4.0; native Azure Cost Management reconciliation is subsequent work.
4. **Authorized monthly spend:** Business Owner approvals in `agent_governance` are the source of authorization; technical administrators cannot approve. A partial cost estimate must not be construed as proof of budget compliance.

No provider-reported price, deployment alias, subscription discount, cached-token discount, reserved capacity, free tier, or tool charge is guessed. Missing prices and incomplete token pairs produce **Not tracked**, not $0.00.

## Data flow

`Azure Application Insights (AppRequests/AppDependencies) → existing read-only Azure collector → runtime_runs/runtime_spans → /api/finops/usage/ingest → finops_usage → /api/finops/summary → Agentic FinOps page`

- Existing Azure agent auto-discovery and identity collision protection remain intact.
- `finops_usage` uses a unique `(tenant_id, source, agent_id, external_run_id, operation_id)` identity. Replays are idempotent; conflicting replays return HTTP 409.
- Usage ingestion is localhost-only and uses the same 32+-character `GAME_RUNTIME_INGEST_TOKEN` as runtime ingestion. It requires the matching existing runtime execution. It rejects arbitrary content including prompts, replies, token strings, tool arguments or opaque attributes.
- Historic runtime executions are **not** deleted or recalculated when no new Azure telemetry arrives. Re-running the collector can backfill standardized token attributes when those rows are still within the query window.
- `finops_rate_cards` is an explicitly configured USD-per-million-token estimate catalog. Rate entries cannot have overlapping effective windows for the same provider/model. Provider names currently use the normalized runtime telemetry **source** (`azure_foundry_logs`), not a marketing display name.

## Installation and startup

1. Back up `data/game.db` and the local vault master key before applying the source ZIP. Preserve your existing `~/.config/game/runtime-ingest-token` and Azure CLI login.
2. Install the full project update in the same existing project directory; do not replace `data/`, `.venv/`, or `~/.config/game`.
3. Install Python requirements as required, then start GAMe with:

```bash
source .venv/bin/activate
export GAME_AUTH_MODE=password
export GAME_RUNTIME_INGEST_TOKEN="$(cat ~/.config/game/runtime-ingest-token)"
PYTHONPATH=src python -m uvicorn game.main:app --host 127.0.0.1 --port 8000 --reload
```

4. Existing launchd collection remains valid: the updated `scripts/collect_azure_foundry.py` now submits eligible model usage metadata **after** each corresponding runtime run is ingested. If no token attributes exist, it imports zero FinOps usage records and does not invent costs.
5. In the browser, select **Agentic FinOps**. The default period is 30 days. Select All history to see older evidence.

### One-time manually triggered verification

```bash
source .venv/bin/activate
export GAME_RUNTIME_INGEST_TOKEN="$(cat ~/.config/game/runtime-ingest-token)"
python scripts/collect_azure_foundry.py \
  --workspace YOUR_EXISTING_LOG_ANALYTICS_WORKSPACE_GUID \
  --lookback-minutes 1440 --lag-minutes 0 --dry-run
```

The diagnostic now includes `Observed model usage operations: N`. When satisfied, remove `--dry-run`. Collector may report zero token-bearing model spans even when agent runtime traces are present; this is a telemetry coverage finding, not an agent failure. Avoid modifying a production agent merely to manufacture sample data.

### Exact pricing documentation (optional; Admin only)

Use the authenticated FastAPI interactive docs at `http://127.0.0.1:8000/docs`, route `POST /api/finops/rates`, to register a documented rate card. In password mode, use a valid CSRF-authenticated browser session; a bare unauthenticated `curl` request is not permitted. Example **schema only**, not a claim about Azure's current price:

```json
{
  "provider":"azure_foundry_logs",
  "model_id":"EXACT_MODEL_ID_FROM_TELEMETRY",
  "input_usd_per_million":"DOCUMENTED_INPUT_RATE",
  "output_usd_per_million":"DOCUMENTED_OUTPUT_RATE",
  "valid_from":"2026-11-01T00:00:00Z",
  "source_url":"https://YOUR_ACTUAL_SOURCE_DOCUMENTATION"
}
```

The API requires valid decimal rates and an actual HTTPS documentation URL. A rate entered in development is a **configured estimate**, not independently verified or invoice-reconciled. Business Owners authorize the requested budget; they do not inherit technical Admin's rate configuration privilege.

## APIs and checks

| Endpoint | Access | Function |
|---|---|---|
| `POST /api/finops/usage/ingest` | Local authenticated collector | Normalized observed model tokens, linked to existing run |
| `GET /api/finops/summary?period=30d` | Scoped users with `costs.view` | By-agent observed usage, estimate coverage, approved budgets |
| `GET /api/finops/rates` | `costs.view` | Active/historic documented rate metadata |
| `POST /api/finops/rates` | Admin (`finops.rates.manage`) | Record effective rate without overwriting previous periods |

Test:

```bash
PYTHONPATH=src python -m pytest -q tests/test_finops_034.py
PYTHONPATH=src python - <<'PY'
from game.main import app
print([p for p in app.openapi()['paths'] if p.startswith('/api/finops/')])
PY
```

## Deferred / product roadmap

- Azure usage and invoice reconciliation, regional and deployment-specific price cards and enterprise rate agreements.
- Business Owner budget variance and alerting only when actual costs can be reasonably attributed; distinguish partial estimates.
- Cost-center assignment and historic budget snapshots.
- AWS AgentCore, Google Agent Engine and SaaS MCP provider-specific cost adapters.
- Independent telemetry quality checks, large-scale aggregation, production checkpointing and alerting.
- Central SaaS tenancy, production IAM/SSO, secure monitoring and scalable data store.

## v0.3.4.1 — Azure Cost Management ActualCost (resource-scope evidence)

This optional integration makes a **read-only** query to Azure Cost Management's `ActualCost` API at an explicitly selected subscription or resource-group scope. It stores daily `ResourceId` + `UsageDate` + `Currency` charges and displays the result separately under Agentic FinOps. It does **not** claim invoice finalization or allocate costs to individual AI agents, since Azure charge records often represent shared resources, model deployments, or unrelated services. Never compare an agent's estimated usage cost directly with scope-wide charges as if they share an accounting boundary.

Azure service principal or Azure CLI identity must have permission to query Cost Management at the selected scope (typically Cost Management Reader). Confirm relevant Azure billing account type and permissions. The account does not need write access to Azure resources.

**One-time setup on development Mac** (scope shown is illustrative, replace with your *actual* subscription/resource-group ARM path):

```bash
cd game-mvp
source .venv/bin/activate
az login
python scripts/collect_azure_costs.py \
  --scope /subscriptions/YOUR-AZURE-SUBSCRIPTION-UUID/resourceGroups/YOUR-FOUNDRY-RESOURCE-GROUP \
  --days 7 --dry-run
```

Verify that the output is scoped correctly and contains actual resource charges. When satisfied, load the existing local collector secret and import:

```bash
export GAME_RUNTIME_INGEST_TOKEN="$(cat ~/.config/game/runtime-ingest-token)"
python scripts/collect_azure_costs.py \
  --scope /subscriptions/YOUR-AZURE-SUBSCRIPTION-UUID/resourceGroups/YOUR-FOUNDRY-RESOURCE-GROUP \
  --days 7
```

The GAMe server must be running on `127.0.0.1:8000` with the same token. Azure Cost Management data can lag and prior charges can be corrected; re-import is an **idempotent upsert** that replaces existing resource/day/currency values rather than adding duplicates. Empty query results never delete prior records. The collector defaults to seven inclusive calendar days, configurable from 1 to 31 days per run. The `Azure resource-scope charges` dashboard shows the source and accounting limitations; no conversion is performed between currencies.

**Not implemented:** scheduled cost collection, final invoice matching, billing-meter normalization, full pagination/backfill, per-agent cost allocation, AWS/Google cost management. The collector rejects paginated results rather than silently importing partial billing data. For large subscriptions, prefer a narrow resource-group scope or query smaller windows.

Official API: https://learn.microsoft.com/en-us/rest/api/cost-management/query/usage?view=rest-cost-management-2026-06-01
