# Verification difficulty casebook

`verification_difficulty` measures the work needed to independently verify a
submitted answer. It does not measure the difficulty of finding that answer.

The score is an integer from 0 to 10:

- **0 — final-result scoped.** After checking the submitted result itself, a
  Reviewer can basically decide whether the scoped problem is solved. The check
  may be automated or manual.
- **1–3 — light derivation review.** A few short, local, standard arguments are
  load-bearing.
- **4–6 — connected derivation review.** Several nontrivial claims depend on
  one another.
- **7–9 — heavy derivation review.** The argument is long, specialized, broad,
  or fragile, with many load-bearing dependencies.
- **10 — holistic natural-language proof review.** Correctness rests
  essentially on reviewing a natural-language proof or scientific argument as
  a whole.

Increase the score when more claims depend on earlier claims that cannot be
settled by checking the final result. CI is separate: a problem can score 0
without machine CI, and a high-score problem can still have useful partial CI.

## Score-0 examples

These examples are all final-result scoped:

- an explicit finite counterexample whose hypotheses and violation can be
  checked by a human Reviewer;
- an exact solution checked against the defining equation, domain, boundary
  conditions, and singularities;
- a finite construction whose required properties can be inspected directly;
- a complete closed-form spectrum checked against the defining recurrence or
  characteristic polynomial and multiplicities;
- code rerun under a fixed experimental protocol to compare with specified
  experimental data or a named baseline;
- an algorithm required to meet a fixed output or performance target that the
  submitted implementation and measurements directly test;
- a mathematical proof that the problem explicitly requires as Lean, Coq, or
  Isabelle code and that the pinned kernel accepts.

Score 0 does not mean that every check must be mechanical, cheap, or already
implemented in CI. It means that validation is basically scoped to the final
answer instead of the solver's substantive derivation.

## Boundary examples

| Problem contract | Score | Reason |
|---|---:|---|
| Prove theorem T in ordinary mathematical prose | 10 | Acceptance rests on holistic natural-language proof review |
| Submit a Lean 4 proof of theorem T | 0 | Kernel acceptance checks the required final result |
| Find an exact global optimum, with no certificate format | 7 | Global optimality needs a substantial argument |
| Find the optimum and submit the requested replayable exact upper-bound certificate | 0 | Matching lower and upper bounds are checked from the result |
| Give one finite counterexample | 0 | The witness itself settles the universal finite claim |
| Refute a uniform epsilon-delta claim with an infinite family and tail argument | 6 | The limiting construction and quantifiers require connected derivation review |
| Write code and compare with fixed experimental observations | 0 | Replaying the declared comparison checks the scoped result |
| Give an algorithm and prove a worst-case complexity theorem | 8 | Running the code does not establish the theorem |
| Construct A and prove no B exists | 8 | A can be checked directly, but nonexistence is a separate universal argument |
| Explain robustness across all regimes from a finite benchmark | 9 | Generalization and scientific interpretation remain load-bearing |

## Pipeline rule

Triage records:

- `verification_difficulty`;
- `verification_difficulty_rationale`;
- the expected final result;
- importance and optional CI.

A campaign sets `limits.max_verification_difficulty`. The default is 3. An
important candidate proceeds when its score is at most that limit. Setting the
limit to 0 keeps only final-result-scoped candidates.

The Research Agent re-scores the surviving open core after the literature
audit. The Problem Reviewer checks that the score is supported and that any
claimed CI is operational. The score is used directly for ranking; no parallel
artifact taxonomy or binary review-scope label is needed.

The executable examples live in
`tests/fixtures/verification_difficulty_cases.json`.
