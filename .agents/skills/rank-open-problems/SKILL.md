---
name: rank-open-problems
description: Act as a Problem Reviewer to screen and rank open research questions by scientific importance, target fidelity, and 0-10 verification difficulty; record CI as an optional bonus. Use for open-problem triage, benchmark labeling, post-literature-audit reranking, or solver dispatch.
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
3. Assign `verification_difficulty` from 0 to 10. The score is the residual
   burden left on an independent reviewer after every mechanically delegable
   check — kernels, test suites, SMT/SAT solvers, substitution, replay under
   a pinned protocol, certificate checks — has been delegated:

   - `0`: every load-bearing claim is discharged by mechanical checks,
     replay, or certificates, and specification fidelity is trivial — the
     formal statement, protocol, or target is pinned by the contract or
     directly comparable to the problem statement. This does not require CI;
     manual execution of a fixed procedure stays 0.
   - `1-3`: the residual is a few independent, local, standard reasoning
     units, each checkable at a glance.
   - `4-6`: the residual contains connected derivations whose steps depend on
     one another, or specification fidelity itself requires substantial
     reconstruction.
   - `7-9`: the residual is a long, fragile, or novel chain, or requires
     reviewing substantial code for correctness rather than running it.
   - `10`: the essential claim cannot be decomposed into independently
     checkable units.

   In `verification_difficulty_rationale`, explain why the expected result
   genuinely answers the source question, any limitations, and exactly which
   residual reasoning units the Reviewer must still inspect. Do not move
   burden into an unverified specification gap to lower the score.

   Score-0 examples include an explicit counterexample, an exact solution, a
   finite construction, a complete closed-form spectrum, a fixed
   code-to-experiment comparison, and a required Lean/Coq/Isabelle proof
   artifact whose statement the contract pins and whose kernel accepts it. A
   human Reviewer may perform the fixed procedure. An ordinary
   natural-language proof scores 10.

   For an executable comparison, check that the source grounds the scientific
   target, baseline, applicable regime, and comparison axes strongly enough
   that replay answers the question. Do not demand that the source pre-enumerate
   routine reproducibility details: locked dependencies, exact versions,
   seeds, repetitions, statistical tolerances, and machine-readable outputs
   may be frozen in the final result bundle. They are not extra Triage fields.
   This does not permit choosing a favorable dataset, physical regime, metric,
   or success threshold that changes the scientific target. A successful
   finite benchmark does not establish a broader generalization, causality,
   convergence, or asymptotic-complexity claim; those extra arguments raise
   the score.

   When several outcomes can conclusively answer the source question, choose
   one source-faithful expected result for dispatch. A finite counterexample
   can therefore score 0 even when proving the positive statement would score
   much higher. The chosen result must still resolve
   the scoped question; a merely improved bound or favorable instance does not
   qualify unless that is what the source asks for.

   For an exact finite optimum, a maximizing object checks only the lower-bound
   side. Score the missing upper-bound derivation unless the final result also
   contains independently decisive evidence.
   For a question about a parameter family, do not substitute one checkable
   instance: instance-level CI is partial verification, not resolution of the
   family-level claim.

   A finite object is not automatically 0 when a required property is itself a
   universal or nonexistence statement. Score the substantive proof needed to
   establish non-representability, absence of a morphism, global optimality, or
   another target-level negative claim.
4. Record CI independently:

   - `implemented`
   - `partial`
   - `pseudocode`
   - `solution-reviewer-only`
   - `blocked`

   CI is a bonus, not an admission requirement. It is the operational layer:
   its status records how much of the delegable checking has been automated,
   and executable CI
   does not determine the structural verification score. Add problem-specific
   pseudocode, runtime, and a hard timeout only when useful. Use `ci_timeout_minutes: 0` when no
   machine CI can run. Do not present assignment to a human or Solution
   Reviewer as CI pseudocode. Every load-bearing pseudocode step must name a
   known terminating procedure with concrete inputs and outputs; do not restate
   the scientific acceptance criterion behind verbs such as “decide”,
   “prove”, or “verify”.

When packaging an admitted problem, expand the expected result and rationale
into the Solution Review acceptance boundary and checklist. That checklist is
used only after a solver submits a result; it is not another Triage field.

## Admission and ranking

Every high- or medium-importance canonical candidate proceeds to
later-literature status Research regardless of verification difficulty.

A problem is ready for solver research when:

- the current surviving core is open;
- importance is `high` or `medium`;
- `verification_difficulty` is no greater than the campaign's configured
  maximum, which defaults to 3.

The score is invalid unless the expected result faithfully
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
  search, or unrelated repository files. Use `unassessed` — the benchmark
  uses the same label — when the frozen evidence is insufficient.
- Predict importance, verification difficulty, and CI independently. Do not ask
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
verification_difficulty, verification_difficulty_rationale, ci_status
```

Optionally add `ci_pseudocode`, `estimated_ci_runtime`, and
`ci_timeout_minutes`. The timeout is an integer from 0 to 1440, where 0 means
no runnable CI.

Use [the casebook](../../../docs/verification-difficulty-casebook.md) for boundary
examples. The examples guide the LLM judgment; they are not a deterministic
artifact classifier.
