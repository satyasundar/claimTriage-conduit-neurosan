# Architecture — Claims Triage Assistant

## Overview

The Claims Triage Assistant is a Neuro SAN agent network that turns a First Notice of
Loss into a governed, policy-grounded recommended disposition (pay / deny / investigate).
It combines LLM agents (for language understanding and explanation) with deterministic
Python coded tools (for parsing, policy retrieval, coverage math, fraud scoring, and
the quality gate), and it places a human adjuster approval gate at the end.

The design follows three principles:

1. **Ground every coverage conclusion in the policy, and compute money in code.**
   Whether a loss is covered is decided against the policy wording (in-force dates,
   covered perils, exclusions), and the payable amount is computed by a deterministic
   tool — never produced by the LLM. Every conclusion cites a coverage or exclusion code.
2. **Protect the claimant's data.** The claim and its PII / bank details travel through
   `sly_data`; the LLM sees only redacted text. Sensitive identifiers never enter a prompt.
3. **Screen, don't accuse — and never auto-decide.** Fraud red-flags are deterministic
   indicators for human review; a High band forces an INVESTIGATE / SIU referral. The
   disposition is finalised only after a human adjuster approves.

## Components

### Front-man — `ClaimsAdjudicator`
The entry point and orchestrator. Using AAOSA, it decides which specialist handles
each step, assembles the disposition, runs the evaluation loop, and owns the adjuster
approval gate. It is the only agent that talks to the user.

### Specialist agents
- **ClaimIntakeAnalyst** — calls `ClaimExtractor` and reports the claim facts and the
  redaction summary.
- **CoverageOfficer** — calls `PolicyRetriever` (for the wording) and `CoverageEvaluator`
  (for the deterministic decision and payable), and reports the cited basis.
- **FraudScreener** — calls `FraudScorer` and reports the fraud band, the flags, and
  whether an SIU referral is recommended.
- **AdjudicationCritic** — calls `AdjudicationScorer` to verify the draft is complete,
  grounded, and arithmetically correct; this drives the loop.

### Coded tools (the grounding layer)
- **ClaimExtractor** — parses the FNOL into structured facts, redacts PII / bank
  details, and writes the claim and the sensitive map to `sly_data`.
- **PolicyRetriever** — loads the policy and returns the provisions relevant to the
  peril (matching coverages with limits/deductibles, exclusions, conditions).
- **CoverageEvaluator** — checks in-force status, matches the peril to the most
  restrictive sub-limit, evaluates exclusions, applies the notice condition, and
  computes `payable = max(0, min(amount_claimed, limit) - deductible)`.
- **FraudScorer** — applies deterministic red-flag rules and maps the total to a band.
- **AdjudicationScorer** — checks the draft for a clear recommendation, a cited basis,
  a payable that matches the computed figure, disclosed limit/deductible, and SIU
  routing when fraud is High.

## Data flow and sly_data

```
client ── sly_data{claim_text} ──► ClaimExtractor
                                     │ writes sly_data{claim, sensitive}
                                     ▼
ClaimIntakeAnalyst ─► CoverageOfficer ─► PolicyRetriever
                                     ─► CoverageEvaluator  (writes sly_data{coverage}, incl. payable)
                                     ▼
                            FraudScreener ─► FraudScorer    (reads claim+coverage, writes sly_data{fraud})
                                     ▼
                       (draft disposition assembled by front-man)
                                     ▼
                       AdjudicationCritic ─► AdjudicationScorer (reads sly_data{coverage,fraud} + draft)
                                     ▼
                       complete & grounded? ── no ──► fix gaps, revise (loop, max 2)
                                     │ yes
                                     ▼
                       DRAFT → adjuster approval → FINAL DISPOSITION
```

`sly_data` plays two roles defined by Neuro SAN: a **private channel** (the claimant's
identity, contact details, and bank account never enter any prompt) and a **bulletin
board** (the coded tools cooperate on a shared structure — claim, then coverage, then
fraud — without passing large payloads through the LLM).

## The coverage logic

`CoverageEvaluator` is the heart of the system and is fully deterministic:

1. **In force** — the loss date must fall within the policyholder's in-force window,
   else the claim is denied.
2. **Peril & sub-limit** — the claim peril is matched against each coverage's perils;
   when several coverages match, the one with the lowest limit governs (the sub-limit).
3. **Exclusions** — each policy exclusion declares `checks` (a peril list or text
   terms). If any check matches the claim, the exclusion is triggered and the claim is
   denied with that exclusion cited.
4. **Notice condition** — if the loss was reported later than the policy's notice
   window, that is surfaced as a condition concern.
5. **Payable** — for a covered loss, `payable = max(0, min(amount_claimed, limit) - deductible)`.

Because the policy (coverages, limits, deductibles, exclusion checks, conditions) is
data, adapting the system to another product or line of business is a JSON edit.

## The fraud screen

`FraudScorer` applies deterministic red-flags — late reporting, loss near policy
inception or expiry, amount at/over the limit, suspiciously round amounts — each
contributing points that map to a Low / Medium / High band. A High band recommends
routing to the Special Investigations Unit before payment. These are screening
indicators for a human, not determinations of fraud.

## The evaluation loop and human gate

`AdjudicationScorer` judges the *draft*, not the claim: it verifies there is a clear
recommendation, that it cites the governing coverage or exclusion, that the stated
payable equals the computed payable, that the limit and deductible are disclosed for a
payment, and that a High fraud band routes to INVESTIGATE. If the draft falls short,
the front-man fixes the named gaps and re-checks, up to two iterations. The disposition
is then presented as a draft and finalised only after the adjuster approves; a change
request routes the relevant part back to the right specialist.

## Why this is a good fit for Neuro SAN

Claims handling decomposes naturally into specialised roles, mixes language tasks with
deterministic computation (the coded-tools sweet spot), is regulated and auditable
(favouring grounded, cited decisions and a human gate), and handles sensitive data
(sly_data). AAOSA routing lets the orchestrator adapt to deny/investigate paths rather
than forcing a single hardcoded pipeline, and the policy-as-data and rules-as-data
design means the system extends to new products and rules with configuration, not
code rewrites.
