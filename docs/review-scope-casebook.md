# Review-scope decision casebook

These abstract examples guide an LLM's semantic judgment. They are not an
artifact taxonomy and are not executable rules.

## The single test

Keep the final submitted result, frozen problem, declared checker, and frozen
reference data. Hide the solver's search log, chain of thought, and narrative.

If an independent LLM or checker can basically decide correctness, label the
route `result-only`. If it must also inspect a derivation outside the submitted
result, use `result-and-derivation`. If substantial tacit or specialist
judgment remains, use `expert-intensive`.

## Ordinary proof versus requested formal proof

- “Prove theorem T for every admissible parameter.” An ordinary written proof
  normally requires derivation review. Do not assume the solver will submit
  Lean: `result-and-derivation`.
- “Submit a Lean 4 proof of theorem T checked by the pinned kernel.” The Lean
  program is the requested final result, so kernel checking can be
  `result-only`.

The difference comes from the original answer contract, not from a fixed type
assigned by the pipeline.

## Positive patterns

### Finite counterexample

A finite graph, code, channel, or exact matrix pair can be `result-only` when
the reviewer checks every hypothesis and recomputes the strict violation. It
refutes the scoped conjecture; it does not prove a replacement theorem.

### Explicit exact solution

An exact solution can be `result-only` for existence in the declared regime
when substitution checks the equations, initial and boundary conditions,
domain, and singularities. It does not automatically establish uniqueness,
stability, completeness, or a general classification.

### Replayable optimum certificate

An attaining construction plus an independently replayable upper-bound
certificate can be `result-only` when both bounds meet exactly.

### First-principles explanation of experiment

A frozen model can be `result-only` for a scoped agreement claim when code,
inputs, observables, uncertainty treatment, and tolerances let the reviewer
recompute the comparison. A broader causal or mechanism claim may still need
expert judgment.

## Negative and boundary patterns

### Algorithm plus general guarantee

Running code establishes behavior on checked inputs. If the question also asks
for general correctness, asymptotic complexity, convergence, or a uniform
resource bound and these are not part of an executable requested result,
review is `result-and-derivation`.

### Object plus nonexistence

The object may be directly checkable, but “no object of another class exists”
is a separate universal claim. The combined route is not automatically
`result-only`.

### Finite numerics for an all-time or continuum claim

Samples or discretized eigenvalues do not by themselves establish an all-time
bound, continuum limit, or uniform PDE statement. The missing convergence or
tail argument requires derivation review.

## Benchmark asset

`tests/fixtures/review_scope_cases.json` stores source statement, proposed
result, expected scope, CI expectation, and rationale. Tests validate fixture
integrity only. Semantic accuracy belongs to blind agent evaluation and
adjudication, not a deterministic Python classifier.
