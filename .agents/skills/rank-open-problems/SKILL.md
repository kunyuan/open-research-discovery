---
name: rank-open-problems
description: Review open research problems for scientific significance, source fidelity, accepted answer types, verification clarity, and 0-10 verification difficulty.
---

# Rank Open Problems

Judge scientific value and the acceptance boundary, not how easy the problem is
to solve or retrieve.

## Role split

This policy is applied by two stages with different output contracts:

- **Selection** (production) canonicalizes and *routes*. It reports the
  canonical formulation plus `importance_level`,
  `verification_clarity`, and a conditional decomposition, plus a free-form
  `assessment`. It does **not** output significance scores, expected result,
  verification standard/difficulty, or CI status — Research
  produces those from scratch.
- **Research** produces the full published contract after the later-literature
  audit: significance score and rationale, expected result, answer types,
  verification standard, difficulty, and CI.

The decisions below apply to whichever stage produces the corresponding field.

## Required decisions

1. Judge scientific significance and assign `scientific_significance_score`
   from 0 to 10 (Research only). Explain which knowledge,
   capability, bound, mechanism, experiment, or decision would materially
   change. Also retain the coarse `importance_level` (high/medium/low), which
   is the only importance field Selection reports.
2. State `expected_result` without proposing a method (Research).
   Record every naturally acceptable `answer_type`; answer types are
   descriptive and never gates.
3. Set `verification_clarity`:
   - `clear`: the submission, scope/protocol, checks, and passing outcome are
     unambiguous;
   - `needs_decomposition`: the theme can be split into concrete checkable
     subproblems;
   - `unverifiable`: the candidate as stated admits no faithful pass/fail
     standard. This is not a terminal verdict: the candidate must be split
     into more specific subproblems.
4. Write `verification_standard` as the exact acceptance condition (Research).
   Never invent a proxy benchmark, arbitrary threshold, or
   favorable finite regime that changes the scientific question.
5. Decomposition follows the clarity value exactly (Selection and Research):
   - `clear`: return an empty `proposed_subproblems` and
     `decomposition_parent_coverage: not_applicable`;
   - `needs_decomposition` or `unverifiable`: return at least one entry in
     `proposed_subproblems` and set coverage to `complete` or `partial`. Each
     subproblem carries its own question, scope, answer types, verification
     standard, source support, and relation to the parent. Every proposed
     subproblem enters the persistent topic queue and is replayed as a
     candidate in a later campaign, so a non-clear candidate is retained and
     split rather than dropped.
6. Assign `verification_difficulty` from 0 to 10 as residual independent-review
   burden after mechanical checks, replay, and certificates are delegated
   (Research):
   - 0: every load-bearing claim is discharged by a pinned mechanical, replay, or
     certificate check;
   - 1-3: a few independent local reasoning units remain;
   - 4-6: connected derivations or substantial specification reconstruction;
   - 7-9: long, fragile, or novel reasoning chains;
   - 10: the essential claim cannot be decomposed into independent checks.
7. Record CI independently (Research). CI may automate delegable
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

High- and medium-importance Selection candidates with `verification_clarity: clear`
proceed to later-literature research. Publication requires a current
open core, supported context, `verification_clarity: clear`, and independent
Problem Reviewer acceptance. There is no maximum verification-difficulty
threshold. Rank first by current-open status and scientific significance; use
verification difficulty only as reviewer workload metadata and a secondary
scheduling signal.

## Output

- Selection returns the canonical candidates with routing fields plus
  `assessment` (`schemas/stages/selection.schema.json`).
- Research returns the nested problem draft with significance, expected result,
  answer types, verification clarity and standard, conditional decomposition,
  0-10 verification difficulty and rationale, and CI
  (`schemas/stages/research.schema.json`).

Use [the casebook](../../../docs/verification-difficulty-casebook.md) for score
boundary examples. It calibrates reviewer burden; it is not a deterministic
artifact classifier.
