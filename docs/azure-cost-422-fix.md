# v0.3.4.1 Azure Cost Management ingestion — HTTP 422 compatibility fix

This targeted patch aligns the Azure cost collector and FastAPI validation for Azure `ResourceId` values. Some ActualCost rows are not resource-specific and return a blank `ResourceId`, and resource identifiers can include valid special characters not previously permitted.

- Accept empty `resource_id` as **unassigned Azure cost**, not as an agent; the `scope`, `usage_day`, and `currency` remain part of the stable replay key.
- Accept Azure resource path characters without accepting control characters.
- Preserve empty/null Azure ResourceId values as an empty string, not the misleading literal `none`.
- If the backend returns 422 again, the collector prints the field location and validation message without printing the original cost payload.
- No change to existing SQLite tables or previously imported costs. Re-running the same cost period uses UPSERT, not addition.

## Install

Stop the web server, unpack this ZIP **over the existing project directory**, restart the server with the existing `GAME_RUNTIME_INGEST_TOKEN`, then re-run `scripts/collect_azure_costs.py` with the existing scope and `--days 7`. The API and collector both need this patch.

If another 422 occurs, inspect the new `VALIDATION ERROR` output to identify the actual rejected field. A 422 is not proof that Azure collection has failed; Azure retrieval can succeed before local validation rejects the batch.
