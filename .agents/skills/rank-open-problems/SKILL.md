---
name: rank-open-problems
description: Rank cross-disciplinary open research problems using only scientific importance, whether an independent reviewer can validate the submitted result without reconstructing the solve process, whether the acceptance protocol can run in CI or a bounded LLM review, and verification latency. Use when prioritizing mathematical, physical, computational, experimental, or data-driven problem pools; choosing which verifier to implement next; comparing machine-checkable and LLM-reviewable questions; or revising a ranking after a literature-status audit.
---

# Rank Open Problems

Rank problems for an automated discovery pipeline. Measure the value and cost
of validating an answer, not the difficulty of finding one.

## Hard boundary

Use exactly four intrinsic dimensions:

1. scientific importance;
2. reviewer scope;
3. CI or bounded-review feasibility;
4. verification latency and resource ceiling.

Do not rank on searchability, candidate-space size, feedback density, expected
solve time, search compute, probability of success, available mutations, or
how easy the problem looks to an LLM. These may guide a solver after dispatch,
but must not decide whether the problem is worth attempting.

Treat current-open evidence as a separate eligibility label. Do not inflate or
deflate intrinsic merit merely because the literature audit is easier or more
certain.

Treat stored `audit_priority`, `post_audit_priority`, and `route` values as
historical annotations or outputs, never as ranking inputs. Otherwise an old
ranking silently reproduces itself.

## Workflow

1. Rank the exact current target. If later work made major progress, first
   rewrite the surviving core and reassess it from scratch.
2. Record importance with concrete consequences. Use `high`, `medium`, `low`,
   or `unassessed`.
3. Record reviewer scope:
   - `result-only`: an independently parsed finite result, witness,
     construction, certificate, or bounded answer checklist decides acceptance;
   - `result-and-derivation`: the result can be replayed, but a proof,
     complexity argument, limit, or uniform-family step must also be checked;
   - `expert-intensive`: acceptance requires a long proof, substantial tacit
     judgment, novelty judgment, or a new literature search;
   - `unclassified`: the review boundary is not yet explicit.
4. Record verification mode as `machine-checkable`, `llm-reviewable`,
   `hybrid`, `expert-review`, or `unclassified`. A simple LLM check counts only
   when all context is local, the checklist is bounded, and the verdict format
   is explicit.
5. Record automation state:
   - `implemented`: the substantive acceptance predicate runs now;
   - `partial`: a deterministic stage runs, but declared checks remain;
   - `pseudocode`: the checker is implementable and specified, but not runnable;
   - `reviewer-only`: a bounded reviewer protocol exists without executable CI;
   - `blocked`: no operational acceptance path is known.
   Treat `implemented`, `partial`, `pseudocode`, and a bounded LLM protocol as
   equally sufficient for research admission. Implementation state is an
   operational label, not a worthiness criterion.
6. Record both the expected runtime and a hard timeout. Classify the timeout
   ceiling as `fast` (at most 10 minutes), `moderate` (at most 30 minutes),
   `slow` (at most 120 minutes), `very-slow` (over 120 minutes), or `unknown`.
7. Label the later-literature conclusion independently as `confirmed_open`,
   `likely_open`, `needs_reformulation`, `resolved`, `refuted`, or
   `unclassified`.

## Default ranking lanes

Assign every problem a visible lane. Do not silently discard lower-ranked
items.

1. `research-ready`: important, current-open, result-only, and CI is
   implemented, partial, or specified by problem-specific pseudocode; a
   bounded LLM review protocol also qualifies. The checker does not need to be
   implemented before research starts.
2. `verifier-blocked`: important and result-only, but no acceptable runnable or
   bounded review path exists yet.
3. `derivation-or-expert`: important, but review needs derivation or expert
   judgment.
4. `status-check`: current openness is uncertain or the target needs
   reformulation.
5. `low-significance`: importance is low or unassessed.
6. `closed`: later work resolved or refuted the target.

Within a lane, order by importance, reviewer scope, timeout class, current-open
confidence, then stable problem ID. Do not rank an implemented checker above a
specified checker merely because it is already implemented. This is a
transparent lexicographic policy, not a weighted score. Always show the
component labels so a user can override a tradeoff without reverse-engineering
a scalar.

For the verifier-development queue, select research-ready problems whose
automation state is `partial` or `pseudocode`, and order by importance, then
partial before pseudocode, then shorter timeout. For research dispatch, select
all `research-ready` problems. A missing implementation delays automatic final
acceptance, not the start of research. Keep `likely_open` visibly labelled and
refresh its audit before claiming novelty.

## Required output

Return a table with:

```text
rank, id, lane, importance, open-status, reviewer-scope,
verification-mode, CI-state, expected-runtime, timeout-class, rationale
```

State why the top item is above the next item using only the declared
dimensions. If any required field is unknown, label it; do not impute it from
the perceived difficulty of the research problem.

## Repository commands

Point the discovery scripts at the companion pool catalog:

```bash
uv run python scripts/rank_problem_pool.py \
  --catalog ../open-research-problem-pool/pool/catalog.jsonl
uv run python scripts/rank_problem_pool.py \
  --catalog ../open-research-problem-pool/pool/catalog.jsonl \
  --lane research-ready
uv run python scripts/rank_problem_pool.py \
  --catalog ../open-research-problem-pool/pool/catalog.jsonl \
  --queue verifier
uv run python scripts/rank_problem_pool.py \
  --catalog ../open-research-problem-pool/pool/catalog.jsonl \
  --domain quantum --json
```
