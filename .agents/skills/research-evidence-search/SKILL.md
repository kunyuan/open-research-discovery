---
name: research-evidence-search
description: Search scientific evidence across Bohrium LKM, the web, books, and user references for topic discovery, context reconstruction, current-status audits, and editing-review citation verification.
---

# Research Evidence Search

Use LKM, the web, books, and user references as complementary evidence sources.
Choose routes from the handles already available; do not impose a fixed order.

## Two distinct discovery products

1. A dedicated direct-LKM `data.papers[].open_questions` record is an explicit
   LKM open-question record. It is not automatically a verbatim or
   author-declared question from the paper; confirm that attribution against
   inspected paper text before saying the authors posed it.
2. LKM/web/book/reference search may yield a possible research problem even
   when the source did not label it open. Such a lead requires a verbatim
   excerpt, surrounding context, source intent, and a source-faithful
   derivation rationale.

Never present a search-derived lead as an author-declared open question. Never
infer a stronger claim from an ordinary question, motivation, limitation, or
isolated sentence.

## Search and evidence record

Search by topic, title, author, DOI, arXiv ID, LKM paper ID, theorem, method,
benchmark, formula, or citation. Feed identifiers and aliases between web and
LKM routes. Prefer primary papers and authoritative repositories.

Read [references/sources.md](references/sources.md) before assigning evidence
strength. Read [references/gaia-lkm-cli.md](references/gaia-lkm-cli.md) before
calling LKM through Gaia.

For exploratory retrieval, use Gaia CLI with claims and questions as search
leads:

```bash
gaia search lkm knowledge "<query>" \
  --scopes claim --scopes question \
  --retrieval-mode hybrid \
  --include-paper-enrich \
  --sort-by comprehensive \
  --no-hint
```

Use `gaia search lkm reasoning`, `nodes`, or `package` when the task needs a
reasoning chain, exact node, or known paper package. Gaia's question scope is
mixed: it may contain ordinary problem, subproblem, question, and dedicated
open-question nodes. Those results are leads only. A claim of explicit source
openness still requires confirmation through the containing paper's direct
`papers/graph` response.

The direct graph field confirms LKM route provenance, not author-level
attribution. During the current-status audit, compare the extracted question
with accessible paper text. If it is absent, synthesized, or changes a stated
assumption, retain the retrieval evidence but mark the candidate as needing
reformulation or source re-attribution.

If the direct API returns a nonzero business code, preserve the failed response
and trace ID and retry the paper by another available identifier in this order:
paper ID, DOI, exact title. Do not reinterpret an API failure as zero open
questions and do not fall back to an ordinary question node.

For every load-bearing item record:

- title, date, identifier, URL, and locator;
- the route or query that found it;
- the exact relation to the candidate problem;
- content level: `metadata`, `abstract`, `compressed_claim`,
  `reasoning_chain`, `partial_full_text`, or `full_text`;
- whether support is direct or inferred;
- missing context, conflicts, and uncertainty.

Do not describe compressed claims as full text or retrieval score as
confidence. Do not copy restricted full text.

## Current-status audit

Search the canonical statement and aliases with `solved`, `proof`,
`counterexample`, `refuted`, `improved bound`, `special case`, `remaining
open`, and related field terms. Follow forward citations where possible.
Classify later work by whether it closes, refutes, narrows, improves,
reformulates, or merely neighbors the same core.

Absence of a found solution is not evidence of openness. State the exact
surviving core and the limits of the search in `previous_progress`. Use the
`open` audit outcome only after a systematic same-core search, forward
citation reconstruction, and explicit separation of plausible adjacent
results; use `uncertain` for materially incomplete, conflicting, or
identity-ambiguous evidence; use `resolved` or `refuted` only with direct
external research evidence.

Every cited work goes into `references` as one string containing an
externally verifiable identifier (DOI preferred, arXiv ID, or ISBN for books)
and a URL. Never put an LKM internal node ID in a reference string; keep LKM
provenance as a parenthetical note. Every work cited by author name or paper
title in background, problem_statement, or previous_progress must appear in
`references`.

This is evidence retrieval, not a solver run. New proofs, computations, or
scientific explanations created by the agent cannot establish literature
closure. Keep credentials private and keep pool mutation under the
deterministic pipeline.

Books and user references require the same evidence discipline. Record edition
or stable identifier and page/chapter/section locator. A table-of-contents item
is a retrieval lead, not enough context for selection. Do not copy
restricted full text; retain the minimum exact excerpt and a source-grounded
context summary needed to preserve meaning.
