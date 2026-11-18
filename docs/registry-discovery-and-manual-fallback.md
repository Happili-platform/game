# Agent Registry — automatic discovery and unmanaged fallback (v0.3.4.2 UI refinement)

- **Default:** provider-authorized discovery creates/inventories agents; manually creating each provider agent is not required. Discovery frequency and provider coverage vary. Microsoft Foundry automatic discovery/mapping requires a configured provider connection and collector.
- **Secondary fallback:** under **Agent Registry → More actions → Register unmanaged agent**, authorized roles with `agents.register` may create an explicitly declared record when provider integration cannot discover the agent. This does not invoke the provider, prove identity, authorize spending, or confirm live execution.
- **RBAC:** the `More actions` menu is hidden when `agents.register` is absent. The existing `POST /api/agents` backend capability check is the authorization boundary. No permissions or approval rules changed.
- **No data migration:** existing agent records, provider connections, run telemetry, Business Owner approvals, and Azure costs are unchanged. HTML, JavaScript and CSS ship together as one unit.
- **Validation:** verify no global registration button; the fallback is visible only to permitted users in Agent Registry; normal discovery/refresh remains functional; manually registered records are not represented as verified.
