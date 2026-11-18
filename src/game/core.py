# SPDX-License-Identifier: AGPL-3.0-only
"""Framework-independent reporting and advisory risk rules."""
from __future__ import annotations

from .policy_engine import evaluate_agent


def findings(agent: dict, monthly_spend: float, now=None, rules=None) -> list[dict]:
    return evaluate_agent(agent, monthly_spend, rules=rules, now=now)


def enrich_agent(agent: dict, monthly_spend: float, rules=None) -> dict:
    item = dict(agent)
    item["sensitive_access"] = bool(item["sensitive_access"])
    item["monthly_spend_usd"] = round(monthly_spend, 2)
    item["spend_observed"] = item.get("source") != "discovered"
    item["findings"] = findings(item, monthly_spend, rules=rules)
    severities = {f["severity"] for f in item["findings"]}
    item["risk_level"] = next((s for s in ("high", "medium", "low") if s in severities), "clear")
    item["policy_assessment"] = "advisory"
    item["coverage_notes"] = (["No provider usage/cost telemetry available; zero spend is not confirmed",
                               "Discovery timestamp is not agent activity evidence"]
                              if not item["spend_observed"] else [])
    return item
