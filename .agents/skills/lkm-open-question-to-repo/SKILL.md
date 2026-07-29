---
name: lkm-open-question-to-repo
description: Extract dedicated cross-disciplinary open questions from Bohrium LKM paper graphs, canonicalize duplicates, triage scientific importance and 0-10 verification difficulty, then audit whether later work resolved, narrowed, validated, or reframed each prioritized question before creating one agent-ready Git repository per surviving or derived problem. Use for LKM research-problem mining in mathematics, physics, computer science, chemistry, biology, engineering, or other fields; open-question triage; resolution-status refreshes; problem-repo generation; or batch-agent queue preparation.
---

# LKM Open Question to Repo

Turn source-paper open-question records into current, independently solvable
problem repositories. Keep structured discovery records in the campaign and
companion pool; expose the research problem to people and solving agents
through one readable, versioned README.

## Workflow

1. Start from a paper supplied or selected by `paper_id`, DOI, or title. Request
   its complete LKM paper graph directly:

   ```bash
   curl -sS \
     -H "accessKey: $LKM_ACCESS_KEY" \
     -H "Content-Type: application/json" \
     -d '{"doi":"<DOI>"}' \
     https://open.bohrium.com/openapi/v1/lkm/papers/graph
   ```

   The request body must contain exactly one of `paper_id`, `doi`, or `title`.
   Never log or commit the access key. Preserve the raw response and `trace_id`.

2. Require response-body `code == 0`; HTTP success alone is insufficient.
   Extract candidates only by iterating:

   ```text
   data.papers[].open_questions[]
   ```

   For every item preserve `content`, `id`, and `global_id`, together with
   `paper.id`, the paper title, and DOI from the containing paper record. Do not
   infer open questions from ordinary `question`, `problem`,
   `addressed_problems`, `subproblem`, motivation, variable, or graph nodes.
   The dedicated `open_questions` section is the source-of-truth boundary.

   `gaia search lkm knowledge --scopes question` is not an open-question
   extractor. It can return mixed `problem`, `subproblem`, `question`, and
   `open_question` nodes. Use those results only to recover a containing paper
   ID, DOI, or title; confirm every candidate through the direct endpoint.

   Treat a nonzero response-body code as a failed lookup, never as an empty
   `open_questions` array. Preserve the raw response and try the same paper by
   each available identifier in order: `paper_id`, DOI, exact title. If all
   identifiers fail, record the paper-level failure and select another
   LKM-indexed source paper. Never substitute Gaia question hits for the
   missing direct response.

   Use the discovery repository extractor and write the evidence into the
   companion pool:

   ```bash
   uv run python scripts/extract_paper_open_questions.py \
     --doi "<DOI>" \
     --raw-out ../open-research-problem-pool/inbox/<run>/paper-graph.json \
     --out ../open-research-problem-pool/inbox/<run>/open-questions.json
   ```

3. Atomize and canonicalize before creating a repo. When one dedicated
   `open_questions` record explicitly contains several separable targets,
   split it into atomic candidates, each with one acceptance target and an
   exact supporting excerpt. The same source node may support several atomic
   candidates. Merge equivalent formulations from multiple papers into one
   problem. Keep all source node IDs, local IDs, paper IDs, exact texts, dates,
   DOIs, aliases, and candidate-specific exact excerpts. Do not sharpen a
   source direction into an unstated conjecture, benchmark, or threshold.

4. Triage and rank the intrinsic problem before spending effort on a
   current-status audit. Apply `$rank-open-problems` and
   [references/rubric.md](references/rubric.md) to the canonical statement as
   it stood in the source:

   - state why a solution would materially change a bound, construction,
     algorithm, classification, or shared theoretical bottleneck;
   - describe the expected final result in plain language without proposing a
     solving method;
   - assign `verification_difficulty` from 0 to 10 using the rubric; 0 means
     every load-bearing claim is discharged by mechanical checks, replay, or
     certificates with trivial specification fidelity and does not require
     CI, while 10 is an essential claim that cannot be decomposed into
     independently checkable units;
   - explain in `verification_difficulty_rationale` why that result genuinely answers
     the source question, any limitations on the claim, and whether review
     must substantively assess a derivation rather than only the final answer
     or artifact;
   - implement CI when possible; otherwise write problem-specific pseudocode,
     runner requirements, a hard timeout, and estimated verification runtime.

   Prioritize later-literature work for candidates that are meaningful and
   within `limits.max_verification_difficulty`. CI is a ranking bonus, not a gate. Do not use search or solve
   difficulty. Keep lower-priority candidates in the inventory with their
   labels instead of silently discarding them.

5. Audit later results for the prioritized candidates. Search both
   `comprehensive` and `recent` rankings using
   `$research-evidence-search`. Let the agent combine Gaia LKM and web routes
   adaptively rather than imposing a fixed source order. Search using:

   - the canonical statement;
   - theorem, conjecture, claim, method, benchmark, author, and notation aliases;
   - `solved`, `proof`, `counterexample`, `refuted`;
   - `improved bound`, `exact value`, `special case`, `remaining open`.

   Search both claim and question scopes. Read the relevant later papers or
   paper graphs and reconstruct how the same core evolves: closure result,
   counterexample, replication, failed validation, equivalent reformulation,
   special case, improved bound or benchmark, or continuing use as an
   unresolved target. A later paper need not literally repeat "remains open".
   Absence of a matching solution is never sufficient by itself, but a
   well-covered citation and topic chain may support a confidence-labelled
   `still_open` judgment.

   This stage audits the research record; it does not solve the candidate.
   Do not use a proof, counterexample, construction, computation, or scientific
   explanation newly created by the Research Agent as evidence of closure or
   major progress. Record an apparent elementary issue as a scope/identity
   concern for the Problem Reviewer, and require external research evidence
   before assigning `resolved` or `refuted`.

6. Assign exactly one resolution status:

   - `still_open`
   - `partially_resolved`
   - `resolved`
   - `refuted`
   - `uncertain`

   If the audit finds major progress, do not merely append a citation. Rewrite
   the exact surviving core and reassess, from scratch:

   - whether the remaining question is still scientifically important;
   - whether its answer remains easy enough to verify;
   - whether the progress suggests a distinct, meaningful derived problem.

   Keep the original repo for lineage. Continue it only when the rewritten core
   still passes triage. Create a linked new repo when later work changes the
   research object, population, regime, assumptions, or success condition
   enough to define a distinct problem. Stop solver dispatch when the residual
   question is resolved, unimportant, or no longer acceptably verifiable.

7. Put a problem in the `research-ready` lane when its post-audit core is
   current-open and important, and its verification score is within the
   campaign limit. The rationale must establish that this result
   faithfully answers the surviving core. Problem-specific CI pseudocode with
   runner assumptions, runtime estimate, and hard timeout is sufficient; the
   checker need not be implemented before research starts. Keep
   `ci_contract.status` honest: `pseudocode` or `partial` does not authorize
   automatic acceptance. A bounded LLM review checklist also qualifies.

8. Generate the problem repo:

   ```bash
   uv run python scripts/create_problem_repo.py \
     --id ORP-0001 \
     --title "<canonical title>" \
     --slug "<short-slug>" \
     --out <path> \
     --source-node <gcn_id> \
     --with-zh-translation \
     --git-init
   ```

   Replace the editorial comments in `README.md` with a natural research
   explanation written entirely in English. `README.md` is the canonical
   scientific specification. Use these eight sections, in order:

   1. `The Research Problem`
   2. `Why It Matters`
   3. `Expected Results`
   4. `Difficulty`
   5. `Verification Difficulty`
   6. `Possible CI`
   7. `Current Research Status`
   8. `LKM and References`

   Write for a researcher outside the narrow subfield: they should understand
   the problem, why it is worth doing, what a useful submission could be, and
   how its value would be reviewed. Write `The Research Problem` in the style of a
   concise academic introduction followed by a problem statement, not as a
   schema or a checklist. Explain the scientific setting, introduce specialist
   terminology and acronyms, summarize the prior result or limitation from
   which the question arises, and then state the unresolved target accurately.
   Include the field-specific information needed to understand what would
   answer the question: this may be mathematical definitions and equations,
   an experimental system and its observables, a material or operating regime,
   a dataset and evaluation protocol, a computational task and baseline, or
   another discipline-appropriate description. Use formulas, parameter ranges,
   quantifiers, and conventions only when they are relevant to that problem.
   If the target depends on a source equation, matrix, Hamiltonian, assay,
   loss function, dataset, or observable, reproduce or explain the portion
   needed to identify the target; a bare citation such as “the operator in
   Eq. (45)” or an unexplained field acronym is insufficient. The reader may
   need the cited papers for deeper context, but not to discover what question
   is being asked. Do not expose internal schema fields as a metadata table.
   Difficulty is explanatory only and must not feed back into ranking. Put the
   dated openness judgment and key evidence relationships in the README;
   update them later through commits and Merge Requests.
   Use GitLab-compatible math delimiters: `$...$` inline and `$$...$$` for
   display math. Do not use `\(...\)` or `\[...\]`.

   Keep the repository minimal:

   ```text
   README.md
   README.zh-CN.md      # optional faithful translation
   .gitlab-ci.yml       # only when substantive problem-specific CI exists
   verify/              # only when that CI needs verifier code
   examples/ or data/   # only when the problem itself needs them
   ```

   Do not copy `problem.yaml`, JSON manifests, a difficulty schema, reviewer
   configuration, a separate status file, raw LKM responses, or a generic
   structural workflow into the problem repository. Those records belong in
   the campaign and companion pool. Put review instructions directly under
   `Verification Difficulty`. Put CI ideas directly under `Possible CI`; if no useful
   automatic predicate exists, say that Reviewer judgment is primary.

   `--with-zh-translation` creates a `README.zh-CN.md` scaffold. Fill it only
   as a faithful Chinese translation of the completed English README. It must
   not add, omit, or change the scientific target, accepted result,
   Verification Difficulty, CI criterion, or research status. `README.md`
   remains authoritative;
   omit the translation rather than leave a stale or partial duplicate.

9. Register the problem in the companion pool, not in this public discovery
   repository. Create or push a remote GitHub/GitLab repository only when the
   user explicitly authorizes that external write. Register the resulting URL
   and exact baseline commit in the pool's operational registry.

## Non-negotiable boundaries

- Extract source open questions only from `data.papers[].open_questions`.
- Treat Gaia question-scope hits, including `::open_question` provenance
  suffixes, only as paper leads until the direct paper-graph response confirms
  them.
- Treat nonzero LKM business codes as failures, not empty successful
  extractions; retain the raw response and identifier-attempt history.
- Do not infer an open question from ordinary `question`, `problem`,
  `addressed_problems`, `subproblem`, motivation, variable, or graph records,
  even when their wording sounds unresolved or their IDs contain suggestive
  suffixes.
- Do not create one repo per raw LKM node; create one repo per canonical problem.
- Do not keep a conjunctive multi-question LKM summary as one candidate when
  its explicitly stated targets can be separated.
- Do not lower `verification_difficulty` by inventing a benchmark, finite
  proxy, or threshold that does not answer the scoped target.
- Score explicit counterexamples, exact solutions, finite constructions,
  fixed code-to-experiment comparisons, and required Lean/Coq/Isabelle proof
  artifacts with contract-pinned statements as 0 when no derivation review or
  holistic judgment remains after the delegable checks. Score an ordinary
  natural-language proof as 10.
- Do not pass question IDs to claim-reasoning lookup.
- Do not treat retrieval score as confidence or scientific importance.
- Do not use searchability, feedback density, expected solve time, search
  compute, or success probability to decide whether a problem is worth
  attempting. Those fields belong only to downstream solver scheduling.
- Do not declare novelty from a local verifier.
- Do not spend a systematic resolution audit on every raw retrieval hit;
  establish intrinsic importance and verification fit first.
- Do not inherit importance or verification scores after major progress;
  reassess the rewritten core and any derived problem.
- Do not treat `expert-review` as `llm-reviewable`, or an LLM plausibility
  judgment as a proof certificate.
- Do not treat a green schema/unit-test workflow as substantive acceptance.
  Record CI status as `pseudocode`, `solution-reviewer-only`, or `blocked`
  until the substantive predicate is actually implemented.
- Do not make authors maintain a machine manifest beside the README. Parse the
  README and Git history when a downstream search or collaboration system
  needs structure.
- Do not reduce `The Research Problem` to a bare conjecture, one-sentence task, field
  acronym, or external equation reference. Give enough academic background,
  terminology, prior-work context, and discipline-appropriate detail for a
  researcher outside the narrow specialty to understand the origin and exact
  meaning of the open problem. Do not impose mathematics-specific notation or
  fields on problems that are naturally experimental, computational, or
  descriptive.
- Do not copy restricted paper PDFs; store metadata, stable links, and precise
  evidence notes.
- Do not admit `resolved`, `refuted`, or `uncertain` problems to the
  `research-ready` queue.
- Refresh the resolution audit before accepting a claimed solution.

Read [references/resolution-audit.md](references/resolution-audit.md) whenever
the current status has not already been reconstructed from the later-literature
treatment of the same research core.
