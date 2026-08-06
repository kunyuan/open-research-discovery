# Later-resolution audit

Legacy v1 reference — retained for schema-v1 campaigns; v2 topic campaigns follow the prompts and rank-open-problems skill.

An LKM `open_question` records the source paper's state at publication time. It
does not establish the current state.

## Required evidence

Record:

- original publication date;
- exact canonical formulation, notation, population, and parameter regime;
- author, theorem, conjecture, claim, method, benchmark, and terminology aliases;
- all query strings and ranking modes;
- `checked_at` and `checked_through`;
- relevant later papers with DOI, arXiv ID, paper ID, node ID, date, and exact
  relation to the problem;
- the surviving open core.
- a post-progress assessment whenever later work materially changes the
  baseline.

## Search sequence

1. Search the canonical formulation using comprehensive ranking.
2. Repeat using recent ranking.
3. Search exact theorem, conjecture, claim, method, and benchmark names lexically.
4. Search solution terms: proof, solved, counterexample, refuted.
5. Search partial-progress terms: improved bound, exact value, special case.
6. Search important aliases and formula fragments.
7. Inspect citations and paper graphs for plausible later results.
8. Use external current literature search when LKM coverage does not show how
   the same research core is treated by later work.
9. Follow citations forward and classify each relevant paper's relation as
   closure, refutation, special case, improved bound, reformulation, or
   adjacent-only.

## Status rules

- `resolved`: a later result proves the full canonical question.
- `refuted`: a later result disproves the conjectured statement.
- `partially_resolved`: later work settles cases or changes the best bound, but
  a precise nonempty core remains.
- `still_open`: the reconstructed later-literature chain leaves a precise
  nonempty canonical core and no credible closure result survives review.
  A literal recent sentence saying "remains open" is strong evidence but is
  not required. Pair this state with `likely_open` and limited confidence when
  the evidence is systematic but indirect.
- `uncertain`: evidence is incomplete or contradictory, or the statement is
  not precise and source-grounded enough to audit. Do not use `uncertain`
  solely because no later paper literally repeats that the problem is open.

Never translate "no result found" by itself into `still_open`. Record an
operational conclusion and confidence:

- `confirmed_open`: later work directly tracks the same surviving core;
- `likely_open`: coherent citation/topic coverage supports openness without a
  literal later restatement;
- `needs_reformulation`: the current statement lacks source provenance,
  quantifiers, definitions, or an acceptance predicate;
- `resolved` or `refuted`: decisive closure evidence exists.

## Major-progress state transition

Treat a new theorem, counterexample, sharp bound, classification, algorithm,
dataset, benchmark, replication, or decisive experimental result that
materially changes the target as major progress.

1. State its effect as `narrows`, `resolves`, `refutes`, or `reframes`.
2. Rewrite the surviving core using the new best result as the baseline.
3. Reassess the surviving core's importance.
4. Reassess verification difficulty from 0 to 10.
5. Choose exactly one action:
   - `continue`: the original target is essentially unchanged;
   - `rewrite-core`: keep the repo but replace the target with its important
     residual core;
   - `new-derived-problem`: preserve the original and create a linked repo for
     a materially different descendant;
   - `stop`: no meaningful, acceptably verifiable open core survives.

The post-progress question does not inherit the original importance,
verification difficulty, CI status, or solver priority. Record child IDs in the
original repo's `derived_problem_ids`, and cite the parent ID in each derived
repo's scope and evidence so later agents can reconstruct the lineage.
