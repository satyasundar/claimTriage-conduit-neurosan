# Copyright 2026. Licensed under the Apache License, Version 2.0.
"""Deterministic tests for the claims triage coded tools.

These run fully offline (no LLM, no network) and prove the grounding layer:
FNOL extraction + PII redaction, policy-grounded coverage adjudication and the
payable math, deterministic fraud scoring, and the completeness check that
powers the evaluation loop. The three claim dispositions (PAY, DENY,
INVESTIGATE) are all exercised. Run with `pytest tests/` or
`python tests/test_claims_triage.py`.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from coded_tools.hackathon.claims_triage_assistant.claim_extractor import ClaimExtractor
from coded_tools.hackathon.claims_triage_assistant.coverage_evaluator import CoverageEvaluator
from coded_tools.hackathon.claims_triage_assistant.fraud_scorer import FraudScorer
from coded_tools.hackathon.claims_triage_assistant.adjudication_scorer import AdjudicationScorer

_SAMPLE = os.path.join(
    os.path.dirname(__file__), "..", "coded_tools", "hackathon","claims_triage_assistant", "data", "sample_claim.txt"
)


def _load_claim_into_sly_data():
    with open(_SAMPLE, "r", encoding="utf-8") as handle:
        return {"claim_text": handle.read()}


def test_extraction_and_pii_redaction():
    sly = _load_claim_into_sly_data()
    result = ClaimExtractor().invoke({}, sly)
    claim = sly["claim"]
    assert claim["amount_claimed"] == 48000.0, claim["amount_claimed"]
    assert "water damage" in claim["peril"].lower(), claim["peril"]
    # PII / bank details must be captured privately and not appear in the redacted text.
    for field in ("claimant", "policy_number", "email", "bank"):
        assert field in sly["sensitive"], sly["sensitive"].keys()
    red = result["redacted_fnol"]
    assert "Maria Whitfield" not in red
    assert "GB29 NWBK 6016 1331 9268 19" not in red
    assert "[CLAIMANT]" in red and "[BANK_ACCOUNT]" in red


def test_coverage_pay_with_sub_limit_and_deductible():
    sly = _load_claim_into_sly_data()
    ClaimExtractor().invoke({}, sly)
    cov = CoverageEvaluator().invoke({}, sly)
    assert cov["in_force"] is True, cov
    assert cov["decision"] == "PAY", cov
    assert cov["matched_coverage"] == "WATER", cov
    assert cov["applicable_limit"] == 40000, cov
    assert cov["deductible"] == 1000, cov
    # min(48000, 40000) - 1000 = 39000
    assert cov["payable"] == 39000.0, cov["payable"]
    assert "SUB-LIMIT" in [r["code"] for r in cov["reasons"]], cov["reasons"]


def test_fraud_low_band_on_sample():
    sly = _load_claim_into_sly_data()
    ClaimExtractor().invoke({}, sly)
    CoverageEvaluator().invoke({}, sly)
    fraud = FraudScorer().invoke({}, sly)
    # at-or-over-limit (15) + round-amount (10) = 25 -> Low band, no SIU.
    assert fraud["band"] == "Low", fraud
    codes = [f["code"] for f in fraud["flags"]]
    assert "AT-OR-OVER-LIMIT" in codes and "ROUND-AMOUNT" in codes, codes
    assert "Route to SIU" not in fraud["recommendation"], fraud


def test_coverage_deny_on_flood_exclusion():
    sly = _load_claim_into_sly_data()
    ClaimExtractor().invoke({}, sly)
    # Mutate the claim to a flood loss; the flood exclusion must trigger a DENY.
    sly["claim"] = copy.deepcopy(sly["claim"])
    sly["claim"]["peril"] = "Flood"
    sly["claim"]["description"] = "Rising flood water from the nearby river entered the property."
    cov = CoverageEvaluator().invoke({}, sly)
    assert cov["decision"] == "DENY", cov
    assert "EXCL-FLOOD" in cov["exclusions_triggered"], cov


def test_investigate_path_high_fraud():
    sly = _load_claim_into_sly_data()
    ClaimExtractor().invoke({}, sly)
    # Loss 5 days after inception + reported 45 days later -> near-inception (40) + late (30) = High.
    sly["claim"] = copy.deepcopy(sly["claim"])
    sly["claim"]["loss_date"] = "2025-09-05"
    sly["claim"]["report_date"] = "2025-10-25"
    CoverageEvaluator().invoke({}, sly)
    fraud = FraudScorer().invoke({}, sly)
    assert fraud["band"] == "High", fraud
    assert "SIU" in fraud["recommendation"], fraud


def test_adjudication_scorer_passes_complete_draft():
    sly = _load_claim_into_sly_data()
    ClaimExtractor().invoke({}, sly)
    CoverageEvaluator().invoke({}, sly)
    FraudScorer().invoke({}, sly)
    draft = (
        "DRAFT DISPOSITION. Recommendation: PAY. "
        "Covered under WATER; the loss is sudden and accidental water damage. "
        "Applicable limit 40,000 and deductible 1,000 applied. "
        "Amount claimed exceeds the sub-limit (SUB-LIMIT), so payment is capped. "
        "Payable: $39,000. Fraud band Low; no SIU referral."
    )
    out = AdjudicationScorer().invoke({"draft": draft}, sly)
    assert out["passed"] is True, out
    assert out["completeness_score"] == 100, out


def test_adjudication_scorer_fails_ungrounded_draft():
    sly = _load_claim_into_sly_data()
    ClaimExtractor().invoke({}, sly)
    CoverageEvaluator().invoke({}, sly)
    FraudScorer().invoke({}, sly)
    # No citation, wrong payable, no limit/deductible.
    draft = "We think we should probably pay something around $50,000 for this claim."
    out = AdjudicationScorer().invoke({"draft": draft}, sly)
    assert out["passed"] is False, out
    assert out["completeness_score"] < 80, out


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for test in tests:
        test()
        print("PASS  %s" % test.__name__)
        passed += 1
    print("\n%d/%d tests passed." % (passed, len(tests)))


if __name__ == "__main__":
    _run_all()
