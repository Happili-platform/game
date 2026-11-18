# GAMe Product Brief

**Status:** Product concept and implementation snapshot. The current application is GAMe 0.3.2.2, a local development prototype. Product hypotheses below are not validated customer outcomes or a commercial commitment.

## Vision

Give enterprise architecture, security, and FinOps teams a clearer view of AI agents across supported platforms, including ownership, governance review, and recorded usage.

Organizations using multiple AI agent platforms may lack a consistent inventory, accountable owners, and a way to prioritize governance review. The product direction is to make the available evidence visible and reviewable before considering provider-side enforcement.

## Current Prototype

The 0.3.2.2 release provides:

- Manual agent registration and scoped, on-demand read-only discovery for Microsoft Foundry, Google Agent Engine, AWS Bedrock AgentCore, and AWS Bedrock Agents Classic.
- A private registry inventory push API authenticated through the OIDC API mode.
- Fixed, deterministic advisory findings for missing ownership, inactive assigned Business Owners, production or sensitive-access approval gaps, configured-budget overruns, and stale manually managed agents.
- Manually recorded usage costs and monthly aggregation. These values are not imported from provider billing systems.
- Local password authentication, server-enforced roles and resource scopes, company branding, Business Owner approval workflow, and an application audit view.
- OIDC bearer-token validation and tenant-scoped API access. Browser-based enterprise SSO and production multi-tenant hosting are not included.

The implementation is described in [architecture.md](architecture.md), [single-company-rbac.md](single-company-rbac.md), and [security-gaps.md](security-gaps.md).

## Not Yet in the Prototype

- Configurable governance rules, evidence attachments, exports, and remediation integrations.
- Provider billing ingestion or reconciliation; recorded usage is entered manually.
- Agent suspension, runtime guardrails, tool interception, or model policy enforcement.
- General cross-platform discovery beyond the implemented connectors and their explicit scopes.
- Browser SSO with MFA, production secrets management, production database isolation, and a hosted SaaS operational platform.
- AI-based reasoning analysis, behavioral assurance, or ROI measurement.

## Pilot Evaluation

Potential measures for a future, authorized pilot:

- Inventory reconciliation: independently verified known agents represented / total known agents in the agreed scope.
- Ownership completeness: records with independently confirmed owners / inventoried records.
- Spend reconciliation error: variance from provider billing for the same scope and period.
- Finding precision: confirmed actionable findings / reviewed findings.
- Time required to identify an owner and triage a flagged agent.

Do not present these as measured results until they have been validated using first-party pilot evidence.

## Commercial Hypothesis

An enterprise subscription with tiers based on monitored agents and optional private deployment is one pricing hypothesis. Per-agent, per-platform, and flat subscription models require customer discovery; no price or purchasing model has been established.

## Product Independence

This concept is independently authored. Validate requirements through first-party interviews, public standards, and authorized provider APIs. Do not imply endorsement or use proprietary third-party analyst materials as product specifications.
