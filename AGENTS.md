# Repository Instructions

Work from the problem lifecycle, not from isolated search hits.

1. Preserve raw LKM paper-graph responses used as evidence.
2. Extract only `data.papers[].open_questions`; never infer openness from
   ordinary question, problem, subproblem, motivation, variable, or graph
   records.
3. Canonicalize equivalent nodes before creating a problem repository.
4. Before the expensive later-literature audit, record concrete scientific
   importance and label verification mode and ease.
5. Audit later literature only after intrinsic triage; use `uncertain` when
   absence of a solution is the only evidence.
6. When major progress exists, rewrite the surviving core and reassess its
   importance and verification profile instead of inheriting old scores.
7. Machine-checkable,
   short LLM-reviewable, hybrid, and expert-review problems may all be kept;
   do not silently present one mode as another.
8. Do not set `status: ready` without a surviving open core, an expected
   artifact, an explicit success condition, and either an implemented checker
   or a bounded LLM review protocol.
9. Treat retrieval score as ranking only, never as confidence.
10. Keep proofs, simulations, experiments, datasets, benchmarks, and other
    solving artifacts in the generated problem repository, not this discovery
    toolkit.
11. Rank research candidates only by importance, reviewer scope, verification
    feasibility, and verification latency. Never use expected solve difficulty,
    searchability, feedback density, or success probability as worthiness
    criteria.
12. Treat a problem-specific, bounded CI design as sufficient for research
    dispatch. Checker implementation controls automatic acceptance, not whether
    research may start.
13. Use `ORP-*` for new cross-disciplinary records. Preserve existing `OMP-*`
    identifiers as immutable legacy IDs.
14. Do not equate machine validation with scientific generality, causality,
    novelty, or publication priority; accept only the exact claim encoded by
    the reviewer contract.
15. Keep corpus data outside this public repository. Raw retrieval responses,
    curated problem snapshots, literature-review evidence, generated views,
    and dispatch mappings belong in the companion problem-pool repository.
16. All pool-facing commands must accept an explicit external path; do not
    introduce a hidden dependency on a repository-local `pool/`, `registry/`,
    `inbox/`, or `reports/` directory.
17. Keep source-question ingestion and evidence retrieval separate. Candidate
    papers go to the direct LKM `papers/graph` API, and only
    `data.papers[].open_questions` creates source questions. Gaia CLI and web
    search are evidence-retrieval tools for Discovery and Research agents.
18. A Research Agent's searched evidence flows directly into status, major
    progress, surviving-core, and verification-contract assessment. Reviewer
    revisions return to Research, never to Discovery.
19. Agents return schema-validated artifacts and never mutate the companion
    pool directly. The deterministic pipeline owns IDs, retries, compilation,
    pool synchronization, and ranking.

Use `uv run pytest` and `make check` before publishing changes.
