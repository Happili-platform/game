# ADR-0001: Canonical Agent Identity

- Status: Proposed
- Release: GAMe v0.3.6
- GitHub Issue: #32
- Parent Epic: #8
- Scope: Single-company development baseline
- Decision owner: siddpill

## Context

GAMe currently stores manually registered agents in `agents`
and provider-discovered agents in `discovered_agents`.

Manual records use `agt-*` IDs; discovered records use `ext-*`
IDs. Provider discovery deduplicates by connection_id and external_id.

Runtime, governance, policy, FinOps, and Trust Graph records may
reference either class of agent identity.

A common identity layer is needed without invalidating existing
references or destroying historical evidence.

## Decision

Introduce a GAMe-owned canonical agent identity, independent of
provider names, external IDs, display names, and connection IDs.

The implementation will be additive and backward compatible.

### 1. Canonical agent

Each logical agent receives an immutable internal canonical ID.

The canonical record belongs to exactly one tenant.

Names, provider status, ownership, approval, and observed activity
are attributes or related records, not identity keys.

### 2. External identity mapping

A separate mapping records:

- Tenant ID
- Canonical agent ID
- Provider and source type
- Authoritative source scope
- External agent identifier
- Provider connection reference, where applicable
- Verification status
- Source evidence and timestamps

A provider connection is a collection mechanism. It is not,
by itself, the permanent identity of an external agent.

### 3. Identity resolution

Resolution must be deterministic.

An exact, verified mapping returns the existing canonical ID.

Repeated discovery must not create additional logical agents.

Names and descriptions are insufficient to merge identities.

An ambiguous or conflicting match must fail closed and enter
a reviewable unresolved state.

No automatic cross-provider identity merging is allowed without
authoritative supporting evidence.

### 4. Historical compatibility

Preserve all existing `agt-*` and `ext-*` IDs.

Maintain their association with canonical IDs through explicit
legacy-reference mappings.

Existing runtime, governance, FinOps, audit, and Trust Graph
references must remain readable throughout the transition.

Do not rewrite historical foreign keys in the first migration.

### 5. Lifecycle and deletion

Failure to discover an agent does not prove deletion.

Missing, stale, and retired states must be distinguishable.

Changing or removing a provider connection must not erase
canonical identity or historical business evidence.

Existing destructive connection-management operations require
separate remediation before F01 can be declared complete.

### 6. Tenant isolation and security

All lookups and mappings are tenant-scoped.

No cross-tenant identity merging is allowed.

Identity resolution cannot grant additional permissions or
bypass existing resource-level authorization.

Identity decisions and manual resolutions must be audited.

### 7. Data migration

The migration must:

- Add new structures without dropping existing tables.
- Preserve existing database rows and encrypted credentials.
- Preserve existing agent IDs and their downstream references.
- Backfill only unambiguous legacy identities.
- Record unresolved mappings without guessing.
- Be repeatable, transactional, and safe to retry.
- Include backup, integrity, and rollback procedures.

The initial implementation must not operate on the user's
existing development database without a separate backup and
successful migration tests against disposable database copies.

## Proposed implementation sequence

1. Define canonical identity and mapping schemas.
2. Add migration and compatibility tests.
3. Implement deterministic identity resolution.
4. Backfill existing identities without changing legacy IDs.
5. Integrate provider discovery and collision handling.
6. Validate runtime, governance, FinOps, and Trust Graph references.
7. Review connection changes and deletion safety.
8. Complete regression and migration tests.

## Acceptance criteria

- Repeated discovery retains the same canonical identity.
- Duplicate or conflicting source records are not silently merged.
- Ambiguous identity resolution fails closed.
- Different tenants cannot share canonical identities.
- Provider name changes do not change canonical identities.
- Historical agent references remain valid.
- Existing approvals, runs, costs, and graph evidence survive migration.
- No database or credential loss occurs.
- Automated migration, authorization, and regression tests pass.

## Non-goals

- Automatic deduplication based solely on similar names.
- Automatic merging of agents from unrelated providers.
- Rewriting historical telemetry or financial transactions.
- Production multi-tenant SaaS deployment.
- Provider-side agent modification.

## Open design questions

1. Exact authoritative scope keys for each provider.
2. Whether the first release should expose canonical IDs in public APIs.
3. The administrative process for resolving ambiguous identities.
4. Handling provider ID reuse and connection scope changes.
5. The retention and audit requirements for deprecated mappings.

## Consequences

The additional identity layer increases schema and resolution
complexity but provides a stable foundation for discovery,
governance, runtime observability, FinOps, and MCP relationships.

The ADR remains Proposed until the schema and migration design
are reviewed and accepted.
