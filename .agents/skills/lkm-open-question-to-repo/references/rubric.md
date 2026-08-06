# Candidate rubric

Legacy v1 reference — retained for schema-v1 campaigns; v2 topic campaigns follow the prompts and rank-open-problems skill.

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

Assign an integer from 0 to 10. The score is the residual burden left on an
independent reviewer after every mechanically delegable check has been
delegated. Claims are discharged through modes of increasing cost: mechanical
checks (kernels, type checkers, test suites, SMT/SAT, substitution, finite
enumeration), replay under a pinned protocol, and certificate checks cost a
small constant; derivation review grows with chain length, dependency depth,
and non-standard technique; holistic judgment cannot be decomposed.

- `0`: every load-bearing claim is discharged by mechanical checks, replay,
  or certificates, and specification fidelity is trivial — the formal
  statement, protocol, or target is pinned by the contract or directly
  comparable to the problem statement. This does not require CI; manual
  execution of a fixed procedure stays 0.
- `1-3`: the residual is a few independent, local, standard reasoning units,
  each checkable at a glance.
- `4-6`: the residual contains connected derivations whose steps depend on
  one another, or specification fidelity itself requires substantial
  reconstruction.
- `7-9`: the residual is a long, fragile, or novel chain, or requires
  reviewing substantial code for correctness rather than running it.
- `10`: the essential claim cannot be decomposed into independently checkable
  units.

A finite counterexample, exact solution, executable algorithm, model, or
dataset may itself be the semantic answer and score 0 even when a human
Reviewer performs the fixed procedure. A required formal proof artifact also
scores 0 when the contract pins the formal statement and the pinned kernel
checks it; otherwise verifying that the statement faithfully encodes the
problem is itself residual derivation review, typically 1-3. An ordinary
written proof scores 10.
If a required property asks the Reviewer to establish a substantive
nonexistence, universality, or optimality argument, score that derivation
according to its length and dependency depth.
Exact solutions establish only what direct equation, boundary, domain, and
singularity checks cover. Models establish only the frozen observables,
uncertainties, population, and regime in their acceptance boundary. Do not
silently add uniqueness, generality, complexity, causality, or mechanism.
Do not move burden into an unverified specification gap to lower the score,
and do not invent a proxy benchmark or weaken the scientific target.

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

CI is a bonus, not a gate, and cannot lower the structural verification
score: its status records how much of the delegable checking has been
automated so far. When possible, give problem-specific pseudocode,
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

Audit later literature for every high- or medium-importance canonical
candidate, regardless of verification difficulty.

Dispatch solver research when the surviving core is current-open, importance
is high or medium, and `verification_difficulty` is no greater than the
campaign limit. The score is invalid unless the rationale shows that the
expected result faithfully answers the surviving core. Prefer available CI
among otherwise equal candidates, but do not exclude a score-0 problem because
CI is blocked.

Never rank on searchability, expected solve time, candidate-generation cost,
search compute, feedback density, or probability of success.
