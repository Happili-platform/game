# F01 — Canonical Agent Identity Schema

Status: Proposed
Release: GAMe v0.3.6
Issue: #32
Architecture decision: ADR-0001

## 1. Objective

Introduce stable canonical agent identities without rewriting or deleting
existing agent, governance, runtime, FinOps, or Trust Graph records.

The initial release retains the existing API agent IDs.

## 2. Proposed logical entities

### canonical_agents

One row per logical agent within a tenant.

- id: Immutable GAMe-generated identifier
- tenant_id: Owning tenant
- created_at: Creation timestamp
- updated_at: Last metadata update timestamp

The canonical ID is never derived from a display name or provider ID.

### agent_identity_mappings

Associates an authoritative external identity with a canonical agent.

- id: Mapping identifier
- tenant_id: Tenant boundary
- canonical_agent_id: Canonical identity
- provider: Normalized provider type
- scope_key: Verified authoritative provider scope
- external_id: Provider-defined agent identifier
- connection_id: Optional collection connection reference
- verification_status: verified, pending, or conflicted
- evidence_reference: Identity source reference
- first_seen: First observation
- last_seen: Last successful observation

Verified mappings must be unique within:
tenant_id + provider + scope_key + external_id.

Connection ID is not part of this permanent uniqueness key.

### agent_legacy_references

Preserves the relationship between old application IDs and canonical IDs.

- tenant_id
- source_table: agents or discovered_agents
- legacy_agent_id: Existing agt-* or ext-* identifier
- canonical_agent_id
- created_at

One legacy reference resolves to exactly one canonical agent.

### agent_identity_conflicts

Records identity conflicts requiring investigation.

- id
- tenant_id
- provider
- scope_key
- external_id
- conflict_type
- evidence_reference
- status: open or resolved
- created_at
- resolved_at
- resolved_by

Conflicts must not automatically change historical relationships.

## 3. Provider scope requirements

Microsoft Foundry:
- Trusted tenant/subscription/project identity
- Stable project or resource identifier
- Provider agent identifier

AWS AgentCore or Bedrock Agents:
- Trusted AWS account
- Region
- Service namespace
- Provider agent identifier

Google Agent Engine:
- Trusted Google project
- Location
- Provider resource identifier

Private/self-hosted agents:
- Verified registry authority
- Registry namespace
- External agent identifier

Missing authoritative scope information means identity resolution
is unresolved. A connection display label is not a reliable scope.

The exact provider-specific scope fields must be validated against
existing connector data before implementing the resolver.

## 4. Deterministic resolution

1. Validate tenant, provider, scope and external ID.
2. Reject duplicate conflicting identities in one discovery batch.
3. Search for an exact verified external mapping.
4. Return the existing canonical ID when exactly one mapping matches.
5. Do not use display-name similarity as merge evidence.
6. Treat multiple conflicting matches as unresolved.
7. For a new, fully verified identity, create a canonical agent
   and a mapping atomically.
8. Preserve the same canonical ID during subsequent discovery.

Cross-provider links require separately verified identity evidence.
Manual agents are not merged with discovered agents by name.

## 5. Non-destructive migration

Phase A:
- Create additive identity tables and indexes.
- Preserve agents and discovered_agents unchanged.

Phase B:
- Map existing manual and discovered IDs.
- Backfill only identities with sufficient authoritative evidence.
- Flag incomplete or conflicting identities for review.

Phase C:
- Introduce a compatibility resolver.
- Keep existing agent IDs valid for APIs and stored relationships.

Phase D:
- Integrate new provider discovery with the identity resolver.
- Test connection reconfiguration and deletion behavior.

Do not rewrite existing runtime_runs.agent_id, finops_usage.agent_id,
agent_governance.agent_id, policy_findings.agent_id, or
trust_links.agent_id during the first migration.

No local production or development database will be modified
until disposable-database migration tests pass.

## 6. Security and access control

- Every lookup is tenant-scoped.
- Cross-tenant mappings are prohibited.
- Identity resolution grants no additional permissions.
- Conflicts and administrative decisions are audited.
- Provider credentials are never stored in identity mappings.

## 7. Test matrix

- Repeated provider discovery retains canonical ID.
- Duplicate external identity in a batch is detected.
- Conflicting source identity fails closed.
- Same external ID in different provider scopes stays distinct.
- Multiple connections to the same verified resource do not
  create duplicate canonical agents.
- Renaming a provider agent retains identity.
- Tenant boundaries prevent cross-tenant resolution.
- Existing agt-* and ext-* references remain valid.
- Runtime, FinOps, approvals and graph history survive migration.
- Migration is repeatable without duplicate rows.
- Connection changes do not silently reassign historical identities.
- Invalid or incomplete mappings do not grant authorization.

## 8. Release constraints

This document is a proposed design, not an implemented schema.

Existing databases, vault keys, provider credentials, and external
resource identifiers must remain unchanged until migration approval.
