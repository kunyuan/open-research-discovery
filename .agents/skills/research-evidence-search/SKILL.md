---
name: research-evidence-search
description: Search for scientific papers and evidence across Bohrium LKM and the web without imposing a fixed source order. Use when discovering candidate papers, reconstructing later progress on a research question, checking whether a result closes or narrows a problem, or collecting source-grounded evidence for a surviving open core. This skill is for evidence retrieval and synthesis; it must not infer source open questions outside the dedicated LKM paper-graph open_questions field.
---

# Research Evidence Search

Use LKM and the web as complementary evidence sources. Choose routes from the
information already available; do not follow a fixed LKM-first or web-first
sequence.

## Search routes

1. Start from any available handle: a scientific question, title, author, DOI,
   arXiv ID, LKM paper ID, theorem name, method, benchmark, formula fragment,
   or citation.
2. Search LKM directly when the query is conceptual or when paper identifiers
   are already known.
3. Search the web when it is the faster route to a DOI, title, abstract,
   citation trail, terminology alias, or accessible paper text.
4. Feed identifiers and aliases found on the web back into LKM.
5. Use the web to inspect an abstract or accessible original text when LKM's
   compressed representation is incomplete or ambiguous.
6. Iterate until the evidence supports the requested judgment or the remaining
   uncertainty is explicit.

Read [references/sources.md](references/sources.md) before assigning evidence
strength. Read [references/gaia-lkm-cli.md](references/gaia-lkm-cli.md) before
calling LKM through Gaia.

## LKM access

Use Gaia CLI for exploratory and later-literature retrieval:

```bash
gaia search lkm knowledge "<query>" \
  --scopes claim --scopes question \
  --retrieval-mode hybrid \
  --include-paper-enrich \
  --sort-by comprehensive \
  --no-hint
```

Use `gaia search lkm reasoning`, `nodes`, or `package` when the task needs
reasoning chains, exact node retrieval, or a known paper package. Treat
retrieval scores only as ranking signals.

The discovery pipeline has a separate deterministic ingestion boundary:
candidate papers are sent directly to
`POST https://open.bohrium.com/openapi/v1/lkm/papers/graph`, and only
`data.papers[].open_questions` may create source open-question records. Do not
replace that boundary with `gaia search lkm`, and do not infer source open
questions from ordinary question/problem/subproblem nodes.

Gaia's `--scopes question` is a mixed retrieval scope: its results can include
ordinary `problem`, `subproblem`, `question`, and dedicated `open_question`
nodes. Treat every such hit only as a lead to its containing paper. Even when
`provenance.representative_lcn.local_id` ends in `::open_question`, confirm the
record through that paper's direct `papers/graph` response before admitting
it.

If the direct API returns a nonzero business code such as paper-not-found, do
not reinterpret the failure as zero open questions and do not fall back to
ordinary Gaia question nodes. Preserve the failed response and `trace_id`,
retry the same paper using another available identifier in this order:
`paper_id`, DOI, exact title. If every identifier fails, mark the paper
unresolved in LKM and recall another LKM-indexed paper.

## Evidence record

For every load-bearing item record:

- title, authors when available, date, DOI/arXiv/paper/node identifier, and URL;
- the query or route that found it;
- the exact relation to the research question;
- one content-level label:
  `metadata`, `abstract`, `compressed_claim`, `reasoning_chain`,
  `partial_full_text`, or `full_text`;
- whether the statement is directly supported or inferred;
- conflicts, missing context, and unresolved ambiguity.

Never describe an LKM compressed claim or reasoning chain as full paper text.
Never describe a search ranking as confidence.

## Status research

When reconstructing later progress, search the canonical statement and its
aliases together with closure and progress terms such as `solved`, `proof`,
`counterexample`, `refuted`, `improved bound`, `special case`, `remaining
open`, and `open problem`. Follow citations forward where possible.

Classify relevant later work by what it does to the same core:

- closes or refutes it;
- settles a special case;
- improves a bound or benchmark;
- reframes the object, assumptions, or regime;
- provides adjacent evidence only.

Absence of a found solution is not evidence that the problem remains open.
State what the literature actually establishes, identify major progress, and
write the precise surviving core. A recent sentence literally saying "remains
open" is useful but not required when the later citation/topic chain makes the
status clear.

Use `still_open` for the best-supported object state when a systematic
same-core search, forward citation chain, and treatment of plausible adjacent
results leave a precise nonempty core with no credible closure. Pair it with
`likely_open` and medium or low confidence when the evidence is indirect.
Do not use `uncertain` merely because no recent paper literally repeats
"remains open"; reserve it for materially incomplete, conflicting, or
identity-ambiguous evidence.

## Boundaries

- Keep retrieval separate from scientific judgment and from pool mutation.
- In a discovery status audit, do not attempt a new proof, counterexample,
  construction, computation, or scientific explanation of the candidate.
  Resolution and major-progress claims must come from external research
  evidence. If an apparent elementary resolution is noticed, report it as a
  scope or identity concern without treating it as literature-backed closure.
- Do not create or edit problem-pool records.
- Do not expose access keys or authentication material.
- Do not copy restricted full text; preserve stable metadata and precise notes.
- Prefer primary papers and authoritative repositories over secondary
  summaries.
- If evidence is incomplete or contradictory, return the uncertainty instead
  of forcing a conclusion.
