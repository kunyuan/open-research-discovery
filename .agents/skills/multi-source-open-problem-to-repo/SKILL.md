---
name: multi-source-open-problem-to-repo
description: Build source-faithful, currently open, independently verifiable research problems from one or more topics using dedicated LKM open questions plus contextual LKM, web, book, and user-reference search; compile all concrete problems under one topic into one README-first repository.
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
question open. Keep `explicit_open_question` false and let later-literature
research establish current status.

## Context fidelity

- Read enough of the source to resolve definitions, scope, assumptions,
  population or regime, observables, and the nature of the limitation.
- Never promote a motivation sentence, caveat, or adjacent result into a
  universal conjecture.
- Never copy a sentence while discarding context that changes its meaning.
- Preserve exact excerpts separately from summaries and inferences.
- If the available material is too thin, keep the item as a search lead or
  discard it; do not fabricate the missing contract.

## Canonicalization and decomposition

Merge equivalent formulations, but do not merge merely related problems.
Treat a large theme as a container, not automatically as one problem. A final
problem must have one independently reviewable target. If a broad program does
not have a clear acceptance standard, split it into meaningful subproblems that
preserve the original scientific intent. Do not create arbitrary finite proxies
or thresholds merely because they are easy to test.

For each atomic candidate record:

- the parent topic and theme;
- the canonical statement and aliases;
- candidate-specific source excerpts and context;
- descriptive answer types;
- a preliminary verification plan;
- why the decomposition is faithful.

## Triage and current-status research

Apply `$rank-open-problems` before and after the literature audit.

- Assign scientific significance from 0 to 10 and explain what changes if the
  problem is solved or materially advanced.
- Record answer types without restricting admissibility or choosing a method.
- Record verification difficulty from 0 to 10, but never apply a publication
  threshold.
- Require `verification_clarity: clear`. Otherwise decompose or withhold the
  candidate.
- Materialize triage-proposed subproblems as child candidates and triage them
  again within the configured decomposition depth. Do not send an unclear
  parent theme to the expensive status audit as if research could make its
  acceptance contract unambiguous.
- Search later literature for closure, refutation, special cases, improved
  bounds, reformulations, and continuing treatment of the same core.
- Absence of a found solution is not proof of openness. Use confidence-labelled
  `likely_open` or `uncertain` when appropriate.
- A new argument created during discovery is not literature evidence of
  resolution.

## Verification contract

The standard must say:

1. what claim or artifact is submitted;
2. the exact scope, assumptions, data, model, or protocol;
3. which checks an independent reviewer performs;
4. what result passes or fails;
5. what nearby claims remain outside scope.

The accepted answer may be a proof, counterexample, construction, simulation,
experiment, measurement, dataset, benchmark result, or another scientifically
appropriate form. CI is optional. Verification difficulty describes reviewer
burden; neither it nor answer type controls publication.

## Topic repository

Compile all accepted concrete problems under one topic into one README-first
repository. Give every problem a stable ORP ID and include, for each:

- origin and sufficient context;
- the precise research question and scope;
- scientific significance score and analysis;
- current research progress and surviving open core;
- expected result and descriptive answer types;
- explicit verification standard, checklist, boundary, and difficulty score;
- source trail and references.

Keep raw retrieval responses and structured records in campaign/pool storage,
not in the generated repository. Add code, data, or CI only when a specific
problem's scientific acceptance contract requires it. Remote creation or push
still requires explicit user authorization.
