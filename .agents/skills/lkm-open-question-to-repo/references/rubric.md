# Candidate rubric

Apply this rubric first to the source-era question and again to the surviving
core whenever later literature reports major progress.

## 1. Canonical candidate

- Require dedicated `data.papers[].open_questions` provenance.
- Split separable targets into atomic questions with exact supporting excerpts.
- Merge equivalent formulations.
- Do not sharpen a direction into an unstated conjecture, threshold, or
  benchmark.

## 2. Scientific importance

Require a concrete consequence, such as changing a recognized bound,
construction, classification, algorithmic bottleneck, actively used
conjecture, or dependency shared by later results. Retrieval rank and generic
claims of interest are not evidence.

## 3. One sufficient route

Choose one source-grounded route before judging Solution Review cost. State
whether it resolves, refutes, proves, sharpens, constructs, or makes
independently meaningful partial progress. Record all one-sided,
parameter-regime, and claim limitations.

Preserve the original answer format. Do not impose a benchmark, proxy,
threshold, or formalization merely to make Solution Review easier. In
particular, do not turn an ordinary proof question into Lean/Coq/Isabelle after
the fact.

## 4. Result-only judgment

Describe the expected final result in plain language. Then hide the solver's
search log, chain of thought, and narrative.

- `result-only`: an independent LLM or checker can basically decide
  correctness from the submitted result, frozen problem, and declared
  reference data;
- `result-and-derivation`: correctness also needs a derivation or explanation
  outside the submitted result;
- `expert-intensive`: substantial tacit or specialist judgment remains;
- `unclassified`: the boundary is not clear.

A finite counterexample, exact solution, certificate, executable algorithm,
model, dataset, or formal proof may itself be the result. Formal proof code
counts only when that is the answer format requested by the original problem.
Exact solutions establish only what direct equation, boundary, domain, and
singularity checks cover. Models establish only the frozen observables,
uncertainties, population, and regime in their acceptance boundary. Do not
silently add uniqueness, generality, complexity, causality, or mechanism.

The Problem Reviewer makes this semantic judgment directly. Separately write
a short, problem-specific `solution_review_checklist` and acceptance boundary
for use after a solver submits a result. That checklist verifies the solution;
it does not decide whether the research problem is important or worth
dispatching. Deterministic code validates only that the fields exist.

## 5. Optional CI

Record CI as:

- `implemented`
- `partial`
- `pseudocode`
- `solution-reviewer-only`
- `blocked`

CI is a bonus, not a gate. When possible, give problem-specific pseudocode,
runner requirements, runtime, and a hard timeout. Structural schema CI is not
substantive scientific verification. Use a zero-minute timeout only when no
machine CI can run; do not disguise assignment to a Solution Reviewer as CI
pseudocode.

## 6. Current status and post-progress Problem Review

Only after intrinsic triage, audit later literature and assign `still_open`,
`partially_resolved`, `resolved`, `refuted`, or `uncertain`. Absence of a found
solution is not evidence of openness.

If major progress narrows or reframes the question, rewrite the surviving core
and repeat importance, route sufficiency, result-only judgment, and CI
assessment from scratch. Create a derived problem only when the research
object, assumptions, regime, or success condition materially changed.

## Admission

Dispatch solver research when the surviving core is current-open, importance
is high or medium, the chosen route is scientifically sufficient, and Solution
Review scope is `result-only`. Prefer available CI among otherwise equal
candidates, but do not exclude a result-only problem because CI is blocked.

Never rank on searchability, expected solve time, candidate-generation cost,
search compute, feedback density, or probability of success.
