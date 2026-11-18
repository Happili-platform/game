# GAMe v0.3.5 — GitHub and Atlassian provider inventories

This update adds two **read-only** inventory integrations through **Provider Connections**. It is a development/localhost connection pattern, not yet production multi-tenant SaaS credential management.

## Before installation

Back up your local SQLite DB, `.env` and vault master key, then copy updated `src/`, `static/`, `tests/`, `docs/`, `requirements.txt`, and other application files into your Git working copy. Do **not** replace your local DB or vault key. Install requirements: `pip install -r requirements.txt`. Restart uvicorn and hard-refresh the browser. Log in as Admin / Provider Admin with `connections.manage`, `connections.credentials`, and `connections.discover` capabilities; viewing Trust Graph requires `agents.view`.

## GitHub: existing Happili-platform GitHub App

Precondition: App ID (numeric), private key PEM, organization `Happili-platform`. GitHub App installed on the organization with Repository Metadata (read) and Organization Administration (read). Your prior local test saw 8 repositories and 1 installed app; actual inventory is fetched live, not hard coded.

1. Go to **Workspace → Provider connections → Onboard a provider**.
2. Provider: **GitHub — read-only inventory**.
3. Label: `Happili GitHub inventory`.
4. Organization: `Happili-platform`.
5. Authentication: `GitHub App PEM (encrypted; localhost only)`.
6. Enter the **numeric App ID**, not the OAuth Client ID beginning `Iv`.
7. Paste the app **private key PEM** into the protected credential field (never commit or send to chat). Save.
8. Choose **Test connection**. A successful read-only test will display repository and app installation counts without writing inventory.
9. Choose **Discover now**. The connector obtains the installation ID automatically, then enumerates authorized repositories and installed GitHub Apps. It does not read repository contents or create agent links.
10. Open **Trust Graph**. Provider resources appear in the resource table at the bottom, not as AI agents or tools. The Trust Graph itself displays only known agent records and tool capability evidence.

GitHub App authorization uses signed short-lived JWTs and installation tokens. No installation access token is stored in the DB. GitHub API endpoints are fixed to `https://api.github.com` and the selected organization.

## Atlassian: headless Rovo MCP inventory

1. In Atlassian Administration, review **Rovo → Rovo MCP server → Authentication** and enable API token authentication for your organization if allowed by policy.
2. Create an appropriately scoped **Atlassian service account API key** (Bearer token) with the lowest permissions needed. Its underlying account must have permission to use the relevant Atlassian sites/products. Do not use a high-privilege personal account.
3. Under **Workspace → Provider connections**, select **Atlassian Rovo MCP**.
4. Label: `Happili Atlassian Rovo`.
5. Endpoint: `https://mcp.atlassian.com/v2/mcp` (the only permitted endpoint).
6. Authentication: **Service account API key (encrypted; localhost only)**. Save the API key through the protected credential form.
7. Select **Test connection**, then **Discover now**.
8. Open **Trust Graph**: **Inventory** shows MCP capabilities exposed by `tools/list`; the separate provider resources section shows matching tool catalog records.

**Important scope limitation:** The official Rovo MCP v2 server exposes a primary tool catalog and can dynamically offer more tools through its `discover` tool. This read-only update does **not** execute `tools/call`, including the `discover` tool; thus it cannot claim to have enumerated all dynamic tools. There are no generated agent-to-tool edges or observed invocations. If Atlassian requires OAuth rather than headless API keys, this build does not yet support that flow. MCP servers requiring unsupported session/transport behavior may fail with an explicit error rather than saving an incomplete catalog.

## API checks

- `GET /api/providers` — new provider types.
- `GET /api/connections` — connection health and credential presence, never the secret.
- `POST /api/connections/{id}/test` — **no inventory write**.
- `POST /api/connections/{id}/discover` — writes inventory metadata and audit entry.
- `GET /api/provider-inventory` — tenant- and role-scoped provider resources.
- `GET /api/trust-graph` — tool catalog + separately evidenced agent links.

## Security, data integrity, remaining work

- Encrypted private keys/API keys require a stable, separately protected vault key. Key loss makes saved credentials unavailable.
- The existing `legacy` mode and credential submission are intentionally limited to loopback/local development. Do not publish this server to the internet or treat it as production SaaS.
- Stable provider resource keys are tenant + connection + kind + external resource ID. Repeat synchronizations upsert instead of duplicating records; failed fetches do not create partial snapshots.
- Tool listings **do not prove access or execution**. A repository, installed app, or MCP tool is not itself an AI agent.
- Removed provider resources remain as **last-seen historical entries** after subsequent syncs; stale record classification and full reconciliation are next-phase work. Connection deletion / confirmed scope change removes associated local provider inventory, including tool links, so export evidence before doing so.
- Tests use mocks and local TestClient. Live API validation of this build is pending in your environments.

Sources: GitHub REST App installation docs (docs.github.com/en/rest/apps/installations), GitHub organization app installations (docs.github.com/en/rest/orgs/orgs), Atlassian Rovo MCP official docs (developer.atlassian.com/cloud/rovo-mcp/).
