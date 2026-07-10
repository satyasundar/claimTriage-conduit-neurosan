# Copyright 2026. Licensed under the Apache License, Version 2.0.
"""PolicyRetriever coded tool.

Grounds the agents in the policy wording. Given a peril or free-text query, it
returns the relevant policy provisions — matching coverages (with limits and
deductibles), potentially relevant exclusions, and conditions. This is the
retrieval / grounding step; it is deterministic and offline, with no external
API dependency.
"""

import json
import os
import re
from typing import Any, Dict, List, Union

from neuro_san.interfaces.coded_tool import CodedTool

_POLICY_PATH = os.path.join(os.path.dirname(__file__), "data", "policy.json")


def _load_policy() -> Dict[str, Any]:
    with open(_POLICY_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class PolicyRetriever(CodedTool):
    """Retrieve coverages, exclusions, and conditions relevant to a peril/query."""

    def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        policy = _load_policy()
        peril = (args.get("peril") or "").strip().lower()
        query = (args.get("query") or "").strip().lower()
        haystack = (peril + " " + query).strip()
        q_tokens = set(_tokenize(haystack)) if haystack else set()

        coverages = []
        for cov in policy.get("coverages", []):
            cov_perils = [p.lower() for p in cov.get("perils", [])]
            matched = False
            if haystack:
                for p in cov_perils:
                    if p in haystack or haystack in p:
                        matched = True
                        break
                if not matched and q_tokens & set(_tokenize(" ".join(cov_perils) + " " + cov["name"])):
                    matched = True
            if matched or not haystack:
                coverages.append({
                    "code": cov["code"], "name": cov["name"], "perils": cov.get("perils", []),
                    "limit": cov.get("limit"), "deductible": cov.get("deductible", policy.get("standard_deductible")),
                })

        exclusions = [{"code": e["code"], "description": e["description"]} for e in policy.get("exclusions", [])]
        conditions = [{"code": c["code"], "description": c["description"]} for c in policy.get("conditions", [])]

        return {
            "policy_id": policy.get("policy_id"),
            "in_force": policy.get("policyholder_in_force"),
            "matching_coverages": coverages,
            "exclusions": exclusions,
            "conditions": conditions,
        }

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        return self.invoke(args, sly_data)
