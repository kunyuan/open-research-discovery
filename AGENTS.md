# Repository Instructions

Work from the research-problem lifecycle, not isolated search hits.

`discovery campaign` is the default problem-generation workflow. Benchmark
construction and evaluation are separate and run only when explicitly requested.

1. Accept one or more user topics. Campaigns may use both
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
5. Selection merges equivalent formulations source-first. Preserve the natural
   generality and quantifiers of the literature problem. Split only genuinely
   conjunctive questions along source-supported or literature-supported
   boundaries; a restricted special case is a derived problem, not a replacement
   for its parent. For a famous or named problem, align the title and statement
   with a primary or standard authoritative formulation quoted from the source
   context. Never present an invented tractable variant as the famous problem
   itself.
6. Every final problem carries a `verification_contract` keyed by answer type:
   each entry states what is submitted, what is checked, and what passes for
   that answer type, plus an optional `ci_contract` for the mechanically
   executable part. Verification evaluates an answer to the problem statement;
   it must not redefine or artificially restrict that statement. If no faithful
   pass/fail contract can be stated, the Problem Reviewer rejects the candidate
   and it stays archived in the run directory — there is no decomposition
   queue and no cross-campaign re-issuance.
7. Always record verification difficulty from 0 to 10 (`verification_difficulty`
   score plus rationale) as independent-review burden. The score is never a
   publication threshold. CI availability and answer type are also never
   admission gates.
8. Record all naturally acceptable answer types—proof, counterexample,
   construction, simulation, experiment, measurement, dataset, benchmark result,
   or another form—as the keys of `verification_contract`, without prescribing
   a solving route.
9. Record affected-field significance as a high/medium/low level and explain
   specifically which knowledge, capability, bound, mechanism, or decision
   would change.
10. Audit later literature for every high- or medium-importance candidate
    selected within the configured per-topic audit budget. Search LKM and the
    web adaptively, distinguish source content from inference, and use
    `uncertain` when the evidence does not justify an `open` outcome. A narrower
    surviving core is permitted only when later literature actually resolves the
    broader part; record that derivation explicitly in `previous_progress`.
11. Resolution or refutation must be supported by external research evidence,
    never a new proof or computation invented by the discovery agent.
12. Each accepted problem compiles to its own README-first solution
    repository. Topics remain grouping metadata, so several solution repositories
    may share one `topic_id`. Every README has exactly these top-level sections,
    in order: `Background`, `Problem Statement`, `Current Progress`,
    `Scientific Significance`, `Answer Types`, `Verification Standard`,
    `Suggested CI`, and `References`.
13. Keep structured records, raw evidence, and pool views outside generated
    solution repositories. Generated repositories remain README-first; add code,
    data, or CI only when a specific scientific verification contract needs them.
14. The canonical README uses English headings and narrative plus GitLab math
    delimiters (`$...$` and `$$...$$`). Bibliographic titles and exact source
    excerpts may retain their source language. An optional Chinese README must
    be a faithful translation.
15. The pipeline is one-directional: Discovery → Selection → Research →
    Problem Review → Compile, with no revision or feedback loops. Context
    travels through pipeline-written `memory.md` files (one per topic, one per
    candidate); every agent prompt opens by reading it, and only the
    deterministic pipeline writes it. Every agent's world is a folder prepared
    for it: Discovery in the topic directory, Selection in a copied
    `selection-workdir/`, Research in the candidate directory, and the
    Problem Reviewer in a copied `review-workdir/`. Research and review are
    network-enabled stages: the Research Agent returns a Problem Schema v1.0
    record validated directly against `schemas/problem.schema.json` and
    leaves its audit notes in `research-memory.md`. The Problem Reviewer
    verifies the literature online, fixes formatting, makes the problem
    statement self-contained, returns the corrected full record, and leaves
    its review notes in `review-memory.md` (archived back into the candidate
    directory). It may
    override the audited status when online evidence settles the problem
    (`resolved-externally` / `refuted-externally`) or leaves it genuinely
    unclear (`uncertain`), but only with the external evidence cited in
    `concerns` or `previous_progress`; accepted records compile at any
    status, and settled problems sync to `pool/resolved/` instead of the
    active `pool/problems/`.
    Compilation uses the reviewed record. The deterministic pipeline owns
    identifiers, crash recovery, agent invocation retries, compilation, pool
    synchronization, and ranking, and injects every mechanical field — ids,
    status, domain, topic, repository, schema_version — so no agent output may
    contain or choose them (beyond the evidence-backed reviewer status
    override, any drift is a contract failure). Agent notes follow the
    `<role>-memory.md` convention; pipeline memory is always `memory.md`.
16. Before every agent invocation retry, clear stale structured output. On
    timeout, terminate the whole process group so descendants cannot retain
    pipes. A failed research/review stage quarantines its candidate as
    `research_failed`; a plain `campaign resume` re-runs it because no ledger
    cache exists for the failed stage.
17. Remote publication still requires explicit user authorization.

Use `uv run pytest` and `make check` before publishing changes.
