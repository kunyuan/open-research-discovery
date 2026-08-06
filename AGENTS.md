# Repository Instructions

Work from the research-problem lifecycle, not isolated search hits.

`discovery campaign` is the default problem-generation workflow. Benchmark
construction and evaluation are separate and run only when explicitly requested.

1. Accept one or more user topics. Schema-v2 campaigns may use both
   `lkm_open_questions` and `topic_search` source routes.
2. Preserve raw direct-LKM responses and the provenance of every LKM, web, book,
   dataset, or user-reference lead. Never expose credentials or copy restricted
   full text.
3. A dedicated `data.papers[].open_questions` record is an explicit LKM route
   record, not automatically a verbatim or author-declared paper question.
   Confirm author attribution during the paper audit. LKM/web/book/reference
   search may also produce a possible problem, but only with a verbatim excerpt,
   surrounding context, source intent, and a source-faithful derivation rationale.
4. Never infer a stronger, broader, more universal, or differently scoped claim
   from an isolated sentence. Equally, never narrow a source problem by adding a
   finite size, parameter window, model subclass, method, observable, or answer
   form merely to make verification easier. If context is insufficient, keep the
   lead out.
5. Canonicalize equivalent formulations source-first. Preserve the natural
   generality and quantifiers of the literature problem. Split only genuinely
   conjunctive questions along source-supported or literature-supported
   boundaries; a restricted special case is a derived problem, not a replacement
   for its parent. For a famous or named problem, align the title and statement
   with a primary or standard authoritative formulation. Never present an
   invented tractable variant as the famous problem itself.
6. Every final problem requires `verification_clarity: clear` and a concrete
   verification standard stating what is submitted, what is checked, and what
   passes for each natural answer type. Verification evaluates an answer to the
   problem statement; it must not redefine or artificially restrict that
   statement. If the conclusion has separately checkable components, expose them
   as review units while retaining the original problem. If a faithful pass/fail
   standard still cannot be stated, do not publish it — but never silently drop
   a literature-grounded question either: decompose it into subproblems and
   retain them in the persistent topic queue (`topic-queue.jsonl`) so a later
   campaign can pose them. `unverifiable` requires decomposition, not
   rejection.
7. Always record verification difficulty from 0 to 10 as independent-review
   burden. Schema-v2 campaigns never use that score as a publication threshold.
   CI availability and answer type are also never admission gates.
8. Record all naturally acceptable answer types—proof, counterexample,
   construction, simulation, experiment, measurement, dataset, benchmark result,
   or another form—without prescribing a solving route.
9. Record scientific significance from 0 to 10 and explain specifically which
   knowledge, capability, bound, mechanism, or decision would change.
10. Audit later literature for every clear, high- or medium-importance candidate
    selected within the configured per-topic audit budget. Search LKM and the web
    adaptively, distinguish source content from inference, and use `likely_open`
    or `uncertain` when the evidence does not justify certainty. A narrower
    surviving core is permitted only when later literature actually resolves the
    broader part; record that derivation explicitly.
11. Resolution or refutation must be supported by external research evidence,
    never a new proof or computation invented by the discovery agent.
12. Each accepted schema-v2 problem compiles to its own README-first solution
    repository. Topics remain grouping metadata, so several solution repositories
    may share one `topic_id`. Every README has exactly these top-level sections,
    in order: `Background`, `Problem Statement`, `Scientific Significance`,
    `Answer Types`, `Verification Standard`, `Current Progress`, and `References`.
13. Keep structured records, raw evidence, and pool views outside generated
    solution repositories. Generated repositories remain README-first; add code,
    data, or CI only when a specific scientific verification contract needs them.
14. The canonical README uses English headings and narrative plus GitLab math
    delimiters (`$...$` and `$$...$$`). Bibliographic titles and exact source
    excerpts may retain their source language. An optional Chinese README must
    be a faithful translation.
15. Agents return schema-validated artifacts. The deterministic pipeline owns
    identifiers, retries, compilation, pool synchronization, and ranking.
16. Before every agent retry, clear stale structured output. On timeout, terminate
    the whole process group so descendants cannot retain pipes.
17. Remote publication still requires explicit user authorization.

Use `uv run pytest` and `make check` before publishing changes.
