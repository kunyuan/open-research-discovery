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
to find it. Preserve the original answer format. In the verification
rationale, explain why the result genuinely answers the question and any
one-sided, parameter-regime, or claim limitation. Do not impose a benchmark,
proxy, threshold, or formalization merely to make review easier. In
particular, distinguish an ordinary natural-language proof from a problem that
requires Lean/Coq/Isabelle code.

## 4. Verification difficulty

Assign an integer from 0 to 10:

- `0`: checking the submitted result itself basically decides whether the
  scoped problem is solved. This does not require mechanical verification.
- `1-3`: short, local, standard derivations are load-bearing.
- `4-6`: several nontrivial derivations depend on one another.
- `7-9`: the reasoning chain is long, specialized, broad, or fragile.
- `10`: correctness rests essentially on holistic review of a
  natural-language proof or scientific argument.

A finite counterexample, exact solution, executable algorithm, model, or
dataset may itself be the semantic answer and score 0 even when a human
Reviewer performs the check. A required formal proof artifact also scores 0
when the pinned kernel checks it. An ordinary written proof scores 10.
If a required property asks the Reviewer to establish a substantive
nonexistence, universality, or optimality argument, score that derivation
according to its length and dependency depth.
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
pseudocode. Pseudocode must name concrete inputs, outputs, and a known
terminating procedure rather than restating the target claim behind “decide”,
“prove”, or “verify”.

## 6. Current status and post-progress Problem Review

Only after intrinsic triage, audit later literature and assign `still_open`,
`partially_resolved`, `resolved`, `refuted`, or `uncertain`. Absence of a found
solution is not evidence of openness.

If major progress narrows or reframes the question, rewrite the surviving core
and repeat importance, expected-result, verification-difficulty, and CI judgments from
scratch. Create a derived problem only when the research object, assumptions,
regime, or acceptance boundary materially changed.

## Admission

Dispatch solver research when the surviving core is current-open, importance
is high or medium, and `verification_difficulty` is no greater than the
campaign limit. The score is invalid unless the rationale shows that the
expected result faithfully answers the surviving core. Prefer available CI
among otherwise equal candidates, but do not exclude a score-0 problem because
CI is blocked.

Never rank on searchability, expected solve time, candidate-generation cost,
search compute, feedback density, or probability of success.
