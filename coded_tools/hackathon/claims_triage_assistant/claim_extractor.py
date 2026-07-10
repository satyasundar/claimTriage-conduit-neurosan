# Copyright 2026. Licensed under the Apache License, Version 2.0.
"""ClaimExtractor coded tool.

Parses a First Notice of Loss (FNOL) into structured claim facts and redacts
personally identifying and financial-account data (claimant name, policy
number, address, phone, email, payout/bank account) out of the text the LLM
agents see. The structured claim and the sensitive values are written to
``sly_data`` so they stay off the LLM chat stream and are available to the
deterministic coded tools. Loss amounts and dates are kept visible because
they are needed for an explainable coverage decision and are not identifying.
"""

import re
from typing import Any, Dict, List, Union

from neuro_san.interfaces.coded_tool import CodedTool

# Each field: canonical name -> list of accepted labels in the FNOL form.
_FIELD_LABELS = {
    "policy_number": ["policy number", "policy no", "policy #"],
    "policy_type": ["policy type", "product"],
    "claimant": ["claimant", "insured", "policyholder"],
    "address": ["address"],
    "phone": ["phone", "telephone"],
    "email": ["email", "e-mail"],
    "bank": ["payout account (iban)", "payout account", "iban", "bank account", "account number"],
    "loss_date": ["date of loss", "loss date"],
    "report_date": ["date reported", "reported", "report date"],
    "peril": ["peril", "cause of loss", "cause"],
    "amount_claimed": ["amount claimed", "claim amount", "amount"],
    "location": ["location of loss", "location"],
    "description": ["description", "details"],
}
# Fields that are sensitive PII / financial-account data and must be redacted.
_PII_FIELDS = ["claimant", "policy_number", "address", "phone", "email", "bank", "location"]
_PII_TOKEN = {
    "claimant": "[CLAIMANT]", "policy_number": "[POLICY_NO]", "address": "[ADDRESS]",
    "phone": "[PHONE]", "email": "[EMAIL]", "bank": "[BANK_ACCOUNT]", "location": "[LOCATION]",
}
_MONEY_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{1,2})?)")


def _find_field(label_list: List[str], text: str) -> str:
    for label in label_list:
        pattern = re.compile(r"(?im)^\s*" + re.escape(label) + r"\s*[:\-]\s*(.+?)\s*$")
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return ""


def _parse_amount(raw: str):
    match = _MONEY_RE.search(raw)
    if match:
        return float(match.group(1).replace(",", ""))
    digits = re.sub(r"[^\d.]", "", raw)
    return float(digits) if digits else None


class ClaimExtractor(CodedTool):
    """Extract structured claim facts and redact PII into sly_data."""

    def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        claim_text = sly_data.get("claim_text") or args.get("claim_text", "")
        if not claim_text or not claim_text.strip():
            return "Error: no claim text supplied. Pass it via sly_data['claim_text'] or args['claim_text']."

        raw_fields: Dict[str, str] = {}
        for field, labels in _FIELD_LABELS.items():
            raw_fields[field] = _find_field(labels, claim_text)

        # Build the sensitive map and a redacted, LLM-safe display text.
        sensitive: Dict[str, str] = {}
        redacted_text = claim_text
        for field in _PII_FIELDS:
            value = raw_fields.get(field, "")
            if value:
                sensitive[field] = value
                redacted_text = redacted_text.replace(value, _PII_TOKEN[field])

        amount_claimed = _parse_amount(raw_fields.get("amount_claimed", ""))

        # Structured claim for the deterministic tools (no PII except non-identifying facts).
        claim = {
            "policy_type": raw_fields.get("policy_type", ""),
            "peril": raw_fields.get("peril", ""),
            "loss_date": raw_fields.get("loss_date", ""),
            "report_date": raw_fields.get("report_date", ""),
            "amount_claimed": amount_claimed,
            "description": raw_fields.get("description", ""),
        }
        sly_data["claim"] = claim
        sly_data["sensitive"] = sensitive

        return {
            "claim": claim,
            "redaction_summary": {
                "pii_fields_redacted": sorted(sensitive.keys()),
                "count": len(sensitive),
            },
            "redacted_fnol": redacted_text,
        }

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        return self.invoke(args, sly_data)
