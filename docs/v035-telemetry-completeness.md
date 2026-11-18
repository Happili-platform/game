# v0.3.5 — Azure Foundry collection completeness

The Azure Application Insights collector now automatically splits a time window when `AppRequests` or `AppDependencies` returns the configured `--max-rows-per-table` count. It recursively queries the earlier and later halves using half-open UTC intervals until every queried slice returns fewer than the cap. This avoids truncation of a busy hour when each subrange can be collected.

Safety limits: at most 128 queries **per table per collection**, and an individual one-second slice may not be saturated. If limits are hit, collection fails **before any telemetry is submitted** to GAMe. Azure query errors also stop collection. Partial data is not reported as a successful heartbeat. Smaller windows and sufficient ingestion lag remain operational necessities. Query budgets are conservative by design.

Existing automatic Microsoft Foundry inventory reconciliation, failure-on-ambiguous identity, and token-usage deduplication are unchanged. The collector remains read-only to Azure, reports only allowlisted runtime metadata, and imports to the loopback GAMe API. This release does not add durable checkpoints or guarantee complete late-arriving source events; operators should continue scheduling overlapping windows.

Validation: `PYTHONPATH=src python -m pytest -q tests/test_azure_query_windows_035.py` and then the full test suite. Live Azure validation must be performed in the deployment environment. Do not commit `.env`, local databases, credentials, or local `.venv` to Git.
