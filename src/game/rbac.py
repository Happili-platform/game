# SPDX-License-Identifier: AGPL-3.0-only
"""Single-company role inheritance and capability closure.

Roles are fixed presets. User assignments store the selected role, never a client-provided
set of effective capabilities. Permission checks always run on the server.
"""
from __future__ import annotations

# Role inheritance is a DAG, not a single linear power ranking.
ROLES = {
    'viewer': {'label': 'Viewer', 'includes': [], 'grants': ['overview.view', 'agents.view', 'connections.view', 'governance.view']},
    'agent_owner': {'label': 'User / Agent Owner', 'includes': ['viewer'], 'grants': ['agents.register', 'agents.submit', 'usage.record', 'governance.remediate', 'runtime.view', 'finops.usage.view', 'finops.estimates.view']},
    'business_owner': {'label': 'Business Owner', 'includes': ['viewer'], 'grants': ['agents.approve', 'runtime.view', 'finops.usage.view', 'finops.estimates.view']},
    'provider_admin': {'label': 'Provider Admin', 'includes': ['agent_owner'], 'grants': ['connections.manage', 'connections.discover', 'connections.credentials', 'agents.owner.assign']},
    'auditor': {'label': 'Auditor', 'includes': ['viewer'], 'grants': ['audit.view', 'runtime.view', 'finops.usage.view', 'finops.estimates.view', 'finops.billing.view']},
    'admin': {'label': 'Admin', 'includes': ['provider_admin', 'auditor'], 'grants': ['members.manage', 'governance.manage', 'governance.evaluate', 'finops.rates.manage']},
}
CAPABILITIES = {
    'overview.view': {'label': 'View dashboard', 'implies': []},
    'agents.view': {'label': 'View agent inventory', 'implies': []},
    'agents.register': {'label': 'Register agents', 'implies': ['agents.view']},
    'usage.record': {'label': 'Record agent usage', 'implies': ['agents.view']},
    'connections.view': {'label': 'View provider connections', 'implies': []},
    'connections.discover': {'label': 'Discover agents', 'implies': ['connections.view', 'agents.view']},
    'connections.manage': {'label': 'Manage provider connections', 'implies': ['connections.discover', 'connections.view']},
    'agents.submit': {'label': 'Submit agent for business approval', 'implies': ['agents.view']},
    'agents.owner.assign': {'label': 'Assign accountable Business Owner', 'implies': ['agents.view']},
    'agents.approve': {'label': 'Approve/reject assigned agent business requests', 'implies': ['agents.view']},
    'connections.credentials': {'label': 'Replace/clear connection credentials', 'implies': ['connections.view']},
    'governance.view': {'label': 'View governance findings', 'implies': ['agents.view']},
    'governance.manage': {'label': 'Configure advisory policy rules', 'implies': ['governance.view']},
    'governance.remediate': {'label': 'Document remediation without suppressing a finding', 'implies': ['governance.view']},
    'governance.evaluate': {'label': 'Record a policy evaluation snapshot', 'implies': ['governance.view']},
    'costs.view': {'label': 'Legacy cost information (deprecated)', 'implies': ['overview.view']},
    'finops.usage.view': {'label': 'View scoped token and model usage', 'implies': ['agents.view']},
    'finops.estimates.view': {'label': 'View scoped estimated costs and budgets', 'implies': ['finops.usage.view']},
    'finops.billing.view': {'label': 'View company-wide Azure resource charges', 'implies': ['finops.estimates.view']},
    'finops.rates.manage': {'label': 'Configure documented FinOps estimate rates', 'implies': ['finops.estimates.view']},
    'runtime.view': {'label': 'View scoped runtime execution metadata', 'implies': ['agents.view']},
    'audit.view': {'label': 'View audit history', 'implies': []},
    'members.view': {'label': 'View company users', 'implies': []},
    'members.manage': {'label': 'Assign and revoke company roles', 'implies': ['members.view']},
}
# Backward compatibility with v0.3.0 OIDC memberships; old fixtures and migrated users keep working.
ALIASES = {'tenant_admin': 'admin', 'connection_admin': 'provider_admin', 'analyst': 'agent_owner'}


def normalized_role(role: str) -> str:
    return ALIASES.get(role, role)


def inherited_roles(role: str) -> frozenset[str]:
    effective: set[str] = set()
    def visit(name: str) -> None:
        if name not in ROLES or name in effective:
            return
        effective.add(name)
        for lower in ROLES[name]['includes']:
            visit(lower)
    visit(normalized_role(role))
    return frozenset(effective)


def effective_capabilities(role: str) -> frozenset[str]:
    caps: set[str] = set()
    def add(cap: str) -> None:
        if cap in caps: return
        caps.add(cap)
        for lower in CAPABILITIES[cap]['implies']:
            add(lower)
    for inherited in inherited_roles(role):
        for cap in ROLES[inherited]['grants']:
            add(cap)
    return frozenset(caps)


def allowed(role: str, capability: str) -> bool:
    return capability in effective_capabilities(role)


def catalog() -> dict:
    return {'roles': [{'id': name, 'label': data['label'], 'includes': data['includes'],
                       'effective_roles': sorted(inherited_roles(name)),
                       'capabilities': sorted(effective_capabilities(name))} for name, data in ROLES.items()],
            'capabilities': [{'id': name, 'label': value['label'], 'implies': value['implies']}
                             for name, value in CAPABILITIES.items()]}


def validate_selection(role: str, selected: list[str]) -> frozenset[str]:
    """Validate explicit user permissions against role ceiling and dependency closure.

    A custom selection can only REMOVE preset permissions; changing the primary
    role is the only way to grant higher permission. This prevents privilege
    escalation and preserves Business Owner approval separation.
    """
    if not isinstance(selected, list) or len(selected)>len(CAPABILITIES) or any(not isinstance(x,str) for x in selected):
        raise ValueError('Invalid capability selection')
    chosen=set(selected)
    ceiling=set(effective_capabilities(role))
    if not chosen.issubset(ceiling):
        raise ValueError('Selected permissions exceed the primary role')
    for cap in chosen:
        if not set(_implied_closure(cap)).issubset(chosen):
            raise ValueError('Selected permissions are missing prerequisite permissions')
    if normalized_role(role)=='admin' and 'members.manage' not in chosen:
        raise ValueError('Admin must retain user administration access')
    return frozenset(chosen)

def _implied_closure(name: str) -> frozenset[str]:
    found=set()
    def visit(cap):
        if cap in found: return
        found.add(cap)
        for lower in CAPABILITIES[cap]['implies']:visit(lower)
    visit(name)
    return frozenset(found)
