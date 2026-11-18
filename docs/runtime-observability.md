# Runtime Observability — v0.3.3 Foundation

## What is implemented

- Additive SQLite migration for `runtime_runs` and `runtime_spans`, tenant/company ID and agent registry linkage.
- `POST /api/runtime/ingest`: **normalized metadata-only JSON contract**, a collector-only ingestion endpoint using `X-GAME-Ingest-Token` and loopback restriction.
- `GET /api/runtime/runs`, `GET /api/runtime/runs/{run_id}`, `GET /api/runtime/summary`: identity- and agent-scope-filtered read APIs.
- **Runtime observability** navigation: visible-agent selector, executions, outcome coverage, success rate, p95 runtime duration, trace/span inspection and freshness.
- Duplicate replay handling and additive span ingestion. Missing duration, cost and status are **Not tracked**/`unknown`, not zero. No demo runs inserted.
- Audit Log and Business Owner workflows, provider settings and encrypted credentials remain unchanged.

## Explicit limitations

**This is the first working foundation, not the full v0.3.3 release acceptance gate.** It does *not* yet automatically poll Microsoft Foundry, AWS AgentCore or Google Agent Engine telemetry, and it does **not** accept raw OTLP/HTTP protobuf or JSON. A trusted adapter maps real provider or OpenTelemetry trace evidence to the normalized contract. No provider trace-to-agent linkage has been validated live yet.

The ingestion credential is one **company-wide local prototype key**, not scoped per collector or per agent. It must never be exposed to browsers, untrusted agents or SaaS tenants. Ingestion is **loopback only**; do not expose the app to the Internet. Production requires collector service identities, narrow scopes, TLS ingress, secret rotation, throttling, retention and payload-size enforcement at the ingress proxy, stronger query scaling and eventual tenant isolation. Current retention is indefinite unless data are manually removed; no automated purge.

Only store generic span operation names, IDs, metadata, timestamps, statuses and duration. **Never send prompts, responses, tool inputs/outputs, request URLs, access tokens or sensitive attributes**. This strict API contract rejects unknown top-level and span keys. Names themselves may still contain sensitive information: adapters must sanitize them before submission.

Recorded runtime evidence **does not alter business approval**, provider operation or billing data. Cost is always `Not tracked` until backed by cost evidence. Success rate uses only **known outcome** runs; p95 uses only completed-duration samples. All summary metrics are across the current recorded history; no billing-window semantics are implied.

## Upgrade (existing macOS installation)

Before upgrade, stop the process and back up the database **and** secure credential master key:

```bash
cd /Users/nanna/Documents/Siddhartha-Collabera/Develop
cp game-mvp/data/game.db game-mvp/data/game.db.pre-v033.bak
cp ~/.config/game/master.key ~/.config/game/master.key.pre-v033.bak
unzip -o ~/Downloads/GAME-v0.3.3-Merged-Baseline-Update.zip -d .
cd game-mvp
source .venv/bin/activate
export GAME_RUNTIME_INGEST_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
GAME_AUTH_MODE=password PYTHONPATH=src python -m uvicorn game.main:app --host 127.0.0.1 --port 8000 --reload
```

Set the collector credential via a protected environment or secret store; do not check it into Git or put it in an app config served to the browser. The example creates a *new* key each startup; an external collector must receive the corresponding value through a secure secret channel. For repeatability, persist the key in a suitably protected secret store instead of regenerating it on each restart.

## Verify without inventing executions

1. Log into `http://127.0.0.1:8000`. Select **Runtime observability**. It should show `0` recorded runs (unless the existing DB already includes telemetry), and `Not tracked` for unknown cost/latency/success rate.
2. Identify an **existing real** agent ID from the Agent Registry, or via `GET /api/agents` while authenticated.
3. Produce one genuine invocation in your provider agent, capture its **real** run ID, trace ID, span IDs, timestamps and result from an actual telemetry source.
4. Normalize that observation to this request shape and submit it from the same Mac using the collector secret. This is an **illustrative field template only**; substitute actual source evidence, not fabricated test values:

```json
{
  "agent_id": "EXISTING_AGENT_ID",
  "source": "PROVIDER_OR_COLLECTOR_NAME",
  "external_run_id": "ACTUAL_RUN_ID",
  "trace_id": "ACTUAL_32_CHARACTER_HEX_TRACE_ID",
  "status": "success",
  "started_at": "2026-11-06T12:00:00Z",
  "ended_at": null,
  "spans": []
}
```

To ingest a real payload saved in `run.json`:

```bash
curl -fsS http://127.0.0.1:8000/api/runtime/ingest \
 -H "X-GAME-Ingest-Token: $GAME_RUNTIME_INGEST_TOKEN" \
 -H 'Content-Type: application/json' --data-binary @run.json
```

If using a separate Terminal, export the same collector secret there; a Uvicorn server environment variable is not automatically shared with other terminals. Avoid saving run.json in your source repository; real metadata can be sensitive. If there is no real runtime trace available yet, **stop after step 2**: discovery by itself cannot demonstrate observability.

5. Refresh Runtime observability, filter to the agent, open `View spans`; check the source IDs and times, then restart the application and verify persistence. Replay the exact same payload and verify there is still only one run.

## Normalized POST contract

- Required: `agent_id`, `source`, `external_run_id`, `started_at` (timezone-aware ISO 8601).
- Optional: `trace_id` (32 hexadecimal characters), `status` (`success`, `failure`, `unknown`), `ended_at`, `spans` (at most 100).
- Spans: `span_id` (16 hex chars), `parent_span_id` (16 hex chars or null), `trace_id`, `kind` (`agent`, `model`, `tool`, `mcp`, `other`), `name`, `status`, `started_at`, `ended_at`.
- Unrecognized fields are rejected to avoid accidental capture of prompt or tool content.
- Replaying the same company+source+agent+external run ID updates incomplete outcomes/spans, but conflicting start times, trace identities or span identities fail with HTTP 409.
- Ingestion accepts only existing agent IDs in the local company, including provider-discovered records.

## Validation

```bash
PYTHONPATH=src python -m pytest -q
node --check static/app.js
```

**Outstanding acceptance:** Build a Microsoft Foundry or OpenTelemetry adapter from verified available telemetry, correlate at least one actual invocation to an existing discovered agent and prove exact source-to-UI equivalence. Then proceed to AWS and Google telemetry, actual runtime tool/model attribution and FinOps integration in v0.3.4.

## Azure Foundry Application Insights collector increment

A read-only Azure Monitor Logs collector is now available in `scripts/collect_azure_foundry.py` for manual/dry-run import of **real** Azure Application Insights request/dependency trace metadata. See [Azure Foundry telemetry collector](azure-foundry-telemetry-collector.md) for permissions, mapping, safe attribution, limitations, and Mac commands. **Live cloud integration has not yet been validated with the customer's Azure project.**
