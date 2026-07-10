# Copyright 2026. Licensed under the Apache License, Version 2.0.
"""CoverageEvaluator coded tool.

Deterministically adjudicates a claim against the policy. It checks whether the
policy was in force on the date of loss, whether the peril is covered (applying
the most restrictive matching sub-limit), whether any exclusion is triggered,
and the prompt-notice condition; then it computes the payable amount as
``min(amount_claimed, limit) - deductible`` (floored at zero). The result is
written to ``sly_data['coverage']`` so the fraud and critic tools can build on
it. No coverage figure is produced by the LLM — only by this tool.
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from neuro_san.interfaces.coded_tool import CodedTool

_POLICY_PATH = os.path.join(os.path.dirname(__file__), "data", "policy.json")


def _load_policy() -> Dict[str, Any]:
    with open(_POLICY_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _parse_date(value: str) -> Optional[datetime]:
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _matching_coverages(peril: str, policy: Dict[str, Any]) -> List[Dict[str, Any]]:
    peril_l = peril.lower()
    matches = []
    for cov in policy.get("coverages", []):
        for p in cov.get("perils", []):
            if p.lower() in peril_l or peril_l in p.lower():
                matches.append(cov)
                break
    return matches


def _triggered_exclusions(peril: str, description: str, policy: Dict[str, Any]) -> List[Dict[str, str]]:
    peril_l = peril.lower()
    text_l = (peril + " " + description).lower()
    triggered = []
    for exc in policy.get("exclusions", []):
        hit = False
        for check in exc.get("checks", []):
            if check["kind"] == "peril_in":
                if any(p.lower() in peril_l for p in check.get("perils", [])):
                    hit = True
            elif check["kind"] == "text_contains":
                if any(term.lower() in text_l for term in check.get("terms", [])):
                    hit = True
            if hit:
                break
        if hit:
            triggered.append({"code": exc["code"], "description": exc["description"]})
    return triggered


class CoverageEvaluator(CodedTool):
    """Adjudicate coverage for the claim on the bulletin board and compute payable."""

    def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        claim = sly_data.get("claim")
        if not claim:
            return "Error: no claim found. Run the claim extractor first."
        policy = _load_policy()

        peril = claim.get("peril", "")
        description = claim.get("description", "")
        amount_claimed = claim.get("amount_claimed")

        loss_date = _parse_date(claim.get("loss_date", ""))
        report_date = _parse_date(claim.get("report_date", ""))
        in_force_window = policy.get("policyholder_in_force", {})
        start = _parse_date(in_force_window.get("start", ""))
        end = _parse_date(in_force_window.get("end", ""))
        in_force = bool(loss_date and start and end and start <= loss_date <= end)

        report_days = (report_date - loss_date).days if (loss_date and report_date) else None
        notice = next((c for c in policy.get("conditions", []) if c["code"] == "COND-NOTICE"), None)
        max_report_days = notice.get("max_report_days") if notice else None
        late_notice = bool(report_days is not None and max_report_days is not None and report_days > max_report_days)

        matches = _matching_coverages(peril, policy)
        # The most restrictive (lowest-limit) matching coverage governs the sub-limit.
        matched = min(matches, key=lambda c: c.get("limit", float("inf"))) if matches else None
        exclusions = _triggered_exclusions(peril, description, policy)

        reasons: List[Dict[str, str]] = []
        decision = "PAY"
        payable = None
        applicable_limit = matched.get("limit") if matched else None
        deductible = matched.get("deductible", policy.get("standard_deductible")) if matched else policy.get("standard_deductible")

        if not in_force:
            decision = "DENY"
            reasons.append({"code": "NOT-IN-FORCE", "text": "The policy was not in force on the date of loss."})
        elif matched is None:
            decision = "DENY"
            reasons.append({"code": "PERIL-NOT-COVERED", "text": "The reported peril is not covered by any policy coverage."})
        elif exclusions:
            decision = "DENY"
            for exc in exclusions:
                reasons.append({"code": exc["code"], "text": "Excluded: %s" % exc["description"]})
        else:
            covered_amount = amount_claimed if amount_claimed is not None else 0.0
            capped = min(covered_amount, applicable_limit) if applicable_limit is not None else covered_amount
            payable = max(0.0, capped - (deductible or 0))
            reasons.append({"code": matched["code"],
                            "text": "Covered under %s (%s); limit %s, deductible %s."
                                    % (matched["code"], matched["name"], applicable_limit, deductible)})
            if amount_claimed is not None and applicable_limit is not None and amount_claimed > applicable_limit:
                reasons.append({"code": "SUB-LIMIT",
                                "text": "Amount claimed exceeds the applicable limit; payment is capped at the limit."})

        if late_notice:
            reasons.append({"code": "COND-NOTICE",
                            "text": "Loss reported %d days after the date of loss, exceeding the %d-day notice condition."
                                    % (report_days, max_report_days)})

        coverage = {
            "decision": decision,
            "in_force": in_force,
            "matched_coverage": matched["code"] if matched else None,
            "applicable_limit": applicable_limit,
            "deductible": deductible,
            "amount_claimed": amount_claimed,
            "payable": payable,
            "exclusions_triggered": [e["code"] for e in exclusions],
            "report_days": report_days,
            "late_notice": late_notice,
            "reasons": reasons,
        }
        sly_data["coverage"] = coverage
        return coverage

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        return self.invoke(args, sly_data)
