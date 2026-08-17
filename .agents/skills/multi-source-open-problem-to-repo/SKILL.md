---
name: multi-source-open-problem-to-repo
description: Build source-faithful, currently open, independently verifiable research problems from one or more topics using dedicated LKM open questions plus contextual LKM, web, book, and user-reference search; compile each accepted problem into its own README-first solution repository.
---

# Multi-Source Open Problem to Repo

Turn one or more user topics into current, source-grounded research-problem
repositories. The workflow accepts diverse sources and diverse answer forms,
but never accepts an ambiguous verification boundary.

## Source routes

Use either or both routes per topic:

1. `lkm_open_questions`: discover candidate papers, call the direct
   `papers/graph` API, preserve the raw response and trace ID, and ingest only
   `data.papers[].open_questions` as dedicated LKM open-question records. Also
   inspect at least abstract-level material for the paper and retain a grounded
   context summary and source intent; the isolated open-question sentence is
   not the whole formulation contract. Do not call it author-declared or
   verbatim until the later audit confirms that attribution in the paper.
2. `topic_search`: search LKM and the web adaptively and inspect books or
   user-supplied references. Return possible problem leads only when the record
   contains a verbatim excerpt, enough surrounding context, the source author's
   intent, and a precise account of how the research question follows.

A topic-search lead is not evidence that the source explicitly called the
question open. Later-literature research establishes current status.

## Context fidelity

- Read enough of the source to resolve definitions, scope, assumptions,
  population or regime, observables, and the nature of the limitation.
- Never promote a motivation sentence, caveat, or adjacent result into a
  universal conjecture.
- Never copy a sentence while discarding context that changes its meaning.
- Preserve exact excerpts separately from summaries and inferences.
- If the available material is too thin, keep the item as a search lead or
  discard it; do not fabricate the missing contract.

## Selection and current-status research

Apply `$rank-open-problems` before and after the literature audit.

Selection runs once per topic over the topic's `memory.md`: merge equivalent
formulations, but do not merge merely related problems. Treat a large theme as
a container, not automatically as one problem. A final problem must have one
independently reviewable target. Do not create arbitrary finite proxies or
thresholds merely because they are easy to test. For each selected candidate
record the canonical statement, the per-source supporting excerpts, the
importance level, and a free-form assessment.

- Record answer types as `verification_contract` keys without restricting
  admissibility or choosing a method.
- Record verification difficulty from 0 to 10, but never apply a publication
  threshold.
- An unclear or too-general candidate is not decomposed into a queue: the
  Problem Reviewer rejects it and it stays archived in the run directory.
  Do not send a vague parent theme to the expensive status audit as if
  research could make its acceptance contract unambiguous — Selection should
  keep such a theme out of the important candidate set.
- Search later literature for closure, refutation, special cases, improved
  bounds, reformulations, and continuing treatment of the same core.
- Absence of a found solution is not proof of openness. Use the `uncertain`
  audit outcome when coverage is materially incomplete, conflicting, or
  identity-ambiguous.
- A new argument created during discovery is not literature evidence of
  resolution.
- The research audit returns a Problem Schema v1.0 record plus
  `audit_outcome`. Mechanical fields — identifiers, status, domain, topic,
  repository, schema_version — are injected by the pipeline during validation;
  never emit or choose them.

## Verification contract

Each `verification_contract` entry (one per answer type) must say:

1. what claim or artifact is submitted;
2. the exact scope, assumptions, data, model, or protocol;
3. which checks an independent reviewer performs;
4. what result passes or fails;
5. what nearby claims remain outside scope.

The accepted answer may be a proof, counterexample, construction, simulation,
experiment, measurement, dataset, benchmark result, or another scientifically
appropriate form. CI is optional (`ci_contract` per answer type). Verification
difficulty describes reviewer burden; neither it nor answer type controls
publication.

## Problem repositories

Each accepted problem compiles into its own README-first solution repository
with a stable ORP ID; `topic_id` is retained as grouping metadata. The README
has exactly these top-level sections:

1. Background;
2. Problem Statement;
3. Current Progress;
4. Scientific Significance;
5. Answer Types;
6. Verification Standard;
7. Suggested CI;
8. References.

Keep raw retrieval responses and structured records in campaign/pool storage,
not in the generated repository. Add code, data, or CI only when a specific
problem's scientific acceptance contract requires it. Remote creation or push
still requires explicit user authorization.
