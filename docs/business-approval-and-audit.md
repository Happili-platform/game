# GAMe v0.3.2.2 — Business ownership, approvals, and audit log

**Status:** Implemented in the local development prototype. Approval and audit records are advisory application data; they do not enforce provider policy, authorize external spending, or form a tamper-evident audit archive.

## Separation of duties

- **Admin** (technical) configures users, company branding, and provider connections, and can assign an accountable Business Owner or submit an agent for approval. Admin **cannot approve or reject** an agent.
- **Provider Admin** can assign an accountable Business Owner and submit requests, but only within authorized provider/agent scopes. Provider Admin **cannot approve or reject**.
- **Agent Owner** may submit agent requests within assigned scope; cannot approve.
- **Business Owner** is an independent, scoped role. Only the **active Business Owner explicitly assigned to an individual agent** may approve or reject a pending request. Even a Business Owner with access to multiple agents may decide **only** on agents explicitly assigned to them. Business Owner cannot manage users, connection credentials, or approve unassigned agents.
- **Auditor** can view company-wide audit records but cannot modify or approve agents. Admin can view audit records under **Administration → Audit Log**. Viewer has no audit access.

Higher-level technical role inheritance deliberately **does not inherit the Business Owner's approval capability**. This is a separation-of-duties requirement, not an omission.

## Workflow

1. Company Admin creates an active user with the Business Owner role in **Administration → Users & Roles**. Their scope is selected-agent only.
2. Admin or authorized Provider Admin opens an agent and assigns that user as **Business Owner**. A Business Owner's scope is updated to include that agent. Reassigning ownership revokes the previous Business Owner's assignment and resets any prior approval.
3. Admin / Provider Admin / Agent Owner submits a request with monthly budget (USD), cost center, and a business justification. Registration and discovery alone **never** confer business approval.
4. The assigned Business Owner signs in under their account and chooses Approve or Reject, entering a justification. The user who submitted the request cannot approve their own submission.
5. GAMe records timestamps, actor, agent, requested amount, cost center, and decision reason in `audit_events`. The approval state is stored separately from the cloud provider's own reported status. These are **advisory records** and do not authorize spending in the customer's external procurement or finance system unless that system is integrated.

## Permissions and persistence

- Existing `agents`, `discovered_agents`, `provider_connections`, `provider_credentials`, users, and sessions are preserved by the SQLite schema update.
- New `agent_governance` rows are keyed by `(tenant_id, agent_id)`; source/provenance metadata stays unchanged.
- Older agent approval fields are retained as `provider_approval_status` metadata, **not** adopted as verified GAMe business approval. All previously unreviewed agents begin as `not_reviewed` in the new workflow.
- Credentials, API keys, passwords, and session cookies are **never included** in audit-event details.
- `Audit Log` shows the latest 200 events in the browser. This is a local-development audit view, not a tamper-evident archive. It lacks retention/export policies, independent storage, SIEM integration, and external cloud-side audit correlation.
- In this iteration, Business Owner assignment uses GAMe **local password user accounts**. The existing OIDC role catalog includes Business Owner but OIDC-based owner identity binding and full SSO still need implementation before enterprise release.

## Security / deployment scope

Keep the password-authenticated server bound to `127.0.0.1`. Multi-user browser SSO, strong credential recovery, persistent independently protected audit logs, and finance-system approval integrations remain prerequisites for commercial hosting. No provider-side agent is modified by approval actions.
