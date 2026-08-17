---
name: rank-open-problems
description: Review open research problems for scientific significance, source fidelity, accepted answer types, per-type verification contracts, and 0-10 verification difficulty.
---

# Rank Open Problems

Judge scientific value and the acceptance boundary, not how easy the problem is
to solve or retrieve.

## Role split

This policy is applied by two stages with different output contracts:

- **Selection** (production) canonicalizes and *routes*. It reports the
  canonical formulation plus `importance_level` and a free-form `assessment`
  narrative. It does **not** output significance levels, verification
  contracts, difficulty, or CI — Research produces those from scratch.
- **Research** produces the full published contract after the later-literature
  audit: one Problem Schema v1.0 record — significance level and description,
  per-answer-type verification contracts, difficulty, and CI — plus the
  `audit_outcome`.

The decisions below apply to whichever stage produces the corresponding field.

## Required decisions

1. Judge scientific significance and assign
   `scientific_significance.affected_field.level` (high/medium/low) with a
   specific `description` (Research only). Explain which knowledge,
   capability, bound, mechanism, experiment, or decision would materially
   change. Also retain the coarse `importance_level` (high/medium/low), which
   is the only importance field Selection reports.
2. Record every naturally acceptable answer type as a key of
   `verification_contract`; answer types are descriptive and never gates
   (Research).
3. Write each `verification_contract` entry as the exact acceptance condition
   for that answer type: what is submitted, what the reviewer checks, and what
   passes (Research). Never invent a proxy benchmark, arbitrary threshold, or
   favorable finite regime that changes the scientific question. The optional
   `ci_contract` records the mechanically executable part of that contract, or
   null when no reasonable automated acceptance exists.
4. Assign `verification_difficulty.score` from 0 to 10 as residual
   independent-review burden after mechanical checks, replay, and certificates
   are delegated, with a `rationale` (Research):
   - 0: every load-bearing claim is discharged by a pinned mechanical, replay, or
     certificate check;
   - 1-3: a few independent local reasoning units remain;
   - 4-6: connected derivations or substantial specification reconstruction;
   - 7-9: long, fragile, or novel reasoning chains;
   - 10: the essential claim cannot be decomposed into independent checks.
5. Record CI independently (Research). CI may automate delegable
   checks but never lowers the structural score and never gates a research
   problem.

An explicit finite counterexample, exact substitution check, finite
construction, source-faithful code-to-experiment comparison, or contract-pinned
Lean/Coq/Isabelle proof may score 0 when every load-bearing claim is discharged.
An ordinary natural-language proof reviewed as one inseparable whole scores 10.
For a parameter family, one checkable instance is not a family-level answer. For
an exact finite optimum, a maximizing object supplies only the lower bound unless
the result also contains independently decisive evidence of global optimality.

## Admission and ranking

High- and medium-importance Selection candidates proceed to later-literature
research — importance is the only selection gate. Publication requires an
`open` audited status and acceptance by the Problem Reviewer — an editing
review on a copy of the candidate folder, with LKM and web access, whose
corrected record is what gets compiled. A rejected
or non-open candidate is archived in the run directory, never re-issued or
decomposed into a queue. There is no maximum verification-difficulty
threshold. Rank first by current-open status and affected-field significance
level; use verification difficulty only as reviewer workload metadata.

## Output

- Selection returns the canonical candidates with `importance_level` and
  `assessment` (`schemas/stages/selection.schema.json`).
- Research returns a Problem Schema v1.0 record — title, abstract, background,
  references, previous_progress, problem_statement, scientific_significance,
  solution_difficulty, verification_contract, verification_difficulty — plus
  `audit_outcome` (`schemas/problem.schema.json`).

Use [the casebook](../../../docs/verification-difficulty-casebook.md) for score
boundary examples. It calibrates reviewer burden; it is not a deterministic
artifact classifier.
