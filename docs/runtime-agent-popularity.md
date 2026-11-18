# v0.3.3 — Runtime agent popularity and daily execution breakdown

## Purpose

The Runtime Observability page now differentiates **recorded executions by agent** while remaining usable for large enterprise inventories (100+ agents). This release is a UI/API enhancement to the existing v0.3.3 runtime foundation. It neither collects new kinds of telemetry nor changes retention, source credentials, provider discovery, RBAC, or historical records.

## Dashboard

- **Most used agents:** sorted by the number of observed runs in the selected time period; counts and share of matching observed runs are displayed. Clicking a row filters the existing execution history and trace viewer to that agent.
- **Daily executions by agent (UTC):** a stacked vertical bar for each active UTC date, labelled with the total recorded runs that day. Each Top N agent has a distinct color. All remaining agents are grouped into gray **Others**. Hover on a segment to see agent, date, and run count.
- **Top N:** 5 (default), 10, or 20. For small deployments, only agents with recorded runs appear. For large ones, never render hundreds of individually colored series.
- **Search ranking:** filter the popularity ranking and stacked visualization by agent name or internal ID. This does not alter the existing global metric tiles; the popularity panel explicitly reports its own matched count and total in the current agent/period scope.
- **Period:** reuses Last 24 hours, Last 7 days, Last 30 days, and All history. For All history with more than 60 distinct active days, the chart only shows the **60 most recent active days**, while ranking and counts span the full period. A visible note explains this limitation.

## API contract

`GET /api/runtime/popularity?period=7d&top_n=5&search=&agent_id=`

Requires the existing `runtime.view` capability. Values: `period=24h|7d|30d|all`, `top_n=1..20`, optional `search` (up to 120 characters), optional `agent_id`. Data is aggregated in SQLite (one run counts once, not once per span); response fields include `runs`, `scope_total_runs`, `active_agents`, `ranking`, `others_runs`, `others_agents`, `daily`, `chart_days_truncated`, and `coverage`.

All returned agent identifiers and aggregated counts are visibility-scoped using the existing GAMe RBAC resource access checks. No fabricated records, no inferred unique users, and no new costs are created. An agent with zero executions is absent from the usage ranking, not considered an error.

## Operational verification

1. Confirm the previously imported Microsoft Foundry runs remain visible under **All history**.
2. Set **Top 5**. The two observed agents should appear in separate colors in the chart, with observed run counts beside their names in **Most used agents**.
3. Change to **Top 10**, and test the **Search ranking** input. For a selected agent, counts should reconcile to its runtime history.
4. Select an agent in the ranking; verify that the execution table and trace drill-down filter to it.
5. Switch to **Last 24 hours**, then **All history**. Old runs should reappear in historical views without being imported again.
6. In a future larger deployment, verify that more than Top N agents become **Others**, and the chart never attempts to assign 100+ unique series colors.

### Note on the metric name

“Popularity” is a convenience label for **run volume**, not number of distinct human users, quality, success, ROI, or business outcomes. Those require separate telemetry and attribution in later releases.


## Stable baseline and release compatibility

This feature extends **v0.3.3 Runtime Enhancements**. Install the complete four-file change together:
`src/game/runtime.py`, `static/index.html`, `static/app.js`, and `static/style.css`.
A `GET /api/runtime/popularity?period=all&top_n=5` check should return HTTP 200 with a JSON response (when signed in). A 404 indicates the wrong backend is running.
Historical telemetry is not altered. Use **All history** to show prior executions. The color palette is defined in `static/style.css` as `--runtime-series-*`; "Others" uses a neutral color. The Top N ranking is based on recorded run counts, not distinct users.
