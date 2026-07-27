---
name: rank-open-problems
description: Act as a Problem Reviewer to screen and rank open research questions by scientific importance, target fidelity, and whether a future Solution Reviewer can basically judge correctness from the submitted result itself; record CI as an optional bonus. Use for open-problem triage, benchmark labeling, post-literature-audit reranking, or solver dispatch.
---

# Rank Open Problems

Judge the value and review boundary of a problem, not how hard it is to solve.

## Required decisions

1. Judge scientific importance as `high`, `medium`, `low`, or `unassessed`.
   State what scientifically changes if the problem is solved or materially
   advanced.
2. Describe the expected final result in plain language. Do not propose a
   solving method. Preserve the answer format requested or naturally committed
   to by the source question.
3. As the Problem Reviewer, judge the future Solution Review scope:

   - `result-only`: an independent reviewer can basically decide correctness
     from only the final result naturally required by the original problem,
     without reviewing the solver's reasoning process;
   - `result-and-derivation`: correctness also depends on substantively
     reviewing a mathematical or scientific derivation, even when that
     derivation is included in the submission;
   - `expert-intensive`: substantial tacit or specialist judgment remains;
   - `unclassified`: the boundary is not yet clear.

   In `solution_review_rationale`, explain why the expected result genuinely
   answers the source question, any limitations on that claim, and whether
   review must assess a derivation rather than only the final answer or
   artifact. Do not invent a benchmark, proxy, threshold, or formalization to
   make review easier.

   Apply one test: without reviewing the solver's reasoning process, can the
   future Solution Reviewer basically decide correctness from only the
   source-faithful final result? If not, it is not `result-only`.

   Judge the source's semantic answer contract, not a specially constrained
   future submission. Code, a finite witness, an exact solution, a model, or a
   dataset may itself be the answer. An ordinary written proof remains
   `result-and-derivation`. Proof-assistant code or a replayable proof
   certificate counts as the result only when the original problem requests
   that answer format. Do not append Lean, an SOS identity, a primal-dual
   certificate, or another file format merely to obtain `result-only`.

   When several outcomes can conclusively answer the source question, choose
   one source-faithful expected result for dispatch. A finite counterexample
   can therefore be `result-only` even when proving the positive statement
   would require derivation review. Do not require every possible solution
   route to have the same review scope. The chosen result must still resolve
   the scoped question; a merely improved bound or favorable instance does not
   qualify unless that is what the source asks for.

   For an exact finite optimum, a maximizing object checks only the lower-bound
   side. Do not call it `result-only` unless the natural final result also makes
   the upper bound independently decidable without reviewing solver reasoning.
   For a question about a parameter family, do not substitute one checkable
   instance: instance-level CI is partial verification, not resolution of the
   family-level claim.
4. Record CI independently:

   - `implemented`
   - `partial`
   - `pseudocode`
   - `solution-reviewer-only`
   - `blocked`

   CI is a bonus, not an admission requirement. Add problem-specific
   pseudocode, runtime, and a hard timeout only when useful. Executable CI does
   not by itself imply `result-only`. Use `ci_timeout_minutes: 0` when no
   machine CI can run. Do not present assignment to a human or Solution
   Reviewer as CI pseudocode.

When packaging an admitted problem, expand the expected result and rationale
into the Solution Review acceptance boundary and checklist. That checklist is
used only after a solver submits a result; it is not another Triage field.

## Admission and ranking

A problem is ready for solver research when:

- the current surviving core is open;
- importance is `high` or `medium`;
- Solution Review scope is `result-only`.

The `result-only` label is invalid unless the expected result faithfully
answers the source question; this is a semantic check recorded in the
rationale, not a separate Boolean field. CI status does not block admission.
Within otherwise equal problems, prefer implemented CI, then partial CI,
pseudocode, bounded Solution-Reviewer-only checks, and finally blocked CI.
Do not rank on expected solve time,
searchability, candidate-space size, solver compute, feedback density, or
probability of success.

Keep nonqualifying problems visible with their labels. If later literature
narrows or reframes the question, rewrite the surviving core and repeat every
decision from scratch.

## Benchmark use

Separate dataset construction from evaluation.

- During construction, search and audit the literature, freeze the surviving
  question and a neutral evidence dossier, then obtain independent labels.
- During formal evaluation, use only the frozen dossier. Do not call LKM, Web
  search, or unrelated repository files. Use `unassessed` or the benchmark's
  `uncertain` equivalent when the frozen evidence is insufficient.
- Predict importance, Solution Review scope, and CI independently. Do not ask
  the evaluated Triage Agent to re-audit current openness; exclude closed or
  identity-uncertain cases before freezing the dataset.
- Keep prediction and gold artifacts separate. Never use the same agent output
  as its own gold label.
- Refresh literature only when creating a new version. Repeated scoring of one
  version must replay the same frozen inputs.

## Output

Return:

```text
candidate_id, importance_level, importance_rationale, expected_result,
solution_review_scope, solution_review_rationale, ci_status
```

Optionally add `ci_pseudocode`, `estimated_ci_runtime`, and
`ci_timeout_minutes`. The timeout is an integer from 0 to 1440, where 0 means
no runnable CI.

Use [the casebook](../../../docs/solution-review-scope-casebook.md) for boundary
examples. The examples guide the LLM judgment; they are not a deterministic
artifact classifier.
