# Verification difficulty casebook

`verification_difficulty` measures the residual burden left on an independent
reviewer after every mechanically delegable check has been delegated. It does
not measure the difficulty of finding the answer.

Score the cheapest sound verification path the contract permits — not the
solver's path, and not the scientific difficulty of discovering the answer.

## Verification modes

Every load-bearing claim is discharged through one of five modes. The mode,
not the domain, sets the cost:

- **M — mechanical check.** Lean kernels, type checkers, test suites, SMT/SAT
  solvers, numerical substitution, finite enumeration. Cost is a small
  constant, independent of the underlying proof or computation size. A
  theoretical derivation whose correctness a machine can verify falls in M.
- **R — replay.** Rerunning code or an experiment under a pinned protocol.
  Cost is environment setup plus protocol fidelity, not understanding.
- **C — certificate check.** A witness, dual certificate, or closed-form
  object settles the claim by a short check; the search is not redone.
- **D — derivation review.** Reconstructing the submitter's natural-language
  or symbolic reasoning. Cost grows with chain length, dependency depth, and
  non-standard technique. Code whose acceptance condition is universal
  correctness is still D: the reviewer must read it, not just run it.
- **H — holistic judgment.** A natural-language scientific argument reviewed
  as a whole. Highest cost; cannot be decomposed.

## Score bands

The score is an integer from 0 to 10:

- **0 — no residual.** Every load-bearing claim is discharged by M, R, or C,
  and specification fidelity is trivial: the formal statement, protocol, or
  target is pinned by the contract or directly comparable to the problem
  statement. Score 0 does not require that CI exists; manual execution of a
  fixed procedure stays 0.
- **1–3 — light residual.** A few independent, local, standard reasoning
  units, each checkable at a glance.
- **4–6 — connected residual.** The residual contains connected derivations
  whose steps depend on one another, or specification fidelity itself requires
  substantial reconstruction.
- **7–9 — heavy residual.** The residual is a long, fragile, or novel chain,
  or requires reviewing substantial code for correctness rather than running
  it.
- **10 — holistic residual.** The essential claim cannot be decomposed into
  independently checkable units.

## Specification fidelity

Specification fidelity — whether a formal statement faithfully encodes the
original problem — is the easiest place to hide burden. Do not move burden
into an unverified specification gap to lower the score.

A Lean proof scores 0 only when the contract pins the formal statement, or
the statement is directly comparable to the problem statement. Otherwise
checking the statement against the informal problem is itself derivation
review and counts as residual work, typically 1–3.

## CI: the operational layer

CI is delegation institutionalized: it automates the delegable checks. The
score above is structural — a property of the contract — and CI cannot lower
it. CI status tracks how much of the delegable checking has been automated so
far, and improves over time.

The reviewer's actual burden in practice is the structural residual plus the
manual execution of delegable checks not yet automated. CI must run the
acceptance condition itself, never a proxy metric. Auditing a CI
configuration is a one-time fixed cost, done when the problem enters the
repository; it is not part of the per-review difficulty score.

Only better contract design — required certificates, pinned formal
statements — and better problem decomposition lower the structural score.

## Score-0 examples

These examples are all fully discharged by M, R, or C with trivial
specification fidelity:

- an explicit finite counterexample whose hypotheses and violation can be
  checked by a human Reviewer;
- an exact solution checked by direct substitution against pinned defining
  equations, domain, boundary conditions, and singularities, without a
  separate numerical-coverage judgment;
- a finite construction whose required properties can be inspected directly;
- a complete closed-form spectrum checked against the defining recurrence or
  characteristic polynomial and multiplicities;
- code rerun under a fixed experimental protocol to compare with specified
  experimental data or a named baseline;
- an algorithm required to meet a fixed output or performance target that the
  submitted implementation and measurements directly test;
- a mathematical proof that the problem explicitly requires as Lean, Coq, or
  Isabelle code, with the statement pinned by the contract and accepted by
  the pinned kernel.

Score 0 does not mean that every check must be mechanical, cheap, or already
implemented in CI. It means that no derivation review or holistic judgment is
left after the delegable checks.

## Numerically verified exact solutions

Score an exact solution as **2** when its practical acceptance path relies
primarily on independently reproducing the original finite-size model
numerically and comparing its predictions with the submitted formulas. This
applies naturally to many quantum many-body and integrable-model results, such
as spectra, gaps, correlators, and finite-time evolution.

The two-point light residual is local verification work: confirm that the
independent implementation faithfully reconstructs the model, basis, boundary
conditions and observables; assess precision, tolerances and representative
size/parameter coverage; and include branch boundaries, degeneracies or other
exceptional cases. It is not a charge for the difficulty of discovering the
exact solution. A pinned exact identity or recurrence that removes these
coverage judgments can still score 0.

## Boundary examples

| Problem contract | Score | Reason |
|---|---:|---|
| Prove theorem T in ordinary mathematical prose | 10 | The essential claim cannot be decomposed into independently checkable units |
| Submit a Lean 4 proof of theorem T, statement pinned by the contract | 0 | Kernel acceptance is M and specification fidelity is trivial |
| Find an exact global optimum, with no certificate format | 7 | Global optimality needs a substantial derivation review |
| Find the optimum and submit the requested replayable exact upper-bound certificate | 0 | Matching lower and upper bounds are certificate and replay checks |
| Give one finite counterexample | 0 | The witness itself settles the universal finite claim |
| Give a quantum many-body exact spectrum whose practical check is independent finite-size diagonalization over documented generic and exceptional parameters | 2 | Numerical replay is bounded, but model fidelity, tolerances, coverage, branches and degeneracies leave a few local review units |
| Prove or refute a property of all finite-dimensional bipartite states; a refutation needs one exhibited state and measurement | 1 | The cheapest branch is checking the witness, a certificate check; constructing it is the solver's burden |
| Refute a uniform epsilon-delta claim with an infinite family and tail argument | 6 | The limiting construction and quantifiers are a connected derivation |
| Write code and compare with fixed experimental observations | 0 | Replaying the declared comparison is R |
| Give an algorithm and prove a worst-case complexity theorem | 8 | Running the code does not establish the theorem; the proof is a long chain |
| Construct A and prove no B exists | 8 | A is a certificate check, but nonexistence is a separate universal derivation |
| Explain robustness across all regimes from a finite benchmark | 9 | Generalization and scientific interpretation remain holistic residual |
| Verify that a pinned Lean statement faithfully encodes the informal problem | 2 | Statement comparison is one local, standard derivation unit |
| Confirm a finite-dimensional relaxation's KKT certificate plus a short duality argument | 1 | The certificate is C; the duality step is a single local check |
| Check that a submitted reduction from problem A to known-solved B is valid, then apply B's checker | 3 | The reduction check is a few independent local units before M applies |

## Pipeline rule

Triage records:

- `verification_difficulty`;
- `verification_difficulty_rationale`;
- the expected final result;
- importance and optional CI.

A campaign sets `limits.max_verification_difficulty`. The default is 3. Every
high- or medium-importance candidate proceeds to later-literature Research,
regardless of score. After Research and Problem Review, the limit controls
which audited problems are published. Setting the limit to 0 publishes only
candidates with no structural residual.

The Research Agent re-scores the surviving open core after the literature
audit. The Problem Reviewer checks that the score is supported and that any
claimed CI is operational. The score is used directly for ranking; no parallel
artifact taxonomy or binary review-scope label is needed.

The score and CI status are two layers: the score is the structural residual,
fixed by the contract; CI status is the operational delegation progress on
the same problem and may improve without the score changing.

The executable examples live in
`tests/fixtures/verification_difficulty_cases.json`.
