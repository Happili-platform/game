# v0.3.3 — Runtime Observability enhancements

Built on the user-provided GitHub Actions-enabled baseline and the working Azure Foundry collector. **No database reset, simulated data, or provider write access.**

## Included

- Agent filter and period selector: last 24 hours, 7 days, 30 days or all retained history.
- Separate **executions in selected period** and **total historical executions**. Period selection only filters API results; it never deletes records.
- Daily execution counts with failures and observed average duration; unknown durations/outcomes remain unknown, not zero.
- Persisted **last successful Azure collection** and result counts. A successful collector query with zero rows still records its completion. A failed collection does not falsely advance the successful timestamp.
- Azure `AppRequests.ResultCode` used as a fallback where `Success` is absent: 200–399 = successful request, 400–599 = failed request, all else unknown. This is HTTP request outcome evidence, **not proof of an agent's business-task success**. Tool/dependency HTTP codes never determine the overall execution outcome.
- Opt-in macOS `launchd` collector every 15 minutes by default, querying the previous 60 minutes with a 5-minute Azure ingestion lag. Overlap handles normal telemetry delays, and the existing idempotent ingestion API deduplicates records. The wrapper prevents overlapping local executions.

## 1. Upgrade

Back up your SQLite database and `~/.config/game/master.key`. Overlay the update ZIP into the parent of `game-mvp`, **not** into the project itself. Existing `data/`, virtual environment, credentials, and `.git/` are excluded.

Restart Uvicorn, loading your **existing** collector token from `~/.config/game/runtime-ingest-token`. Use the same token in the Azure collector. **Do not regenerate this token** if current telemetry ingestion works.

## 2. One-shot validation (no scheduler)

```bash
cd /Users/nanna/Documents/Siddhartha-Collabera/Develop/game-mvp
source .venv/bin/activate
export GAME_RUNTIME_INGEST_TOKEN="$(cat ~/.config/game/runtime-ingest-token)"
python scripts/collect_azure_foundry.py \
  --workspace 00102aad-d274-4d8f-9eb1-564fdd0d3f9e \
  --mapping "$HOME/.config/game/azure-agent-map.json" \
  --lookback-minutes 60 --lag-minutes 5
```

View **Agent runtime observability**. Select **All history** to see past imports; select **Last 24 hours** to restrict to recent executions. The **Last successful Azure collection** line should show a new timestamp even if this particular collection imported zero runs.

## 3. Optional automatic collection on macOS

Requires an installed `.venv` in this project, an existing mapping file, a readable Azure CLI login (`az login`) or preconfigured workload credentials, and the GAMe server running at `127.0.0.1:8000`.

```bash
cd /Users/nanna/Documents/Siddhartha-Collabera/Develop/game-mvp
source .venv/bin/activate
chmod 600 ~/.config/game/runtime-ingest-token
python scripts/install_azure_collector_launchd.py \
  --workspace 00102aad-d274-4d8f-9eb1-564fdd0d3f9e \
  --mapping "$HOME/.config/game/azure-agent-map.json" \
  --interval-seconds 900 --lookback-minutes 60 --lag-minutes 5
launchctl bootstrap gui/$(id -u) \
  "$HOME/Library/LaunchAgents/com.happili.game.azure-foundry-collector.plist"
launchctl kickstart -k gui/$(id -u)/com.happili.game.azure-foundry-collector
```

Check status and logs:

```bash
launchctl print gui/$(id -u)/com.happili.game.azure-foundry-collector
tail -n 30 ~/.config/game/logs/azure-collector.stderr.log
tail -n 30 ~/.config/game/logs/azure-collector.stdout.log
```

To stop auto-collection:

```bash
launchctl bootout gui/$(id -u) \
  "$HOME/Library/LaunchAgents/com.happili.game.azure-foundry-collector.plist"
```

To change the interval, first boot out the existing job, back up/remove its plist and rerun the installer. The token is **not** embedded in the launchd plist or logs. The wrapper reads the same token file used for manual imports. Logs report trace metadata only, but still protect log files as operational metadata. Run `chmod 700 ~/.config/game/logs` if needed.

**Limitations:** launchd LaunchAgents run under the logged-in macOS user. The application server must separately be running. Azure CLI refresh may require an interactive login again; this is not a substitute for renewable workload identity. Telemetry delayed beyond the configured overlap may require a one-off 24-hour backfill. No automatic deletion, configurable database retention, checkpoint/watermark, pagination, ingestion performance tuning, SaaS MCP collection, or real model cost attribution is included. A failed Azure query or missing GAMe server will be visible in local stderr but currently does not create a backend `last_failure_at` record.

## 4. Acceptance checks

1. Existing two imported Azure Foundry traces remain visible under **All history** after upgrade.
2. Switching to last 24 hours may show zero recent traces, while the historical total stays unchanged.
3. One-shot collection with no new records returns `Imported: 0`, and the dashboard's **Last successful Azure collection** updates.
4. Repeat the collection to ensure replays do not add duplicate executions.
5. Confirm the launchd job only runs after explicit enrollment, at the chosen interval.
6. Confirm unknown statuses remain unknown for telemetry lacking trustworthy outcome evidence.

No live Azure execution or macOS launchd enrollment was performed by the development environment; test those on your machine.
