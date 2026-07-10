# Copyright 2026. Licensed under the Apache License, Version 2.0.
"""FraudScorer coded tool.

Applies deterministic fraud red-flag rules over the claim, the policy, and the
coverage result. Each triggered flag contributes points; the total maps to a
band (Low / Medium / High). A High band recommends routing to the Special
Investigations Unit (SIU) before payment. Findings are written to
``sly_data['fraud']``. This is a screening aid, not an accusation — it flags
patterns for human review.
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from neuro_san.interfaces.coded_tool import CodedTool

_POLICY_PATH = os.path.join(os.path.dirname(__file__), "data", "policy.json")
# Thresholds (days)
_NEAR_INCEPTION_DAYS = 14
_NEAR_EXPIRY_DAYS = 14
_LATE_REPORT_DAYS = 30


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


def _band(score: int) -> str:
    if score >= 60:
        return "High"
    if score >= 30:
        return "Medium"
    if score >= 1:
        return "Low"
    return "None"


class FraudScorer(CodedTool):
    """Score the claim for fraud red flags and recommend SIU routing if warranted."""

    def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        claim = sly_data.get("claim")
        if not claim:
            return "Error: no claim found. Run the claim extractor first."
        policy = _load_policy()
        coverage = sly_data.get("coverage", {})

        loss_date = _parse_date(claim.get("loss_date", ""))
        report_date = _parse_date(claim.get("report_date", ""))
        window = policy.get("policyholder_in_force", {})
        start = _parse_date(window.get("start", ""))
        end = _parse_date(window.get("end", ""))
        amount_claimed = claim.get("amount_claimed")
        applicable_limit = coverage.get("applicable_limit")

        flags: List[Dict[str, Any]] = []
        score = 0

        report_days = coverage.get("report_days")
        if report_days is None and loss_date and report_date:
            report_days = (report_date - loss_date).days
        if report_days is not None and report_days > _LATE_REPORT_DAYS:
            flags.append({"code": "LATE-REPORT", "severity": "High",
                          "text": "Loss reported %d days after occurrence (> %d)." % (report_days, _LATE_REPORT_DAYS)})
            score += 30

        if loss_date and start and 0 <= (loss_date - start).days <= _NEAR_INCEPTION_DAYS:
            flags.append({"code": "NEAR-INCEPTION", "severity": "High",
                          "text": "Loss occurred within %d days of policy inception." % _NEAR_INCEPTION_DAYS})
            score += 40

        if loss_date and end and 0 <= (end - loss_date).days <= _NEAR_EXPIRY_DAYS:
            flags.append({"code": "NEAR-EXPIRY", "severity": "Medium",
                          "text": "Loss occurred within %d days of policy expiry." % _NEAR_EXPIRY_DAYS})
            score += 15

        if amount_claimed is not None and applicable_limit is not None and amount_claimed >= applicable_limit:
            flags.append({"code": "AT-OR-OVER-LIMIT", "severity": "Medium",
                          "text": "Amount claimed is at or above the applicable limit."})
            score += 15

        if amount_claimed is not None and amount_claimed >= 5000 and amount_claimed % 1000 == 0:
            flags.append({"code": "ROUND-AMOUNT", "severity": "Low",
                          "text": "Claimed amount is a large round number."})
            score += 10

        band = _band(score)
        recommendation = "Route to SIU before payment." if band == "High" else "No SIU referral indicated; standard processing."

        fraud = {
            "fraud_score": score,
            "band": band,
            "flags": flags,
            "recommendation": recommendation,
        }
        sly_data["fraud"] = fraud
        return fraud

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        return self.invoke(args, sly_data)
