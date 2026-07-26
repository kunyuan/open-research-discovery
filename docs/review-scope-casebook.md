# Review-scope decision casebook

This casebook records reusable screening lessons from the first
mathematics/physics/computational-science campaign. It contains abstracted
training examples, not raw corpus records, current-open judgments, benchmark
gold labels, or source-paper snapshots. Do not evaluate a model on a case it
has been trained with here.

## Decision primitive: load-bearing acceptance obligations

Choose one scientifically sufficient, source-grounded route. List every
load-bearing obligation needed to accept that route:

- `direct-artifact`: the declared final artifact directly decides the check;
- `source-requested-formal-proof`: the source explicitly requires a formal or
  machine-checkable proof/certificate, so the executable proof is the result;
- `derivation`: an ordinary proof, correctness, complexity, convergence,
  generality, uniqueness, or nonexistence argument remains;
- `expert-judgment`: tacit scientific interpretation or unbounded expert
  judgment remains.

The most demanding required obligation determines review scope:

```text
expert-judgment > derivation > direct-artifact/source-requested-formal-proof
expert-intensive   result-and-derivation        result-only
```

Verification mode and CI buildability remain separate axes.

## Metamorphic pair: ordinary proof versus requested formal proof

Keep theorem `T` fixed.

1. Source: “Prove theorem T for every admissible parameter.”
   The load-bearing obligation is `derivation`, even if a solver could choose
   Lean. Expected scope: `result-and-derivation`.
2. Source: “Submit a Lean 4 proof of theorem T checked by the pinned kernel.”
   The load-bearing obligation is `source-requested-formal-proof`. Expected
   scope: `result-only`.

The label changes because the source delivery contract changes, not because
Lean is intrinsically easier to check.

Any Lean/Coq/Isabelle deliverable must also declare
`uses_proof_assistant=true` and `artifact_type=formal-proof`. It cannot be
hidden under a generic `certificate` or `direct-artifact` label.

The deterministic layer does not pretend to understand the scientific prose.
Canonicalization proposes `formal_proof_requested` beside an exact excerpt;
the Reviewer audits that semantic judgment. Code then enforces provenance and
all downstream obligation/artifact/scope consistency. This keeps the
human-or-agent semantic boundary visible instead of replacing it with brittle
keyword matching.

## Reusable positive patterns

### Finite counterexample

A finite hypergraph, graph, code, channel, or pair of exact density matrices
may refute a universal conjecture. It is `result-only` when a checker parses
the object, checks every hypothesis, and recomputes a strict violation. The
scientific effect must be scoped as refutation; the artifact does not prove a
replacement theorem.

### Explicit exact solution

An exact physical or mathematical solution can be `result-only` for existence
in the declared regime when direct substitution checks the equations, initial
and boundary conditions, domain, and singularities. It does not by itself
establish uniqueness, stability, completeness, or a general classification.

### Exact optimum with a replayable certificate

An exact Bell value plus an attaining state/measurement and a noncommutative
SOS upper-bound certificate is `result-only`: the lower and upper bounds can be
replayed independently from the final artifacts.

### Source-requested machine certificate

A computation whose source question explicitly asks for a complete
machine-checked certificate is `result-only` when a pinned checker reconstructs
the obligations from frozen data and replays the certificate.

## Reusable boundary and negative patterns

### Algorithm plus general guarantee

Running an implementation establishes behavior on tested inputs. If the source
also asks for general correctness, worst-case complexity, convergence, or a
uniform resource bound, those are `derivation` obligations. The sufficient
route is `result-and-derivation`; code alone is not sufficient.

### Object plus nonexistence

An explicit manifold, kernel, code, or other object is directly checkable.
The claim that no object of another class exists is a universal
`derivation` obligation. The presence of one finite object does not make the
combined route `result-only`.

### Universal finite-sample optimum

Numerical optima for many instances do not establish a theorem over arbitrary
priors, spectra, adaptive strategies, or measurements. A converse and an
attaining construction remain load-bearing, usually making review
`expert-intensive`.

### Certified numerics with an all-time or continuum claim

Finite samples or discretized eigenvalues do not establish an all-time
semigroup bound, continuum limit, or uniform PDE statement. Certified
discretization, tail, rounding, and convergence arguments remain
`derivation` obligations.

## Regression assets

The executable policy is in
`src/open_research_discovery/review_policy.py`. The six-case regression matrix
is `tests/fixtures/review_scope_cases.json`; it covers the metamorphic formal
proof pair, finite counterexample, exact solution, algorithm plus complexity,
and object plus nonexistence. Unit tests require exact source provenance,
reject a hidden derivation under `result-only`, and reject an ordinary proof
relabelled as source-requested formalization.
