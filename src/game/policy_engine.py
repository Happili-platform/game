# SPDX-License-Identifier: AGPL-3.0-only
"""Versioned deterministic advisory policy definitions and evaluations.

No AI model is used to determine risk. All rules operate on known inventory fields.
Unknown provider information is not treated as proof of safe behavior or zero spend.
"""
from __future__ import annotations

from datetime import datetime, timezone

DEFAULT_RULES = (
    dict(code='MISSING_OWNER', category='Ownership', title='Accountable owner is missing',
         description='An active or unclassified agent has neither an assigned Business Owner nor a recorded technical owner.',
         severity='high', remediation='Assign an accountable Business Owner and confirm the technical owner.'),
    dict(code='BUSINESS_OWNER_NOT_ASSIGNED', category='Ownership', title='Business Owner has not been assigned',
         description='An agent with a recorded technical owner still has no accountable Business Owner for business authorization.',
         severity='medium', remediation='Assign an active Business Owner who can authorize business use and budget.'),
    dict(code='BUSINESS_OWNER_INACTIVE', category='Ownership', title='Business Owner is inactive',
         description='The assigned Business Owner no longer has an active GAME account.',
         severity='high', remediation='Reassign the accountable Business Owner to an active user.'),
    dict(code='PRODUCTION_NOT_APPROVED', category='Business approval', title='Production use lacks approval',
         description='An agent classified as production has not been approved by its assigned Business Owner.',
         severity='high', remediation='Submit business justification, monthly budget and cost center for Business Owner decision.'),
    dict(code='SENSITIVE_ACCESS_UNAPPROVED', category='Data governance', title='Sensitive access requires review',
         description='Declared sensitive access exists without Business Owner approval; this is not proof of an actual data exposure.',
         severity='high', remediation='Review sensitive access and obtain the required governance approvals.'),
    dict(code='OVER_BUDGET', category='FinOps', title='Recorded spending exceeds budget',
         description='Locally recorded monthly usage exceeds the approved or configured monthly budget.',
         severity='medium', remediation='Review recorded usage and request a revised budget from the Business Owner.'),
    dict(code='STALE_AGENT', category='Lifecycle', title='No recorded recent activity',
         description='A manually registered active agent has no recorded activity within the configured number of days.',
         severity='medium', remediation='Confirm whether the agent is still in use and whether activity telemetry is available.'),
    dict(code='UNKNOWN_ENVIRONMENT', category='Inventory quality', title='Environment classification is unknown',
         description='A discovered agent does not have a verified development, staging, or production classification.',
         severity='medium', remediation='Classify the agent environment through an authoritative provider mapping or approved inventory record.'),
    dict(code='REPORTED_AFFECTED_CVE', category='Security vulnerabilities',
         title='Component reported affected by linked CVE',
         description='An authorized user reported that a specific component version is affected and recorded supporting evidence. The report has not been independently verified against a vulnerability scanner or NVD.',
         severity='high', remediation='Have the technical owner verify affected versions, reachability, compensating controls and remediation priorities.'),
    dict(code='MISSING_COST_CENTER', category='FinOps', title='Approved production agent lacks cost center',
         description='An approved production agent has no cost center recorded in GAME.',
         severity='medium', remediation='Record and validate the Business Owner-approved cost center.'),
)

RULES_BY_CODE = {rule['code']: rule for rule in DEFAULT_RULES}
VALID_SEVERITIES = ('high', 'medium', 'low')


def rule_configs(rows: list[dict] | None = None) -> list[dict]:
    """Merge saved configuration with trusted built-in definitions (never execute user scripts)."""
    overrides = {r['code']: r for r in (rows or [])}
    results = []
    for definition in DEFAULT_RULES:
        custom = overrides.get(definition['code'], {})
        results.append({**definition, 'enabled': bool(custom.get('enabled', 1)),
                        'severity': custom.get('severity', definition['severity']),
                        'stale_after_days': int(custom.get('stale_after_days', 30)),
                        'version': int(custom.get('version', 1)),
                        'updated_at': custom.get('updated_at'), 'updated_by': custom.get('updated_by')})
    return results


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def evaluate_agent(agent: dict, spend_usd: float, rules: list[dict] | None = None,
                   now: datetime | None = None) -> list[dict]:
    """Return evidence-backed advisory findings, never an enforcement decision."""
    now = now or datetime.now(timezone.utc)
    if agent.get('lifecycle_status') == 'retired':
        return []
    results = []
    for rule in rules if rules is not None else rule_configs():
        if not rule['enabled']:
            continue
        code = rule['code']
        evidence = None
        if code == 'MISSING_OWNER':
            if not (agent.get('business_owner_user_id') or agent.get('owner_email')):
                evidence = {'business_owner_assigned': False, 'technical_owner_recorded': False}
        elif code == 'BUSINESS_OWNER_NOT_ASSIGNED':
            if agent.get('owner_email') and not agent.get('business_owner_user_id'):
                evidence = {'technical_owner_recorded': True, 'business_owner_assigned': False}
        elif code == 'BUSINESS_OWNER_INACTIVE':
            if agent.get('business_owner_user_id') and agent.get('business_owner_active') is False:
                evidence = {'business_owner_active': False}
        elif code == 'PRODUCTION_NOT_APPROVED':
            if agent.get('environment') == 'production' and agent.get('approval_status') != 'approved':
                evidence = {'environment': 'production', 'business_approval': agent.get('approval_status') or 'unknown'}
        elif code == 'SENSITIVE_ACCESS_UNAPPROVED':
            if agent.get('sensitive_access') and agent.get('approval_status') != 'approved':
                evidence = {'sensitive_access_declared': True, 'business_approval': agent.get('approval_status') or 'unknown'}
        elif code == 'OVER_BUDGET':
            # Provider agent metadata does not contain invoice-reconciled spending.
            if agent.get('source') != 'discovered':
                approved_budget = agent.get('approved_budget_usd') if agent.get('approval_status') == 'approved' else None
                budget = float(approved_budget if approved_budget is not None else agent.get('budget_usd') or 0)
                if budget > 0 and spend_usd > budget:
                    evidence = {'recorded_spend_usd': round(spend_usd, 2), 'budget_usd': round(budget, 2),
                                'cost_source': 'manually_recorded_usage'}
        elif code == 'STALE_AGENT':
            if agent.get('source') != 'discovered' and agent.get('lifecycle_status') == 'active':
                last = _parse_utc(agent.get('last_seen'))
                days = int(rule['stale_after_days'])
                if last is None or (now - last).total_seconds() >= days * 86400:
                    evidence = {'last_activity_at': agent.get('last_seen'), 'threshold_days': days,
                                'activity_source': 'locally_recorded_activity'}
        elif code == 'UNKNOWN_ENVIRONMENT':
            if agent.get('environment') not in ('development', 'staging', 'production'):
                evidence = {'provider_environment': agent.get('environment') or 'unknown'}
        elif code == 'REPORTED_AFFECTED_CVE':
            cves = agent.get('confirmed_affected_cves') or []
            if cves:
                evidence = {'confirmed_cves': sorted(set(cves)),
                            'assessment_source': 'GAME component evidence',
                            'affected_status': 'reported_affected_by_authorized_user'}
        elif code == 'MISSING_COST_CENTER':
            if (agent.get('environment') == 'production' and agent.get('approval_status') == 'approved'
                    and not (agent.get('approval_requested_cost_center') or agent.get('cost_center'))):
                evidence = {'environment': 'production', 'business_approval': 'approved', 'cost_center_recorded': False}
        if evidence is not None:
            results.append({'code': code, 'severity': rule['severity'], 'title': rule['title'],
                            'category': rule['category'], 'message': rule['description'],
                            'remediation': rule['remediation'], 'evidence': evidence,
                            'policy_version': rule['version'], 'advisory_only': True})
    return results
