# v0.3.4.2 — Runtime and FinOps access controls

## Role permissions

- Admin: company-wide runtime, scoped token and estimate information, Azure company-wide ActualCost, rate management, and user administration. **Does not approve/reject business requests**.
- Auditor: company-wide read-only runtime, token usage, estimates, Azure ActualCost and Audit Log.
- Provider Admin: runtime, tokens, estimates and budgets for their explicitly authorized provider or agents. No company-wide Azure billing.
- Agent Owner: runtime, tokens, estimates and budgets for their scoped agents. No company-wide Azure billing.
- Business Owner: runtime, tokens, estimates and approved budgets **only for agents assigned to that Business Owner**. Only that owner can approve business requests; no financial configuration.
- Viewer: overview and inventory only; runtime trace details and FinOps are not enabled by default.

Runtime history requires `runtime.view`; token summary requires `finops.usage.view`; estimated rates and budget visibility requires `finops.estimates.view`; Azure resource ActualCost requires `finops.billing.view`; rate writes require `finops.rates.manage`. All endpoints authorize on the server, regardless of client navigation state.

## Existing account permissions

Administration → Users & Roles → Edit an account. Select a primary role and review the inherited capabilities. For existing local password accounts the capability checkboxes can restrict access within the role's preset ceiling. Selecting a higher role resets to the new role's inherited defaults; checking a capability automatically checks its prerequisites; unchecking a prerequisite removes dependent capabilities. Save changes. User permissions apply on the next API request, including for already-open sessions.

The Admin role cannot remove `members.manage`; business approval cannot be granted to technical Admin through this UI. User permission changes are audit logged. OIDC membership editing continues to use the existing role-and-scope editor (individual capability overrides are currently for local password accounts only).

The application retains SQLite data and keeps tenant/company and resource scope checks. This development deployment is localhost only; production SSO and hardened multi-company tenancy remain out of scope.
