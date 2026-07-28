# Solution Review-scope decision casebook

These abstract examples guide the Problem Reviewer when it predicts what a
future Solution Reviewer will need after a solver submits a result. They are
not an artifact taxonomy, executable rules, or a checklist for reviewing
whether the problem itself is worth admitting.

## The single test

Ask one question: without reviewing the solver's reasoning process, can a
future independent Solution Reviewer basically decide correctness from only
the final result naturally required by the original problem?

If yes, label the expected result `result-only`. If the Reviewer must inspect
a mathematical or scientific derivation, even one included in the submission,
use `result-and-derivation`. If substantial tacit or specialist judgment
remains, use `expert-intensive`.

## Ordinary proof versus requested formal proof

- “Prove theorem T for every admissible parameter.” An ordinary written proof
  normally requires derivation review. Do not assume the solver will submit
  Lean: `result-and-derivation`.
- “Submit a Lean 4 proof of theorem T checked by the pinned kernel.” The Lean
  program is the requested final result, so kernel checking can be
  `result-only`.

The difference comes from the original answer contract, not from a fixed type
assigned by the pipeline.

Apply the same rule to certificates. If the source asks only for an exact
optimum and permits an ordinary proof, do not add an SOS or primal-dual
certificate merely to obtain `result-only`. If the source explicitly requests
a replayable certificate, that certificate is the result.

## Positive patterns

### Finite counterexample

A finite graph, code, channel, or exact matrix pair can be `result-only` when
the Solution Reviewer checks every hypothesis and recomputes the strict
violation. It refutes the scoped conjecture; it does not prove a replacement
theorem.

### Explicit exact solution

An exact solution can be `result-only` for existence in the declared regime
when substitution checks the equations, initial and boundary conditions,
domain, and singularities. It does not automatically establish uniqueness,
stability, completeness, or a general classification.

A parameterized exact solution is not automatically a proof question. For
example, a complete closed-form spectrum for an arbitrary-size matrix family
can be `result-only` when the submitted formula can be substituted into the
defining recurrence or characteristic polynomial and its degree,
multiplicities, and exceptional cases directly establish completeness. The
Reviewer checks the final formula and identities, not the solver's derivation.

### Replayable optimum certificate

An attaining construction plus an independently replayable upper-bound
certificate can be `result-only` when the original answer contract requests
that certificate and both bounds meet exactly. An exact optimum supported by
an ordinary proof remains `result-and-derivation`.

### First-principles explanation of experiment

A frozen model can be `result-only` for a scoped agreement claim when code,
inputs, observables, uncertainty treatment, and tolerances let the Solution
Reviewer recompute the comparison. A broader causal or mechanism claim may
still need expert judgment.

### Executable comparison

Code can itself be the final result when the source naturally asks for an
executable method whose success is the outcome of a defined comparison. For
example, a decoder that must reduce logical error relative to a named baseline
while satisfying a stated throughput constraint can be `result-only` when an
independent Reviewer can replay the fixed noise model, metrics, resource
budget, repetitions, and acceptance inequalities.

The replay bundle normally includes the program, dependency lock, inputs or
instance generator, source-faithful baseline and configuration, random seeds
or statistical rule, and machine-readable outputs. These are not new
screening fields. Together they are the submitted result whose comparison is
replayed.

The source need not have written down every software version, seed, repetition
count, or numerical tolerance. Those are routine reproducibility details that
the final result may freeze. The scientific target, baseline, applicable
regime, and comparison axes must already be source-grounded; changing one of
those to obtain a favorable result is not routine operationalization.

## Negative and boundary patterns

### Algorithm plus general guarantee

Running code establishes behavior on checked inputs. If the question also asks
for general correctness, asymptotic complexity, convergence, or a uniform
resource bound and these are not part of an executable requested result,
review is `result-and-derivation`.

### Invented benchmark

A benchmark chosen after reading the source cannot narrow “robust across all
regimes” into “wins on these instances.” If the source does not naturally fix
enough of the comparison for replay to decide the claim, use
`result-and-derivation`, `expert-intensive`, or `unclassified`; do not invent
metrics or thresholds to manufacture a result-only route.

### Object plus nonexistence

The object may be directly checkable, but “no object of another class exists”
is a separate universal claim. The combined result is not automatically
`result-only`.

### Finite numerics for an all-time or continuum claim

Samples or discretized eigenvalues do not by themselves establish an all-time
bound, continuum limit, or uniform PDE statement. The missing convergence or
tail argument requires derivation review.

## Benchmark asset

`tests/fixtures/solution_review_scope_cases.json` stores source statement,
proposed result, expected Solution Review scope, CI expectation, and rationale.
Tests validate fixture integrity only. Semantic accuracy belongs to blind agent
evaluation and adjudication, not a deterministic Python classifier.
