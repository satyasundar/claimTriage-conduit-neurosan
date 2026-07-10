# Project Summary — Claims Triage Assistant

**Track:** 2 — Vibing + Grounding (Neuro SAN Studio)   
**Team size:** 1   
**Framework:** Neuro SAN / Neuro SAN Studio (Apache-2.0)  

## The problem

Insurance claims triage is high-volume, regulated, and unforgiving of error. For each
claim an adjuster must determine whether the loss is covered under the policy, apply
the right limit and deductible, compute what is payable, watch for fraud indicators,
and document a defensible rationale — all while protecting the claimant's personal and
financial data. It is an ideal candidate for a governed, multi-agent workflow that
augments — but does not replace — a human adjuster.

## The solution

A Neuro SAN agent network that triages a claim against the policy and recommends a
disposition (pay / deny / investigate), gated by adjuster approval. A front-man
orchestrator routes (via AAOSA) to four specialist agents:

- a **claim intake analyst** that extracts the claim facts and redacts PII,
- a **coverage officer** that adjudicates coverage and reports the payable,
- a **fraud screener** that runs deterministic red-flag rules, and
- an **adjudication critic** that re-checks the disposition and drives an evaluation loop.

Five deterministic Python **coded tools** form the grounding layer (FNOL extraction +
redaction, policy retrieval, coverage adjudication and payable math, fraud scoring, and
a completeness gate). The claim and its sensitive fields travel through **sly_data**,
Neuro SAN's private channel, so the LLM only ever sees redacted text. The workflow ends
at a **human approval gate**: the system presents a draft disposition and finalises it
only when the adjuster approves.

## What makes it notable

- **The model never invents a number.** Coverage is decided against the policy wording,
  and the payable amount is computed deterministically as
  `min(amount_claimed, limit) - deductible` (floored at zero). The critic fails any
  draft whose stated payable does not match the computed figure.
- **Privacy by construction.** Claimant name, policy number, address, phone, email, and
  bank/IBAN are redacted into `sly_data` before any LLM call and never re-enter a prompt.
- **Auditable decisions.** Every coverage conclusion cites a coverage or exclusion code;
  exclusions and fraud rules are declarative data, so decisions are explainable and the
  rulebook is transparent.
- **Screen, don't accuse — and never auto-decide.** Fraud red-flags are indicators for
  human review; a High band forces an INVESTIGATE / SIU referral, and the adjuster signs
  off every disposition.

## Effective use of Neuro SAN

The project uses the framework's signature capabilities idiomatically: an AAOSA agent
network defined in HOCON; five coded tools as the grounding layer; `sly_data` as both a
private channel and an inter-tool bulletin board; and network `metadata` with sample
queries for the nsflow UI. LLM reasoning and deterministic computation are cleanly
separated — the LLMs handle language and explanation, the coded tools handle parsing,
policy retrieval, the coverage maths, fraud scoring, and the quality gate.

## Results

On the included synthetic claim — a $48,000 burst-pipe water-damage loss — the engine
confirms the policy was in force, matches the $40,000 water sub-limit, applies the
$1,000 deductible, and recommends **PAY $39,000**, citing the governing coverage and
noting that the claim was capped at the sub-limit. It redacts seven PII fields
(including the IBAN) into the private channel and flags two **low**-severity fraud
indicators with no SIU referral. The offline test suite also verifies a **DENY** (flood
exclusion triggered) and an **INVESTIGATE** (loss near inception plus late reporting →
High fraud band) — all with no LLM or network call.

## Impact and next steps

The pattern generalises across lines of business: adding auto, travel, or commercial
products is a matter of adding policy definitions keyed by product and selecting by the
claim's policy type. Natural extensions include a claimant-letter generator that drafts
correspondence from the approved disposition, prior-claims history fed through sly_data
to enrich the fraud score, and a regulatory-disclosure check layered onto the critic.

*All data used is synthetic. No PII, real policyholder, claim, or insurer is included.
This is a decision-support tool for a human adjuster, not an automated decision system.*
