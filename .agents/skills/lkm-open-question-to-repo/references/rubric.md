# Candidate rubric

Use this rubric twice: first on the source-paper question before the expensive
later-literature audit, and again on the surviving or derived question whenever
the audit finds major progress. Never inherit the first score mechanically.

## Phase 1: intrinsic triage before status audit

### 1. Canonical candidate

- Confirm dedicated `::open_question` provenance.
- Merge duplicate and equivalent nodes.
- State the source-era question precisely enough to identify an answer artifact.

### 2. Scientific importance

Require evidence for at least one:

- improvement of a recognized bound or record;
- correction of an actively used conjecture;
- removal of a named theoretical or algorithmic bottleneck;
- a new parameterized construction, classification, or algorithm;
- resolution of a dependency shared by later results.

Generic statements such as "interesting" or retrieval rank are insufficient.

### 3. Verification profile

Verification ease is a routing label, not an absolute admission gate. Keep
scientifically worthwhile problems at every level, but never leave the level
implicit.

Assign exactly one mode:

- `machine-checkable`: a small deterministic program or trusted proof kernel
  can accept or reject the submitted artifact;
- `llm-reviewable`: an independent LLM can check the whole answer from a
  bounded local context and an explicit checklist, without a new literature
  search or deep unstated domain judgment;
- `hybrid`: deterministic checks cover finite computations while a short,
  explicit reasoning checklist covers the remainder;
- `expert-review`: acceptance needs long proof review, substantial tacit
  expertise, experimental interpretation, infinite-limit reasoning, novelty
  judgment, or expert taste;
- `unclassified`: the acceptance protocol is not yet understood.

Also assign `ease` as `easy`, `moderate`, or `hard`, and write the exact
protocol. A protocol may be:

- checking a finite object, dataset, measurement, or model against assumptions
  and conclusion;
- comparing a construction with a cited numeric baseline;
- running correctness tests, reproducibility checks, and a sealed benchmark;
- replaying a SAT, Lean, SOS, LP, or interval certificate;
- asking an LLM to follow a finite lemma checklist and verify a short
  derivation against definitions included in the repository.

An LLM protocol is acceptable only when the required context and checklist are
bounded and explicit. "Ask an LLM whether this proof looks right" is
`unclassified`, not `llm-reviewable`.

### 4. Reviewer-agent and CI contract

For every retained problem, record:

- `reviewer_contract.scope`: `result-only`, `result-and-derivation`,
  `expert-intensive`, or `unclassified`;
- the ordered acceptance checklist and required structured verdict;
- the estimated reviewer time and what evidence is admissible;
- `ci_contract.status`: `implemented`, `partial`, `pseudocode`,
  `reviewer-only`, or `blocked`;
- executable workflow/driver paths, problem-specific pseudocode, runner
  assumptions, estimated runtime, and a hard timeout.

Use `result-only` only when an independently parsed finite witness,
construction, or certificate decides the claim. Use
`result-and-derivation` when computations can be replayed but a proof,
complexity argument, limit, or uniform-family step remains. Use
`expert-intensive` when correctness depends on a long proof or substantial
tacit judgment.

CI must report its boundary honestly. Schema validation and unit tests may pass
while no substantive checker exists; that state is `pseudocode`, not
`implemented`, and must not authorize automatic acceptance. It may still
authorize research dispatch when the pseudocode is problem-specific and the
review scope is result-only.

### 5. Audit-priority decision

Prioritize the costly later-resolution audit when:

- importance has concrete evidence; and
- verification is `easy`, or the expected scientific value justifies a
  `moderate` or `hard` review path.

Retain lower-priority candidates with their scores and reason. Triage is a
funnel, not a claim that the source-era question is still open.

## Phase 2: current-status audit

Only after intrinsic triage, run the systematic later-literature audit. Assign
`still_open`, `partially_resolved`, `resolved`, `refuted`, or `uncertain`.

If there is major progress, formulate the exact surviving core before deciding
whether to continue.

## Phase 3: post-progress retriage

Run the importance and verification-profile sections again on the rewritten
core. Record whether progress:

- leaves the original target essentially unchanged;
- narrows it to a still-important residual problem;
- reframes it into a distinct derived problem;
- resolves or refutes it; or
- leaves only a low-value or poorly verifiable remainder.

Create a linked derived repo only when the research object, population, regime,
assumptions, or success condition have materially changed. Do not manufacture a
derived problem merely to keep a research line alive.

## Ranking procedure

Use `$rank-open-problems`. The worthiness and queue order of a problem depend
only on:

1. concrete scientific importance;
2. whether acceptance is result-only, result-and-derivation, or
   expert-intensive;
3. whether substantive CI, a specified checker, or a bounded LLM protocol can
   perform the review;
4. expected verification runtime and its hard resource ceiling.

Do not include searchability, feedback density, candidate-generation cost,
expected solve time, search compute, or probability of success. These may help
choose a solver after dispatch, but they do not make a problem more or less
worth attempting. Do not collapse the four dimensions into an opaque weighted
score; preserve the labels and use the lexicographic lanes defined by the
ranking skill. Stored priority and route fields are outputs or historical
annotations, not inputs to the new ranking.

## Repository readiness

- `research-ready`: current-open and important, with result-only review and an
  implemented, partial, or problem-specific pseudocode checker, or a concrete
  bounded LLM protocol. Checker implementation is not an admission gate.
- `verifier-blocked`: current-open and worthwhile, but no credible acceptance
  protocol is yet specified.
- Problems labeled `expert-review` stay in the research corpus and
  manual-review queue; do not silently dispatch them as easily verified
  `research-ready` problems.
- `uncertain`: later-resolution evidence is insufficient.
- `resolved-externally` or `refuted-externally`: keep for provenance, exclude
  from the solving queue.
