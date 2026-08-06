---
name: rank-open-problems
description: Review open research problems for scientific significance, source fidelity, accepted answer types, verification clarity, and 0-10 verification difficulty.
---

# Rank Open Problems

Judge scientific value and the acceptance boundary, not how easy the problem is
to solve or retrieve.

## Required decisions

1. Assign `scientific_significance_score` from 0 to 10. Explain which knowledge,
   capability, bound, mechanism, experiment, or decision would materially change.
   Also retain the coarse `importance_level` for compatibility.
2. State `expected_result` without proposing a method. Record every naturally
   acceptable `answer_type`; answer types are descriptive and never gates.
3. Set `verification_clarity`:
   - `clear`: the submission, scope/protocol, checks, and passing outcome are
     unambiguous;
   - `needs_decomposition`: the theme can be split into concrete checkable
     subproblems;
   - `unverifiable`: no faithful, meaningful decomposition is available.
4. Write `verification_standard` as the exact acceptance condition. Never invent
   a proxy benchmark, arbitrary threshold, or favorable finite regime that changes
   the scientific question.
5. If clarity is not `clear`, return `proposed_subproblems`, each with its own
   question, answer types, verification standard, and decomposition rationale.
6. Assign `verification_difficulty` from 0 to 10 as residual independent-review
   burden after mechanical checks, replay, and certificates are delegated:
   - 0: every load-bearing claim is discharged by a pinned mechanical, replay, or
     certificate check;
   - 1-3: a few independent local reasoning units remain;
   - 4-6: connected derivations or substantial specification reconstruction;
   - 7-9: long, fragile, or novel reasoning chains;
   - 10: the essential claim cannot be decomposed into independent checks.
7. Record CI independently. CI may automate delegable checks but never lowers the
   structural score and never gates a research problem.

An explicit finite counterexample, exact substitution check, finite
construction, source-faithful code-to-experiment comparison, or contract-pinned
Lean/Coq/Isabelle proof may score 0 when every load-bearing claim is discharged.
An ordinary natural-language proof reviewed as one inseparable whole scores 10.
For a parameter family, one checkable instance is not a family-level answer. For
an exact finite optimum, a maximizing object supplies only the lower bound unless
the result also contains independently decisive evidence of global optimality.

## Admission and ranking

High- and medium-importance candidates proceed to later-literature research.
Schema-v2 publication requires a current open core, supported context,
`verification_clarity: clear`, and independent Problem Reviewer acceptance.
There is no maximum verification-difficulty threshold. Rank first by scientific
significance and current-open status; use verification difficulty only as reviewer
workload metadata and a secondary scheduling signal.

Schema-v1 campaigns and frozen benchmarks retain their configured legacy
verification cutoff for reproducibility. Do not apply that compatibility rule
to schema-v2 topic campaigns.

## Output

Return the schema fields for significance, expected result, answer types,
verification clarity and standard, optional decomposition, 0-10 verification
difficulty and rationale, and CI status.

Use [the casebook](../../../docs/verification-difficulty-casebook.md) for score
boundary examples. It calibrates reviewer burden; it is not a deterministic
artifact classifier.
