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

## 3. Expected result

Describe what a correct final submission would contain without proposing how
to find it. Preserve the original answer format. In the Solution Review
rationale, explain why the result genuinely answers the question and any
one-sided, parameter-regime, or claim limitation. Do not impose a benchmark,
proxy, threshold, or formalization merely to make review easier. In
particular, do not turn an ordinary proof question into Lean/Coq/Isabelle.

## 4. Result-only judgment

Describe the expected final result in plain language. Then hide the solver's
search log, chain of thought, and narrative.

- `result-only`: an independent LLM or checker can basically decide
  correctness by inspecting or replaying the submitted final answer or
  artifact against the frozen problem and declared reference data, without
  substantively reviewing a non-machine-checkable solution derivation;
- `result-and-derivation`: correctness also needs substantive review of a
  mathematical or scientific derivation, even when it is included in the
  submission;
- `expert-intensive`: substantial tacit or specialist judgment remains;
- `unclassified`: the boundary is not clear.

A finite counterexample, exact solution, certificate, executable algorithm,
model, or dataset may itself be the result. An ordinary written proof remains
`result-and-derivation`. Formal proof code counts as the result only when that
is the answer format requested by the original problem. Do not extend this
restriction to native exact certificates: a source-faithful SOS identity,
matching primal-dual certificate, or finite witness may count as the result
when replaying it directly establishes the unchanged scientific target.
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
and repeat importance, expected-result, result-only, and CI judgments from
scratch. Create a derived problem only when the research object, assumptions,
regime, or acceptance boundary materially changed.

## Admission

Dispatch solver research when the surviving core is current-open, importance
is high or medium, and Solution Review scope is `result-only`. This label is
invalid unless the rationale shows that the expected result faithfully answers
the surviving core. Prefer available CI among otherwise equal candidates, but
do not exclude a result-only problem because CI is blocked.

Never rank on searchability, expected solve time, candidate-generation cost,
search compute, feedback density, or probability of success.
