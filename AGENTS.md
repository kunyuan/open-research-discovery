# Repository Instructions

Work from the problem lifecycle, not from isolated search hits.

1. Preserve raw LKM paper-graph responses used as evidence.
2. Extract only `data.papers[].open_questions`; never infer openness from
   ordinary question, problem, subproblem, motivation, variable, or graph
   records.
3. Canonicalize equivalent nodes before creating a problem repository.
4. Before the expensive later-literature audit, record concrete scientific
   importance and verification difficulty from 0 to 10.
5. Audit later literature only after intrinsic triage; use `uncertain` when
   absence of a solution is the only evidence.
6. When major progress exists, rewrite the surviving core and reassess its
   importance, verification difficulty, and optional CI instead of
   inheriting old scores.
7. Keep all verification scores visible. Dispatch by the campaign's configured
   maximum score instead of a binary review-scope label.
8. Do not set the internal record to `status: ready` without a surviving open
   core, an expected result, and a verification score within the campaign limit.
9. Treat retrieval score as ranking only, never as confidence.
10. Keep proofs, simulations, experiments, datasets, benchmarks, and other
    solving artifacts in the generated problem repository, not this discovery
    toolkit.
11. Rank research candidates by importance and lower verification difficulty.
    Treat CI availability and latency only as bonuses. Never use expected solve
    difficulty, searchability, feedback density, or success probability as
    worthiness criteria.
12. CI is optional for research dispatch. Checker implementation controls
    automatic acceptance, not whether research may start.
13. Use `ORP-*` for new cross-disciplinary records. Preserve existing `OMP-*`
    identifiers as immutable legacy IDs.
14. Do not equate machine validation with scientific generality, causality,
    novelty, or publication priority; accept only the exact claim encoded by
    the Solution Reviewer contract.
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
    progress, surviving-core, and verification-contract assessment. Problem
    Reviewer revisions return to Research, never to Discovery.
19. Agents return schema-validated artifacts and never mutate the companion
    pool directly. The deterministic pipeline owns IDs, retries, compilation,
    pool synchronization, and ranking.
20. Let the Problem Reviewer judge verification difficulty directly from
   the exact question and expected result. Put scientific sufficiency, claim
   limitations, and review reasoning in one
   `verification_difficulty_rationale`, not
   separate schema fields. `solution_review_checklist` is consumed only after
   solver submission.
21. Verification difficulty is the residual burden left after every
   mechanically delegable check has been delegated. Score 0 means all
   load-bearing claims are discharged by mechanical checks, replay, or
   certificates with trivial specification fidelity; it does not require CI.
   Explicit counterexamples,
   exact solutions, finite constructions, source-faithful code-to-experiment
   comparisons, and required Lean/Coq/Isabelle proof artifacts with
   contract-pinned statements can all be 0.
   An essential claim that cannot be decomposed into independently checkable
   units is 10. CI tracks how much of the delegable checking has been
   automated; it cannot lower the structural score.
22. Keep structured records in campaign outputs and the companion pool. A
    generated problem repository is README-first and must not contain
    `problem.yaml`, copied schemas, reviewer configuration, or generic
    structural CI.
23. Add `.gitlab-ci.yml`, `verify/`, `examples/`, or `data/` only when the
    specific problem needs them. Put future Solution Review instructions and
    meaningful CI ideas directly in the README.
24. Write the canonical problem-repository `README.md` entirely in English and
    use GitLab math delimiters (`$...$` inline and `$$...$$` for display).
    `README.zh-CN.md` is an optional faithful translation, never an independent
    source of scientific scope or acceptance criteria.

Use `uv run pytest` and `make check` before publishing changes.
