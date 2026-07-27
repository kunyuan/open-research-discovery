# Open Research Discovery

`open-research-discovery` is a discipline-neutral toolkit for turning
source-grounded open questions into independently reviewable research
repositories.

It separates three decisions that are often conflated:

1. Is the question scientifically important?
2. What does later literature say about its current status?
3. Can a future Solution Reviewer validate the submitted result with a
   concrete, bounded protocol?

The toolkit discovers, canonicalizes, audits, ranks, and packages problems. It
does not contain the private problem corpus and it does not solve the
problems. The companion corpus lives in
`kunyuan/open-research-problem-pool`; solver work lives in one repository per
problem.

## First principles

A problem is worth dispatching when it is meaningful and its answer has an
explicit acceptance boundary. Expected solve difficulty, searchability,
candidate-space size, feedback density, compute cost, and probability of
success are downstream solver concerns, not ranking criteria.

The lifecycle is:

```text
campaign query
  -> Discovery Agent returns candidate papers
  -> direct LKM papers/graph request
  -> strict data.papers[].open_questions extraction
  -> exact provenance capture
  -> heuristic deduplication and Codex semantic canonicalization
  -> Triage Agent checks intrinsic importance and reviewability
  -> Research Agent searches LKM/Web and directly returns status, major
     progress, surviving core, and verification contracts
  -> independent Problem Reviewer writes one report and verdict
  -> accept compiles; revise marks needs_revision; reject stops
  -> one independent Git repository
  -> deterministic pool synchronization
  -> research-ready ranking
  -> issue-scoped solver dispatch and independent review
```

The current ingestion adapter uses Bohrium LKM. It accepts source questions
only from `data.papers[].open_questions`; the canonical problem model is not
tied to LKM or to a particular discipline.

The pipeline deliberately uses two different LKM interfaces. It calls the
`papers/graph` API directly for strict source-question extraction. Headless
agents use Gaia CLI and web search only for paper discovery and later-evidence
research. See [docs/discovery-pipeline.md](docs/discovery-pipeline.md) for the
complete control and data flow.

## What this repository contains

- `schemas/`: the canonical problem contract;
- `template/`: a complete, independently reviewable problem-repository
  skeleton;
- `src/open_research_discovery/`: reusable validation, ranking,
  deduplication, status-audit, campaign, agent-runner, and registry code;
- `scripts/`: command-line entry points for discovery and pool maintenance;
- `.agents/skills/`: the reusable discovery and ranking policies;
- `tests/`: unit and integration tests for the public contract.

It intentionally does not contain raw retrieval responses, curated problem
snapshots, later-literature audit evidence, private dispatch state, or the
generated corpus registry.

## Admission and ranking policy

Research worthiness uses only:

1. concrete scientific importance;
2. whether an independent LLM or checker can basically judge correctness from
   the submitted result itself.

A problem is `research-ready` when its surviving core is important and
current-open, and review needs only the submitted result. CI is a bonus:
implemented checks are best, problem-specific pseudocode is useful, and the
absence of CI does not disqualify an otherwise result-only problem.

Use one test: without reviewing the solver's reasoning process, can an
independent Reviewer basically decide correctness from only the final result
naturally required by the original problem? The agent makes this semantic
judgment directly; the schema does not classify answers into artifact types.
An ordinary written proof remains `result-and-derivation`; executable formal
proof code counts as the result only when the original problem requests it.

Each admitted problem records the expected result, acceptance boundary, and
concrete review checklist. See the abstracted campaign lessons in
[the Solution Review-scope casebook](docs/solution-review-scope-casebook.md).

CI status is recorded independently as `implemented`, `partial`, `pseudocode`,
`solution-reviewer-only`, or `blocked`. Machine checks establish only the
predicate encoded by the repository; they do not silently establish causality,
generality, novelty, or publication priority.

## Quick start

Requirements:

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- headless `codex exec`
- Gaia CLI with `gaia search lkm`
- `LKM_ACCESS_KEY` only when using the Bohrium LKM adapter

```bash
uv sync --dev
make check
```

Run a resumable campaign:

```bash
cp config/example-campaign.yaml /path/to/campaign.yaml
uv run discovery campaign run /path/to/campaign.yaml
uv run discovery campaign status <run-id> --runs-root /path/to/campaigns
uv run discovery campaign resume <run-id> --runs-root /path/to/campaigns
uv run discovery benchmark prepare /path/to/campaign.yaml \
  --run-id benchmark-v0 --triage-per-domain 8 --workers 3
uv run discovery benchmark resume-prepare <run-id> \
  --runs-root /path/to/campaigns --triage-per-domain 8 --workers 3
uv run discovery benchmark predict <run-id> \
  --runs-root /path/to/campaigns --workers 3
uv run discovery case retry <run-id> <candidate-id> research \
  --runs-root /path/to/campaigns
```

Every agent response is constrained by a checked JSON schema. The campaign
records input/output hashes, prompt/schema/skill versions, model/tool metadata,
attempts, events, exit codes, and timestamps. Resume skips only a completed
stage whose inputs and output hash still match.

`benchmark prepare` runs paper discovery, direct LKM `open_questions`
extraction, atomic canonicalization, and Triage without commissioning
later-literature Research/Problem-Reviewer cycles or compiling problem
repositories.
`benchmark predict` reruns or resumes Triage for every canonical candidate
without first
commissioning full later-literature Research/Problem-Reviewer cycles. Its
output is a baseline prediction set, not benchmark gold. Retain predicted
passes, failures, and boundary cases for independent adjudication.
`--workers` bounds concurrent headless Codex subagents; one in-process ledger
serializes atomic state-file updates. Do not run two mutating CLI commands
against the same campaign directory at once.
For a full campaign, `agents.workers` in `campaign.yaml` bounds the same
independent Triage fan-out before candidates enter later-literature Research.

The initial benchmark profile covers mathematics, physics, and computational
science only. This scope restriction applies to benchmark selection, not to
the discipline-neutral discovery pipeline.

See [docs/screening-benchmark.md](docs/screening-benchmark.md) for the
no-leakage input/prediction/gold layout and stratified benchmark workflow.

Extract the dedicated `open_questions` section of one paper graph:

```bash
uv run python scripts/extract_paper_open_questions.py \
  --doi "10.1000/example" \
  --raw-out /path/to/pool/inbox/example/paper-graph.json \
  --out /path/to/pool/inbox/example/open-questions.json
```

Create one independent problem repository:

```bash
uv run python scripts/create_problem_repo.py \
  --id ORP-0001 \
  --title "Example canonical open research problem" \
  --slug example-canonical-open-research-problem \
  --out ../ORP-0001-example-canonical-open-research-problem \
  --git-init
```

Audit later literature and validate a companion pool:

```bash
uv run python scripts/audit_resolution.py \
  ../ORP-0001-example-canonical-open-research-problem/problem.yaml

uv run python scripts/validate_pool_repository.py \
  ../open-research-problem-pool
```

Query and rank an external pool:

```bash
uv run python scripts/query_pool.py \
  --catalog ../open-research-problem-pool/pool/catalog.jsonl \
  --domain quantum

uv run python scripts/rank_problem_pool.py \
  --catalog ../open-research-problem-pool/pool/catalog.jsonl \
  --lane research-ready
```

## Repository model

Every generated problem repository contains:

- `problem.yaml`: canonical question, status audit, importance, result
  contract, Solution Reviewer contract, CI contract, and compute envelope;
- `evidence/`: source and later-literature provenance;
- `baseline/`: the best known result to improve or settle;
- `references/`: annotated primary literature;
- `submission/`: the complete answer artifact;
- `verifier/solution-review.md`: the normative post-solution checklist;
- `verifier/ci.md`: executable algorithm or problem-specific pseudocode;
- `.github/workflows/verify.yml`: structural and available substantive checks.

New records use `ORP-*` (Open Research Problem). The existing `OMP-*`
namespace remains valid for immutable legacy identifiers.

## Skills

- `$research-evidence-search` gives Discovery and Research agents one neutral
  LKM/Web evidence-retrieval capability, including Gaia CLI commands and honest
  content-level labels.
- `$lkm-open-question-to-repo` performs strict LKM extraction,
  canonicalization, triage, current-status audit, and repository preparation.
- `$rank-open-problems` ranks current problems only by importance and
  independent verification cost.

Discovery and Research are the only networked headless-Codex roles. They run
inside the isolated checkout with `workspace-write` plus network access so
Gaia CLI can reach LKM. Canonicalization, Triage, and Problem Reviewer stay
`read-only`; the pipeline does not require `danger-full-access`.

## Companion repository layout

The tools accept explicit paths, so no fixed local layout is required. A
convenient sibling layout is:

```text
workspace/
  open-research-discovery/
  open-research-problem-pool/
  ORP-0001-example/
  OMP-0001-legacy-example/
```

The public discovery repository may be forked and tested independently. The
private pool retains its evidence, corpus snapshots, deduplication relations,
generated views, and dispatch mappings.
