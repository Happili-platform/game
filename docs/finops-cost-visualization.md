# Azure resource-cost visualization — v0.3.4.1 UI improvement

The Agentic FinOps page displays **Azure Cost Management ActualCost** by currency, service, and resource. This is independent from observed model tokens and separately estimated per-agent model cost.

## UI behavior
- Displays total Azure ActualCost **separately by currency**, without converting or combining currencies.
- Shows the number of distinct resource/scope/currency combinations and imported daily charge rows.
- Uses Azure resource provider namespace to classify recognized services such as Azure AI / Foundry, Storage, Log Analytics, App Service, and Azure Monitor. These labels are UI groupings, not official billing-service names.
- Aggregates and ranks Azure resource identifiers by summed charges for the selected date period. Search filters by resource, provider grouping, or scope.
- Hides long ARM identifiers in expandable details but retains their original values, scope, date range and row counts.
- Indicates charges are **scope-level**, **not agent-attributed**, **not invoice-final**; no guessed cost allocation.
- Does not modify stored Azure cost records, telemetry, collectors, or APIs.

## Install
Overlay the update ZIP into the parent directory containing `game-mvp`, restart the app, and hard-refresh the browser (Cmd + Shift + R).

## Verification
1. Navigate to Agentic FinOps → Azure resource costs.
2. Confirm the totals match `GET /api/finops/azure-costs?period=30d`, separately by currency.
3. Confirm Service and Resource breakdowns reconcile to the same rows.
4. Search for a resource and expand View to inspect the full Azure resource and scope identifiers.
5. Switch time periods; totals and breakdowns should update.

## Future scalability
For large billing data sets, move aggregation, filtering, and pagination to dedicated backend summary endpoints. This UI currently aggregates the returned data client-side and shows the first 100 filtered resources.
