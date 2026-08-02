# Repository Instructions

Work from the problem lifecycle, not from isolated search hits.

Default to the problem-generation campaign when a user asks to find, audit, or
publish research problems. Benchmark construction and benchmark evaluation are
separate workflows: run `discovery benchmark ...` only when the user explicitly
asks for a benchmark.

1. Preserve raw LKM paper-graph responses and contextual evidence used by any
   discovery strategy.
2. Keep two origin classes explicit. `lkm_explicit_open_questions` extracts
   only `data.papers[].open_questions`. `lkm_topic_decomposition` may derive a
   question from contextualized evidence anchors, but must never attribute that
   derived question to a source as a verbatim open question.
3. Normalize every strategy output to `CandidateSeed`, then canonicalize and
   refine all seeds through the shared downstream path.
4. Before the expensive later-literature audit, record concrete scientific
   importance and verification difficulty from 0 to 10.
5. Audit later literature for every high- or medium-importance candidate after
   intrinsic Triage, regardless of verification difficulty; use `uncertain`
   when absence of a solution is the only evidence.
6. When major progress exists, rewrite the surviving core and reassess its
   importance, verification difficulty, and optional CI instead of
   inheriting old scores.
7. Keep all verification scores visible as diagnostics and ranking inputs.
   Never use verification difficulty as a Triage, Research, publication, or
   dispatch threshold.
8. Do not set the internal record to `status: ready` without a surviving open
   core, an expected result, and a concrete, unambiguous verification contract.
9. Treat retrieval score as ranking only, never as confidence.
10. Keep proofs, simulations, experiments, datasets, benchmarks, and other
    solving artifacts in the generated problem repository, not this discovery
    toolkit.
11. Rank research candidates by importance and lower verification difficulty.
    Treat CI availability and latency only as bonuses. Never use expected solve
    difficulty, searchability, feedback density, or success probability as
    worthiness criteria.
12. CI is optional for research dispatch and publication. Checker
    implementation may control later automatic acceptance; verification
    difficulty remains a score, not a gate.
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
    papers in the explicit strategy go to the direct LKM `papers/graph` API,
    and only `data.papers[].open_questions` creates explicit-source seeds.
    Topic decomposition uses LKM/web evidence packets with exact excerpts,
    surrounding context, closest prior work, freshness searches, and a precise
    falsifiable delta to create evidence-derived seeds.
18. In a campaign, a Research Agent's searched evidence flows directly into
    status, major progress, surviving-core, and verification-contract
    assessment. Problem Reviewer revisions return to Research, never to
    Discovery. In the per-topic workflow, revisions instead resume the exact
    original Topic Main Agent session.
19. Agents return schema-validated artifacts and never mutate the companion
    pool directly. The deterministic pipeline owns IDs, retries, compilation,
    pool synchronization, and ranking.
20. The public boundary is `problem.json`, validated by
    `schemas/problem-contract.schema.json`. It contains only the agreed Problem
    Contract fields. README rendering, contract review, rewriting, and GitLab
    publication consume this contract rather than internal campaign records.
21. `scientific_significance` is a dictionary keyed by affected field; each
    entry has `high`, `medium`, or `low` plus a concrete description of what
    changes. `solution_difficulty` is an unscored list of possible solving
    obstacles.
22. `verification_contract` is a dictionary keyed by accepted answer type. For
    every type, state the complete acceptance contract and the mechanically
    executable `ci_contract`, or `null` when no reasonable CI exists. CI means
    Continuous Integration: an automatic mechanical check run after an answer
    or repository update.
23. `verification_difficulty` is one overall 0-10 score across all accepted
    answer types after all mechanically checkable work has been excluded, even
    when the CI implementation does not exist yet. Score only the residual
    Agent or human Reviewer judgment: 0 none; 1-3 local standard checks; 4-6
    connected derivations or substantial problem-answer correspondence work;
    7-9 long, fragile, or novel reasoning or substantial code review; 10
    holistic expert judgment. It measures review difficulty, not solving
    difficulty, and is never a gate.
24. A parent that delegates to `subproblem_ids` may use an empty
    `solution_difficulty` and null verification fields. Every dispatched leaf
    problem supplies its own verification contract and score.
25. A standalone generated problem directory is contract-first and contains
    `problem.json` plus a deterministically generated English `README.md`. It
    must not contain the internal `problem.yaml`, copied schemas, reviewer
    configuration, or generic structural CI.
26. Add `.gitlab-ci.yml`, `verify/`, `examples/`, or `data/` only when the
    specific problem needs them. Use GitLab math delimiters (`$...$` inline and
    `$$...$$` for display). `README.zh-CN.md` is an optional faithful
    translation, never an independent source of scope or acceptance criteria.
27. Use one persistent Topic Main Agent per topic. Persist and resume its exact
    session UUID; never use `--last`, and fail closed if the topic text changes
    under an existing topic ID.
28. The Topic Main Agent owns search decomposition and final contracts. Run its
    independent search briefs in parallel through schema-constrained workers,
    normalize them into one evidence ledger, and send only evidence deltas back
    to the resumed main Agent.
29. Generate a companion evidence dossier for every topic-derived contract.
    Keep it outside the public Problem Schema, but submit it beside the contract
    so source context, freshness searches, and the claimed open core can be
    independently audited.
30. Submit each problem under `problems/<problem_id>/` in the existing topic
    repository through its own Draft MR. Refresh the root problem index
    deterministically and merge these MRs serially.
31. Keep workflow state outside `problem.json`. Anchor every independent review
    to the GitLab project, MR, current commit SHA, contract path and hash,
    optional evidence path and hash, and review prompt/schema hashes. A new push
    invalidates the old review.
32. The Topic Main Agent may push its unprotected problem branch and create or
    update its Draft MR, but it never reviews or merges its own work. A fresh
    Reviewer reads exact Git blobs in a trusted read-only working directory,
    without network or GitLab credentials, and may return only an anchored
    verdict. It never pushes, approves, or merges.
33. Publish the review as a commit status bound to the current MR head SHA plus
    an audit note. Recheck the MR head after review; labels and comments alone
    are not merge gates. Merging belongs to a human or separately authorized
    finalizer.
34. Treat `contract publish` as a legacy standalone helper. The default topic
    lifecycle is `topic run` -> `contract submit` -> `contract review-mr`, then
    on rewrite `topic revise` -> `contract update-draft` -> fresh review.

Use `uv run pytest` and `make check` before publishing changes.
