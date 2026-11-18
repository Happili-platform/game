# GAMe v0.3.5 — Trust Graph foundation and provider onboarding

## Scope and status

**Implemented:** tenant-scoped tool catalog, stable upsert identity, agent/tool evidence links, deduplicated recording, server-side RBAC, audit events, and read-only graph response under `/api/trust-graph`. These are local API contracts that accept provider snapshots; they do **not** call GitHub or Atlassian themselves. Not yet implemented: native GitHub or Atlassian connectors, automated polling, MCP protocol negotiation, policy enforcement, or guaranteed attribution from vendor audit logs to individual AI agents. No direct remote access is attempted.

**Data truth:** provider-supplied capabilities are not evidence that any particular agent can access them. `declared_configuration` indicates configuration evidence; `observed_invocation` requires an actual, externally verifiable invocation record. Never infer a user-agent linkage from an organization-wide audit event without an authoritative mapping. Snapshot ingestion is upsert-only; disappearing tools are not removed without a confirmed full-sync and explicit lifecycle reconciliation.

## Proposed GitHub provider setup (read-only)

1. In the GitHub organization, use **Settings → Developer settings → GitHub Apps → New GitHub App** (account-level navigation varies), name it `GAMe Inventory`, and configure it for the organizations to be inventoried. **Do not request webhook delivery** initially; leave permissions at the least privilege needed for the intended API calls.
2. For repository inventory, use repository **Metadata: Read-only** (mandatory baseline). To list the organization's installed GitHub Apps through `GET /orgs/{org}/installations`, GitHub documents **Organization Administration: Read-only** and an **organization owner** authentication requirement. Confirm the ownership requirement with the chosen authentication method; do not assume an installation token alone bypasses it. Avoid Contents, Secrets, Actions, Administration Write, and Org Write unless subsequently proven necessary.
3. Install the app on the intended organization(s), selecting repositories as required. Capture **App ID**, **Installation ID**, and a securely held **private key**. Generate installation access tokens server-side; they are temporary. Do **not** store long-lived installation access tokens or send the key in graph snapshot JSON.
4. Validate with an authorized installation token: `GET https://api.github.com/installation/repositories` to verify accessible repositories. To enumerate *other* installed apps use `GET https://api.github.com/orgs/ORG/installations` with the authentication and role required by its official endpoint. Confirm that permissions returned for each installation are **granted GitHub App capabilities**, not proof of an AI agent's use.
5. If inventorying **GitHub MCP Server** tools, use the official GitHub MCP server configuration and toolset documentation in a dedicated, read-only integration. Do not run mutating tools merely to discover them. GitHub App installations and MCP tools are distinct entities; model both only with sourced identifiers.
6. Maintain a provider connection in GAMe for GitHub (existing connection UX may not yet offer this provider type). Until a native connector is built, an authenticated importer with `connections.discover` can POST verified tool metadata to the snapshot endpoint. Link individual agents only when a GitHub configuration, gateway record, or invocation event identifies the agent.

Official references:
- https://docs.github.com/en/rest/orgs/orgs#list-app-installations-for-an-organization
- https://docs.github.com/en/rest/apps/installations
- https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app

## Proposed Atlassian provider setup (read-only)

1. In **admin.atlassian.com**, select the organization and confirm site-level access and approvals for Rovo MCP. Under **Apps → AI settings / Rovo MCP server**, review which permission groups are enabled. Restrict read/search permission groups; do not enable `delete_jira`, `manage_jira`, or unnecessary write scopes.
2. For a headless integration, create a dedicated **service account** at **Directory → Service accounts**, assign only the required product/site visibility, then create an **API token or service-account API key with narrowly scoped read access**, according to Atlassian's current credential options. Organization admins must allow API-token authentication for Rovo MCP. Alternatively use OAuth 2.1 for interactive sign-in; do not confuse this with Atlassian REST API service-account OAuth 2.0 credentials.
3. Use the officially documented Atlassian Rovo MCP endpoint: `https://mcp.atlassian.com/v2/mcp`. For full paginated discovery, Atlassian documents `https://mcp.atlassian.com/v2/mcp?tools=all` (actual availability is permission dependent). The server exposes some tools dynamically through `discover`; a bare `tools/list` is not a complete inventory.
4. Keep credentials in an approved vault, never in snapshot payloads. A future connector should negotiate Streamable HTTP MCP with authentication, enumerate approved tool metadata without invoking write operations, then upsert the catalog in GAMe.
5. Review **Atlassian Administration → Insights → Audit log**, filtering for MCP user actions. Audit events can show tool, action, and user. They do not necessarily identify the originating AI agent: link an event to a specific agent only with corroborating gateway/client correlation evidence.
6. Review the available admin visibility for connected OAuth applications and Rovo MCP activity; record source scope and collection timestamps. Keep SaaS site permissions separate from MCP tool catalog visibility.

Official references:
- https://developer.atlassian.com/cloud/rovo-mcp/guides/getting-started/
- https://developer.atlassian.com/cloud/rovo-mcp/guides/authentication-and-authorization/
- https://developer.atlassian.com/cloud/rovo-mcp/guides/supported-tools/
- https://support.atlassian.com/security-and-access-policies/docs/monitor-atlassian-mcp-server-activity/
- https://support.atlassian.com/user-management/docs/manage-api-tokens-for-service-accounts/

## API exercise (after creating a real provider connection)

The examples use GAMe's currently authenticated API context. Replace `CONNECTION_ID`, `AGENT_ID`, and `TOOL_ID` with *actual* returned IDs. Do not submit secrets or personal data.

```
curl -sS -X POST "$GAME_URL/api/trust-graph/tools/snapshot" \
  -H "Authorization: Bearer $GAME_TOKEN" -H 'Content-Type: application/json' \
  -d '{"connection_id":"CONNECTION_ID","namespace":"github-org:example","tools":[{"external_id":"github.mcp.issues.read","name":"Read GitHub issues","capability":"read"}]}'

curl -sS "$GAME_URL/api/trust-graph" -H "Authorization: Bearer $GAME_TOKEN"

curl -sS -X POST "$GAME_URL/api/trust-graph/links" \
  -H "Authorization: Bearer $GAME_TOKEN" -H 'Content-Type: application/json' \
  -d '{"agent_id":"AGENT_ID","tool_id":"TOOL_ID","evidence_type":"declared_configuration","evidence_reference":"config://verified-provider-source"}'
```

Note: In explicitly enabled loopback-local development mode, authentication differs; normal deployments require the configured bearer identity. For manually registered agents without a provider connection, a scoped provider administrator can still link against a separately inventoried tool, but the linkage requires evidence.

## Release acceptance checklist

- [x] Existing tenant / role boundaries enforced on graph read and write endpoints
- [x] Stable namespace + external ID per provider connection
- [x] No inference of invocation from discovered tools
- [x] Evidence type and external reference mandatory for links
- [x] Idempotent upsert and audit events
- [ ] GitHub App connector tested against a live GitHub organization
- [ ] Atlassian Rovo MCP connector tested against a live Atlassian organization
- [ ] Proven agent identity correlation from runtime/gateway events
- [ ] Source completeness, retirement and stale-record reconciliation
- [x] Read-only Trust Graph UI with graph, tool inventory and evidence views
- [ ] Governance scoring integration

## Trust Graph UI verification (v0.3.5 UI increment)

1. Restart the application and sign in with a user who has `agents.view`. Open **Workspace → Trust Graph** or visit `http://127.0.0.1:8000/#trustGraph`.
2. With no provider snapshots ingested, the Graph view should display an empty state, and Inventory/Evidence should contain no fabricated tools or invocations.
3. Once an authenticated snapshot is imported, use **Inventory** to find each tool by connection, namespace, identity and capability. Use **Evidence** for declared or reported links and their source references.
4. Use **Graph** to inspect agent/tool nodes and the different line styles for configured relationships versus reported invocation evidence. Search and filter as required. The interactive visualization shows up to 30 nodes of each type on larger estates; the tables are not capped.
5. Account permissions and resource scoping are enforced on the API. The page is hidden for users without `agents.view`. The UI performs no provider calls or write operations.
6. If the interface looks unchanged, hard-refresh the browser; stylesheet and JavaScript asset URLs now carry a new version query.

**No provider-side configuration change is required to display the page.** Live tool inventory still requires native connectors or authenticated ingestion of verified snapshots.
