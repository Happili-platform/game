# GAMe v0.3.5 — Provider Filter & Graph Zoom

## User guide

1. Navigate to **Workspace → Trust Graph**.
2. Scroll to **Provider resources** and select **All providers**, **GitHub**, or **Atlassian**. The list is built from actual discovered provider connection types, so additional provider types will appear as they are connected and synchronized. Type a resource name to narrow results further. The count shows displayed rows versus the entire authorized inventory.
3. In the **Graph** tab, use **+** to zoom in (125% of the current scale), **−** to zoom out, and **Fit to view** to fit the complete selected graph within the viewport. The zoom level is displayed as a percentage; the canvas can scroll when zoomed.

## Important data semantics

The provider resource inventory contains GitHub repositories/installed applications and Atlassian MCP tool metadata; it is **not** proof that any AI agent has access or has invoked any tool. The graph visualizes registered agents and normalized MCP tools and includes only evidence-backed relationships. GitHub repositories do not automatically appear as agent-to-tool graph nodes.

## Install without losing data

Back up the existing SQLite DB, `.env` and credential vault key; merge source files only, preserving private settings. Restart the app and hard-refresh the browser. No schema changes or provider-side reconfiguration are required.

## Validation

Run `PYTHONPATH=src python -m pytest -q` and `node --check static/app.js`. Test filters and zoom interactively against a local running GAMe instance; automated UI tests assert the existence of handlers, while backend tests cover tenant isolation and persistence.
