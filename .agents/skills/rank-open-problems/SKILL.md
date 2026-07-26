---
name: rank-open-problems
description: Screen and rank open research questions by scientific importance and whether an independent LLM or checker can basically judge correctness from the submitted result itself; record CI as an optional bonus. Use for open-problem triage, benchmark labeling, post-literature-audit reranking, or solver dispatch.
---

# Rank Open Problems

Judge the value and review boundary of a problem, not how hard it is to solve.

## Required decisions

1. Judge scientific importance as `high`, `medium`, `low`, or `unassessed`.
   State what scientifically changes if the problem is solved or materially
   advanced.
2. Choose one source-grounded, scientifically sufficient solution route.
   Preserve the original problem's answer format and state any one-sided or
   finite-regime limitation. Do not invent a benchmark, proxy, threshold, or
   formalization to make review easier.
3. Describe the expected final result in plain language.
4. Judge its review scope:

   - `result-only`: an independent LLM or checker can basically decide
     correctness from the submitted result, frozen problem, and declared
     reference data, without consulting the solver's search or reasoning
     process;
   - `result-and-derivation`: correctness also depends on reviewing a
     derivation or explanation outside the submitted result;
   - `expert-intensive`: substantial tacit or specialist judgment remains;
   - `unclassified`: the boundary is not yet clear.

   Apply the origin-hiding test: remove the producing agent's search log,
   chain of thought, and narrative. If the reviewer can no longer decide the
   scoped claim, it is not `result-only`.

   Code, a certificate, an exact solution, a model, a dataset, or formal proof
   may itself be the result. But never assume Lean/Coq/Isabelle for an ordinary
   proof question. Proof-assistant code counts as the result only when that is
   the answer format requested by the original problem.
5. Write a concrete acceptance boundary and short reviewer checklist.
6. Record CI independently:

   - `implemented`
   - `partial`
   - `pseudocode`
   - `reviewer-only`
   - `blocked`

   CI is a bonus, not an admission requirement. Give problem-specific
   pseudocode, runtime, and a hard timeout when possible. Executable CI does
   not by itself imply `result-only`.

## Admission and ranking

A problem is ready for solver research when:

- the current surviving core is open;
- importance is `high` or `medium`;
- the chosen route is scientifically sufficient; and
- review scope is `result-only`.

CI status does not block admission. Within otherwise equal problems, prefer
implemented CI, then partial CI, pseudocode, bounded reviewer-only checks, and
finally blocked CI. Do not rank on expected solve time, searchability,
candidate-space size, solver compute, feedback density, or probability of
success.

Keep nonqualifying problems visible with their labels. If later literature
narrows or reframes the question, rewrite the surviving core and repeat every
decision from scratch.

## Output

Return:

```text
id, importance, solution_route, route_scientific_effect, route_sufficiency,
route_scope_limitations, expected_result, review_scope, review_rationale,
review_protocol, ci_status, ci_pseudocode, estimated_review_time,
estimated_ci_runtime, ci_timeout_minutes
```

Use [the casebook](../../../docs/review-scope-casebook.md) for boundary
examples. The examples guide the LLM judgment; they are not a deterministic
artifact classifier.
