# Repository Instructions

Work from the research-problem lifecycle, not isolated search hits.

`discovery campaign` is the default problem-generation workflow. Benchmark
construction and evaluation are separate and run only when explicitly requested.

1. Accept one or more user topics. Schema-v2 campaigns may use both
   `lkm_open_questions` and `topic_search` source routes.
2. Preserve raw direct-LKM responses and the provenance of every LKM, web, book,
   dataset, or user-reference lead. Never expose credentials or copy restricted
   full text.
3. A dedicated `data.papers[].open_questions` record is an explicit source
   question. LKM/web/book/reference search may also produce a possible problem,
   but only with a verbatim excerpt, surrounding context, source intent, and a
   source-faithful derivation rationale.
4. Never infer a stronger, broader, more universal, or differently scoped claim
   from an isolated sentence. If context is insufficient, keep the lead out.
5. Canonicalize equivalent formulations and split broad programs into concrete
   independently reviewable subproblems before repository compilation. A prompt
   such as “determine the Hubbard-model phase diagram” is a theme, not a final
   problem, until regime, observables, target, and acceptance conditions are pinned.
6. Every final problem requires `verification_clarity: clear` and a concrete
   verification standard stating what is submitted, what is checked, under which
   scope or protocol, and what passes. If this cannot be stated faithfully,
   decompose the problem; if decomposition fails, do not publish it.
7. Always record verification difficulty from 0 to 10 as independent-review
   burden. Schema-v2 campaigns never use that score as a publication threshold.
   CI availability and answer type are also never admission gates.
8. Record all naturally acceptable answer types—proof, counterexample,
   construction, simulation, experiment, measurement, dataset, benchmark result,
   or another form—without prescribing a solving route.
9. Record scientific significance from 0 to 10 and explain specifically which
   knowledge, capability, bound, mechanism, or decision would change.
10. Audit later literature for every high- or medium-importance candidate. Search
    LKM and the web adaptively, distinguish source content from inference, and use
    `likely_open` or `uncertain` when the evidence does not justify certainty.
11. Resolution or refutation must be supported by external research evidence,
    never a new proof or computation invented by the discovery agent.
12. One schema-v2 topic compiles to one README-first repository containing all
    accepted concrete problems under that theme. Give each problem a stable ORP
    ID, provenance, origin and context, significance analysis, current progress,
    answer types, and verification standard in the repository README.
13. Keep structured records, raw evidence, and pool views outside generated
    problem repositories. Generated repositories remain README-first; add code,
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
