# Azure Foundry → GAMe runtime collector (v0.3.3 increment)

> **Current behavior:** Agent registration and telemetry identity matching are automatic for existing configured Microsoft Foundry project connections. Do **not** supply `--mapping` for the normal collector path. The manual mapping steps below document the optional legacy override; see [the operations guide](sysadmin_coadmin_guide.md) for automatic collection and the scheduler migration.


This is a **read-only Azure Monitor Logs collector**, not a modification to Microsoft Foundry agents and not an OTLP endpoint. It fetches actual request/dependency trace metadata from the Log Analytics workspace behind Azure Application Insights, correlates events via `OperationId`, maps explicit Foundry agent identifiers to existing GAMe inventory IDs, and posts normalized metadata to the **localhost-only** GAMe runtime ingestion endpoint. **Nothing is seeded or simulated.**

## Prerequisites

1. Microsoft Foundry project connected to **Azure Application Insights** (Agents → Traces → Connect). The Log Analytics workspace behind that Application Insights resource must have `Microsoft.OperationalInsights` registered at subscription scope. Invoke both agents after connecting; verify real traces in Foundry / Application Insights.
2. Access to the Azure **Log Analytics workspace**, typically the **Log Analytics Reader** role on the workspace or linked monitoring resource (plus Privileged Monitoring Data Reader for protected data where required). Verify access with Azure Portal → Application Insights → Logs. If the collector receives 403, check exact workspace RBAC, API permissions and identity propagation. Read-only access is sufficient.
3. For interactive/local use, install **Azure CLI** and execute `az login` (select the correct subscription using `az account set --subscription ...` if necessary). For unattended collection, use a separate least-privileged Entra application with `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and `AZURE_CLIENT_SECRET` in a protected secret store. Workload identity / federated credentials are preferred for production; this local prototype currently supports CLI or application secret.
4. Existing GAMe **v0.3.3 merged source**, running on `http://127.0.0.1:8000`, with the runtime ingestion token configured. **Set the same token in the collector process**.
5. Python 3.13 project `.venv`, dependencies from `requirements.txt` (including `httpx`).

## Workspace and agent IDs

**Workspace ID:** Azure Portal → Application Insights → Properties → Workspace (open the Log Analytics workspace) → Overview → **Workspace ID** (GUID). This is **not** the Application Insights resource name, instrumentation key, connection string, or Azure resource ID.

**Azure agent identifier:** inspect actual traces from the Foundry project using the Azure Portal → Application Insights → Logs, for example:

```kusto
AppRequests
| where TimeGenerated > ago(2h)
| extend FoundryAgentId = tostring(Properties['gen_ai.agent.id']),
         FoundryAgentName = tostring(Properties['gen_ai.agent.name'])
| project TimeGenerated, OperationId, FoundryAgentId, FoundryAgentName, Name
| order by TimeGenerated desc
| take 50
```

If this returns no agent ID, also inspect the `AppDependencies` table in the same way. Attribute availability varies by Foundry agent and instrumentation. **Do not guess an ID from the agent's display name**; if the trace lacks attributable identifiers, the collector will skip it until a supported source-to-agent mapping can be verified.

**GAMe ID:** existing inventory ID displayed in GAMe or returned by `GET /api/agents` under an authenticated browser session. Do not use the Azure Foundry display name as the GAMe database ID unless that is truly the stored ID.

Place a private file **outside Git** (e.g. `$HOME/.config/game/azure-agent-map.json`) with explicit source-to-destination identifiers:

```json
{
  "ACTUAL_FOUNDRY_AGENT_ID_1": "ACTUAL_GAME_ID_1",
  "ACTUAL_FOUNDRY_AGENT_ID_2": "ACTUAL_GAME_ID_2"
}
```

These are placeholders **only**; do not submit them as real IDs. Every key must match an observed Azure `gen_ai.agent.id`/`gen_ai.agent.name` or supported agent identity field. Multiple keys can map to the same GAMe agent, but a trace that would map to **different** GAMe agents is rejected as ambiguous.

## Run on Mac (first dry run)

Start GAMe in terminal A with its existing collector credential:

```bash
cd /Users/nanna/Documents/Siddhartha-Collabera/Develop/game-mvp
source .venv/bin/activate
# Set your existing secret in the shell or secure secret manager.
# export GAME_RUNTIME_INGEST_TOKEN=...  # >=32 chars; SAME value as collector
GAME_AUTH_MODE=password PYTHONPATH=src python -m uvicorn game.main:app --host 127.0.0.1 --port 8000 --reload
```

In terminal B:

```bash
cd /Users/nanna/Documents/Siddhartha-Collabera/Develop/game-mvp
source .venv/bin/activate
az login
python scripts/collect_azure_foundry.py \
  --workspace YOUR_LOG_ANALYTICS_WORKSPACE_GUID \
  --mapping "$HOME/.config/game/azure-agent-map.json" \
  --lookback-minutes 120 \
  --dry-run
```

The dry-run prints counts and IDs only; **it does not import anything**. The usual query lag is 5 minutes to allow Azure telemetry to arrive. It retrieves at most 2,000 records per table by default; if a table reaches the cap, the run stops so it cannot silently miss data.

After verifying attribution and securing the identical collector token in terminal B:

```bash
python scripts/collect_azure_foundry.py \
  --workspace YOUR_LOG_ANALYTICS_WORKSPACE_GUID \
  --mapping "$HOME/.config/game/azure-agent-map.json" \
  --lookback-minutes 120
```

Return to **GAMe → Runtime observability**. Confirm individual executions for both agents and check matching trace IDs/timestamps. Rerunning the same collection will replay existing run IDs instead of duplicating them. To poll periodically on a Mac, use a separately configured launchd job or cron with secure credentials; this release provides a **one-shot** command, not a built-in scheduler.

## Current behavior and limitations

- Queries **`AppRequests` and `AppDependencies`**, only for `TimeGenerated`, `OperationId`, `Id`, `ParentId`, `Name`, `DurationMs`, `Success`, `Properties`. `Properties` are processed in memory with an **agent-identification allowlist** and **never transmitted or stored**. Span names are sanitized to generic operation labels. `AppTraces` message bodies are *not* retrieved.
- Every submitted run must contain a valid real Azure trace `OperationId` (32 hex characters), a timezone-aware timestamp and an explicit match to **exactly one** configured GAMe agent ID. Unknown and ambiguous traces are skipped, not guessed.
- Azure request/dependency `Id` formats may not be 16-hex OTel span IDs. The adapter derives a **stable local correlation ID** when necessary, rather than presenting the original ID as a genuine OTel span ID. Run trace IDs remain actual Azure IDs.
- Request `Success` determines a known outcome only where request data supports it. Missing outcomes/durations remain unknown. A trace is not guaranteed to represent precisely one logical agent run; grouping by Azure `OperationId` is provisional and must be validated with actual sample traces.
- Some Foundry agent types emit different trace attributes or table schemas. If the two agents don't emit `gen_ai.agent.id`, `gen_ai.agent.name`, `agent.id`, or `agent.name`, the collector **cannot safely attribute them** and will report `unattributed`. Do not turn on heuristic matching to force ingestion. Provider-specific adaptation would be needed.
- This collector has **not been exercised against your Azure tenant**. Automated tests use controlled row fixtures and fake HTTP responses. Real end-to-end acceptance requires your Azure Workspace ID, permissions, agent-ID mapping and actual agent executions.
- The collector uses the user's local Azure CLI token or explicitly configured service-principal credentials. It is **read-only on Azure**. Only the existing local GAMe `/api/runtime/ingest` API receives writes. Do not check credentials, mappings, query results or token into GitHub. Localhost-only GAMe is intentionally unchanged.
- Data can arrive late; overlapping collection windows + server deduplication are expected. The collector doesn't implement durable checkpoints or advanced backfill for delayed spans yet. A replay with shifted start timestamps may be rejected as a conflict rather than silently rewriting a run.
- Existing governance, approval, Azure provider connections, cloud credentials and GitHub Actions CI stay unchanged.

## Troubleshooting

| Output | Meaning / next action |
|---|---|
| `AppRequests is absent` | No table created yet, wrong workspace, or instrumentation not enabled. Verify traces in Foundry. |
| `403` from Azure Monitor | Verify workspace `Log Analytics Reader` permissions and identity; allow for RBAC propagation. |
| `eligible: 0`, `unattributed` | Agent identity attributes not present/mapped; inspect Foundry trace attributes. |
| `ambiguous` | Multiple mapped agents share a trace; exclude rather than misattribute. |
| `401` from GAMe | Collector token not shared between the server and terminal B. |
| `404` from GAMe | Mapped GAMe ID doesn't exist in the current local database. |
| `409` from GAMe | Existing run/trace/spans conflict; inspect source grouping rather than overwriting history. |
| `query cap` | Narrow `--lookback-minutes` and rerun overlapping windows. |

Microsoft documentation: [Foundry tracing](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-setup), [Azure Monitor Logs Query API](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/overview), [Azure Monitor auth](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/access-api).


### v0.3.3 automatic Foundry mapping
A collector-authenticated localhost inventory-sync operation refreshes configured Microsoft Foundry connections and maps unique provider IDs/names to stored discovered agents, without per-agent local JSON configuration. Name collisions or missing identifying metadata are deliberately skipped; existing connections and read-only credentials are still prerequisites. See `docs/sysadmin_coadmin_guide.md`.
