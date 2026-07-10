# Copyright 2026. Licensed under the Apache License, Version 2.0.
"""AdjudicationScorer coded tool.

Powers the evaluation loop and the approval gate. It checks the drafted
disposition against the deterministic coverage and fraud results on the
bulletin board: is there a clear recommendation, is it grounded in a cited
coverage or exclusion code, does the stated payable match the computed payable,
are the limit and deductible disclosed for a payment, and does the draft route
to SIU when the fraud band is High? It returns a completeness score and the
list of gaps so the front-man can decide whether to revise the disposition.
"""

import re
from typing import Any, Dict, List, Union

from neuro_san.interfaces.coded_tool import CodedTool

_DECISIONS = ["PAY", "DENY", "INVESTIGATE"]
_DEFAULT_THRESHOLD = 80


def _amount_in_text(amount: float, text: str) -> bool:
    """True if the (integer) amount appears in the text with or without thousands commas."""
    n = int(round(amount))
    candidates = {str(n), "{:,}".format(n)}
    return any(c in text for c in candidates)


class AdjudicationScorer(CodedTool):
    """Score the drafted disposition for completeness and grounding."""

    def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        draft = args.get("draft") or ""
        if not draft.strip():
            return "Error: pass the drafted disposition as args['draft']."
        coverage = sly_data.get("coverage")
        if not coverage:
            return "Error: no coverage result found. Run the coverage evaluator first."
        fraud = sly_data.get("fraud", {})

        upper = draft.upper()
        lower = draft.lower()
        checks: List[Dict[str, Any]] = []

        def add(name, passed, detail):
            checks.append({"check": name, "passed": bool(passed), "detail": detail})

        # 1. A clear recommendation is present.
        decision_present = any(d in upper for d in _DECISIONS)
        add("recommendation_present", decision_present, "One of PAY/DENY/INVESTIGATE must be stated.")

        # 2. Grounding: the draft cites the governing coverage or a triggered exclusion code.
        codes = []
        if coverage.get("matched_coverage"):
            codes.append(coverage["matched_coverage"])
        codes.extend(coverage.get("exclusions_triggered", []))
        for r in coverage.get("reasons", []):
            codes.append(r.get("code", ""))
        grounded = any(code and code in draft for code in codes)
        add("coverage_grounded", grounded, "Cite the governing coverage or exclusion code (e.g. WATER, EXCL-FLOOD).")

        # 3. For a payable decision, the stated payable must match the computed payable.
        if coverage.get("decision") == "PAY" and coverage.get("payable") is not None:
            add("payable_consistent", _amount_in_text(coverage["payable"], draft),
                "Stated payable must equal the computed payable (%s)." % coverage["payable"])
            add("limit_and_deductible_disclosed",
                _amount_in_text(coverage.get("applicable_limit") or 0, draft) and _amount_in_text(coverage.get("deductible") or 0, draft),
                "Disclose the applied limit and deductible.")

        # 4. If fraud risk is High, the disposition must route to SIU / investigate.
        if fraud.get("band") == "High":
            add("fraud_routed", ("INVESTIGATE" in upper) or ("siu" in lower),
                "High fraud band requires INVESTIGATE / SIU referral.")

        passed_count = sum(1 for c in checks if c["passed"])
        score = round(100 * passed_count / len(checks)) if checks else 100
        threshold = int(args.get("threshold", _DEFAULT_THRESHOLD))
        gaps = [c for c in checks if not c["passed"]]

        return {
            "completeness_score": score,
            "passed": score >= threshold,
            "threshold": threshold,
            "checks": checks,
            "gaps": gaps,
        }

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        return self.invoke(args, sly_data)
