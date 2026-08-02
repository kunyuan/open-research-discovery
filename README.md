# Open Research Discovery

`open-research-discovery` is a discipline-neutral pipeline for finding
source-grounded open research questions, checking whether they are still
scientifically meaningful, and packaging the strongest candidates as
independently reviewable Git repositories.

The package is designed for research agents, but it does not ask one large
agent to improvise the entire workflow. A deterministic program owns control
flow, provenance, schemas, retries, IDs, state, repository generation, pool
synchronization, and ranking. A small number of headless Codex roles make the
scientific judgments that cannot be reduced to stable code.

The result is not merely a list of interesting-looking questions. For every
admitted problem, the pipeline records:

- the exact source open-question text and paper provenance;
- a canonical, atomic statement of the problem;
- what later literature has resolved, narrowed, or reframed;
- the precise surviving open core;
- the affected scientific fields and the concrete significance in each;
- possible solving obstacles without conflating them with review difficulty;
- one acceptance contract for every allowed answer type;
- the mechanically executable CI part of each acceptance contract, when one
  exists;
- one overall residual verification-difficulty score after those mechanical
  parts have been removed;
- one independent repository that a solver agent can work in.

The public toolkit intentionally does not contain the private problem corpus.
Curated questions, raw LKM responses, later-literature evidence, benchmark
labels, and dispatch state belong in the companion
`open-research-problem-pool`. Solver submissions belong in one repository per
problem.

## Contents

- [Why this package exists](#why-this-package-exists)
- [Design from first principles](#design-from-first-principles)
- [End-to-end architecture](#end-to-end-architecture)
- [How LKM is used](#how-lkm-is-used)
- [What the resulting questions look like](#what-the-resulting-questions-look-like)
- [What one generated problem repository contains](#what-one-generated-problem-repository-contains)
- [Installation](#installation)
- [Configure a campaign](#configure-a-campaign)
- [Recommended usage](#recommended-usage)
- [Single-paper and manual-repository tools](#use-the-strict-single-paper-extractor)
- [Companion problem pool](#work-with-a-companion-problem-pool)
- [Run artifacts and recovery](#run-artifacts-and-recovery)
- [Troubleshooting](#troubleshooting)

## Why this package exists

Searching for papers and selecting research problems are different tasks.

A paper search engine can retrieve a passage that sounds unresolved, but that
does not establish that:

1. the authors actually designated it as an open question;
2. the passage describes one atomic research target rather than a broad future
   program;
3. the question remains open after later work;
4. the surviving core is still scientifically important;
5. a submitted answer can be reviewed without reconstructing the solver's
   private reasoning process.

The pipeline therefore separates three decisions that are often conflated:

1. **Importance** — what scientifically changes if the problem is solved or
   materially advanced?
2. **Current status** — how does later literature treat the same core?
3. **Verification difficulty** — how much reasoning beyond the final submitted
   result must an independent Reviewer inspect, from 0 to 10?

Expected solve difficulty, probability of success, searchability, feedback
density, candidate-space size, and solver compute do not determine whether a
problem is worth attempting. Those are downstream scheduling questions.

## Design from first principles

The implementation follows six boundaries.

### 1. Origin class is an evidence boundary

The explicit-source strategy never infers a source open question from an
ordinary `question`, `problem`, `subproblem`, motivation, or discussion node.
Candidate papers are sent to the direct Bohrium LKM paper-graph API, and only
records under:

```text
data.papers[].open_questions[]
```

may create `explicit_source_question` seeds. The topic-decomposition strategy
may instead create `derived_from_evidence` seeds from contextualized anchors,
but those are labeled as derived and are never attributed to a paper as a
verbatim question.

This deliberately sacrifices some recall. A false open-question attribution
contaminates every downstream decision, while an omitted paper can be recalled
in a later campaign.

### 2. Programs own mechanics; agents own scientific semantics

Programs are reliable at API calls, exact extraction, hashing, schema
validation, state transitions, retries, deterministic IDs, and repository
generation. Agents are useful for finding relevant papers, recognizing
equivalent formulations, assessing scientific effect, and reconstructing how
later literature changes a problem.

The package uses each for the work it can actually support.

### 3. Intrinsic triage precedes expensive status research

The pipeline first canonicalizes raw retrieval hits, then Triage evaluates
every canonical candidate. Every high- or medium-importance candidate receives
the systematic later-literature audit, regardless of verification difficulty.

Low-importance questions are retained in the inventory without consuming the
same audit budget. Above-limit verification questions are audited normally;
otherwise acceptable cases are retained as `audited_out`. The limit controls
publication, not status Research.

### 4. Current openness is reconstructed, not guessed

“No solution found” is not evidence that a problem remains open. The Research
Agent follows later papers, aliases, citations, special cases, improved bounds,
and adjacent results. A recent paper need not literally repeat “this remains
open”; the evidence must show what happened to the same scientific core.

When major progress exists, the pipeline rewrites the surviving core and
reassesses importance and verification difficulty from scratch.

### 5. Verification difficulty measures residual burden

The score is the residual verification burden left on an independent reviewer
after every mechanically delegable check has been delegated — not how hard
the answer is to discover. Claims are discharged through modes of increasing
cost: mechanical checks (kernels, test suites, SMT/SAT, substitution), replay
under a pinned protocol, and certificate checks all cost a small constant;
derivation review grows with chain length and dependency depth; holistic
judgment of a natural-language argument cannot be decomposed.

- **0:** every load-bearing claim is discharged by mechanical checks, replay,
  or certificates, and specification fidelity is trivial — the formal
  statement, protocol, or target is pinned by the contract. CI is not
  required; manual execution of a fixed procedure stays 0.
- **1–3:** the residual is a few independent, local, standard reasoning
  units.
- **4–6:** the residual contains connected derivations, or specification
  fidelity itself requires substantial reconstruction.
- **7–9:** the residual is a long, fragile, or novel chain, or substantial
  code that must be reviewed rather than run.
- **10:** the essential claim cannot be decomposed into independently
  checkable units.

Examples that score 0 include:

- a finite counterexample whose hypotheses and violation can be recomputed;
- an exact solution that can be substituted directly into pinned defining
  equations and boundary conditions without a separate coverage judgment;
- a Lean/Coq/Isabelle proof artifact required by the problem, with the
  statement pinned by the contract and accepted by a pinned kernel;
- an executable decoder that beats a named baseline in a source-grounded
  regime under declared accuracy and throughput comparisons;
- a first-principles model whose predictions can be rerun against a frozen
  experimental comparison.

An ordinary natural-language proof normally scores 10, while a required Lean
proof with a pinned statement scores 0. The difference is the verification
contract, not the mathematical difficulty. When the statement is not pinned,
checking that it faithfully encodes the problem is itself residual
derivation review.

An exact solution whose practical acceptance path relies primarily on
independent numerical reproduction of the original finite-size model scores
**2**, not 0. The light residual is checking that the independent model uses
the right basis, boundary conditions and observables; that precision,
tolerances and size/parameter coverage are adequate; and that exceptional
cases are included. The score remains independent of how difficult the exact
solution was to discover.

For executable comparisons, the source must ground the scientific target,
baseline, applicable regime, and comparison axes. Routine reproducibility
details—versions, seeds, repetitions, and statistical tolerances—may be frozen
in the final result. Choosing a favorable dataset, physical regime, metric, or
success threshold that changes the scientific target is not allowed, and
neither is hiding burden in an unverified specification gap.

### 6. CI is the operational layer

CI is delegation institutionalized: it automates the delegable checks. It
cannot lower the structural score. A finite counterexample or an exact
solution checked by direct substitution into pinned defining equations can
score 0 even when a human Reviewer checks it. An exact solution checked
primarily through independent numerical reproduction instead scores 2 under
the calibration above. Conversely, code that reproduces a few finite examples
does not lower a broad theorem, causal claim, continuum limit, or all-regime
generalization unless the replayed result itself answers that scoped question.
CI status records how much of the delegable checking has been automated and
improves over time; only better contract design, such as required certificates
or pinned formal statements, lowers the structural score.

Machine checks establish only the predicate encoded by the problem contract.
They do not silently establish novelty, causality, generality, or publication
priority.

The public Problem Contract uses schema version `1.0`; internal campaign and
benchmark records retain their own independent versions. Legacy categorical
review labels are not converted into guessed numeric scores.

## End-to-end architecture

```mermaid
flowchart TD
    C["Campaign configuration"] --> DS["Hot-pluggable discovery strategies"]
    DS --> D["Explicit LKM open-question strategy"]
    D --> A["Direct papers/graph extraction"]
    DS --> TD["Topic decomposition strategy"]
    TD --> B["CDQ-style search briefs"]
    B --> EP["Parallel contextual evidence packets"]
    A --> CS["CandidateSeed contract"]
    EP --> CS
    CS --> H["Shared canonicalization and refinement"]
    H --> T["Codex Triage Agent"]
    T -->|"low importance"| L["Retained triage-deferred inventory"]
    T -->|"high or medium importance"| R["Codex Research Agent"]
    R -. "LKM / Web evidence search" .-> E["Later-literature evidence"]
    E --> J["Status, major progress, surviving core, review and CI contracts"]
    J --> V["Independent Problem Reviewer"]
    V -->|"accept with clear contract"| QD["Quality-diversity selection: max N"]
    V -->|"revise"| N["Mark needs_revision and stop"]
    V -->|"reject"| X["Retain rejected record"]
    QD --> G["Program: compile one problem repository"]
    G --> P["Program: synchronize pool and rank"]
```

The Problem Reviewer writes one report and verdict. A `revise` verdict does
not create an uncontrolled Research–Reviewer loop. An operator can explicitly
retry the Research or Problem Review stage after inspecting the report.
Every distinct, pipeline-recorded `revise` verdict is appended to the
candidate-local `problem-review-feedback-history.json`, and a Research retry
receives the deduplicated union of all earlier concerns and revision
instructions.
`accept` and `reject` do not add feedback. The assessment's exact input is
frozen in `research-feedback-applied.json`. Within a v9 campaign, only an
explicit retry that invalidates Research (`triage` or `research`) advances that
snapshot. Ordinary resume and Problem-Review-only retry therefore reuse the
existing assessment instead of silently starting new Research. Its hash is
recorded in `state.json`; a missing or modified snapshot fails closed.

For a pre-v9 campaign, recovery trusts only a current verdict whose completed
stage record and output SHA match. If the version upgrade invalidates Research,
that recovered feedback is applied to the migration run. Verdict rounds
already overwritten by an older pipeline cannot be recovered automatically.
Re-audit them or add reviewed history entries with source `manual-seed`,
unique IDs, attempt `0`, and string-list concerns and revision instructions.
Campaign artifacts are trusted local state rather than a tamper-evident log;
never relabel a manual recovery entry as `problem-review`.

### Responsibility split

| Component | Owns |
| --- | --- |
| Deterministic pipeline | API requests, raw-response preservation, extraction, hashes, state, retries, IDs, schema validation, compilation, synchronization, ranking |
| Explicit-question Discovery Agent | Finding candidate papers and identifiers; never authoring source open questions |
| Topic planner and search workers | Independent CDQ-style briefs, contextual evidence packets, and evidence-derived seed proposals |
| Canonicalization Agent | Merging equivalent formulations and atomizing/refining all CandidateSeed records |
| Triage Agent | Source-grounded scientific importance, expected result, verification difficulty, optional CI |
| Research Agent | Later-literature search, current status, major progress, surviving core, revised contracts |
| Problem Reviewer | Independent audit of the constructed problem dossier |
| Future Solution Reviewer | Reviewing a solver submission using the generated checklist |

## How LKM is used

LKM serves two different purposes with different trust contracts.

### A. Strict source-question ingestion

For each candidate paper, the program sends:

```http
POST https://open.bohrium.com/openapi/v1/lkm/papers/graph
accessKey: <LKM_ACCESS_KEY>
Content-Type: application/json
```

The body contains exactly one of:

```json
{"paper_id": "867750354362565467"}
```

```json
{"doi": "10.48550/arXiv.2208.08547"}
```

```json
{"title": "Exact paper title"}
```

The collector:

1. requires response-body `code == 0`;
2. preserves the complete response and `trace_id`;
3. reads only `data.papers[].open_questions`;
4. stores each record's `content`, `id`, and `global_id`;
5. also stores the containing paper's ID, title, DOI, and exact source path.

A nonzero LKM business code is a failed lookup, not an empty successful result.
The collector retries the same paper by paper ID, DOI, then exact title. It
never substitutes ordinary LKM question nodes for a failed paper graph.

### B. Discovery and later-evidence research

Discovery and Research agents use the repository's
`$research-evidence-search` skill. LKM and the web are complementary sources;
there is no mandatory LKM-first or web-first sequence.

Common routes are:

- start from a question or concept and search LKM directly;
- use web search to recover a DOI, exact title, author, terminology alias, or
  citation trail, then return to LKM;
- inspect an accessible abstract or original paper text when LKM's compressed
  representation is ambiguous;
- follow a later claim back to its paper graph and reasoning chain;
- search the canonical statement together with `proof`, `counterexample`,
  `improved bound`, `special case`, `refuted`, and `remaining open`.

Gaia CLI provides the exploratory LKM interface used by headless agents:

```bash
gaia search lkm knowledge "<query>" \
  --scopes claim \
  --scopes question \
  --retrieval-mode hybrid \
  --include-paper-enrich \
  --sort-by comprehensive \
  --no-hint
```

The package may also use:

```text
gaia search lkm reasoning
gaia search lkm nodes
gaia search lkm package
```

### What information is available

| Source | Typical information | How it is used |
| --- | --- | --- |
| Direct LKM paper graph | Dedicated `open_questions`, paper metadata, structured nodes | Authoritative source-question extraction |
| LKM knowledge search | Metadata, abstracts, compressed conclusion claims | Paper recall and progress leads |
| LKM reasoning search | Compressed reasoning chains and premises | Understanding how a later claim was supported |
| Web search | DOI/title aliases, abstracts, citation trails, accessible preprints or original text | Identification, disambiguation, and primary-text inspection |

Every load-bearing evidence record carries an honest content-level label:

```text
metadata | abstract | compressed_claim | reasoning_chain |
partial_full_text | full_text
```

Retrieval score is only a ranking signal. It is never treated as scientific
confidence.

### Why Gaia search does not extract source open questions

Gaia's question scope is mixed: it may return `problem`, `subproblem`,
`question`, and `open_question` provenance. Those results are useful paper
leads, but even an ID ending in `::open_question` is not admitted until the
direct `papers/graph` response confirms it under the dedicated
`open_questions` field.

This is the most important provenance rule in the package.

## What the resulting questions look like

A research-ready problem must satisfy all three conditions:

1. the audited surviving core is current-open;
2. its importance is `high` or `medium`;
3. its answer has a concrete, unambiguous verification contract.

`verification_difficulty` remains a visible 0-10 diagnostic and an ordering
signal among otherwise similar candidates. It is never a Triage, Research,
publication, or dispatch threshold. CI availability and latency are bonuses.

### Representative positive shapes

#### Finite mathematical counterexample

**Question shape:** find a finite cubic planar graph whose injective chromatic
number is at least six.

**Expected result:** one explicit graph.

**Review:** check that the graph is finite, simple, cubic, connected, and
planar; construct the injective-coloring constraint graph; use an exact solver
to show that five colors are impossible.

The search process can be arbitrarily difficult. The final result is small and
independently checkable.

#### Exact theoretical-physics object

**Question shape:** determine exact quantum bounds for fixed finite Bell
operators and provide attaining states and measurements.

**Expected result:** exact values together with finite states and measurement
operators.

**Review:** reconstruct the fixed operators, verify the attaining expectation
values, and independently reproduce matching global bounds.

#### Executable scientific code

**Question shape:** construct a decoder that improves logical-error
suppression over a named baseline in a specified code and noise regime while
meeting a declared throughput constraint.

**Expected result:** source code or HDL, locked dependencies, source-grounded
configuration, seeded or statistically controlled comparisons, and
machine-readable outputs.

**Review:** run candidate and baseline on identical inputs; recompute accuracy,
throughput, resource use, and confidence intervals. The reviewer does not need
the solver's design or search reasoning.

This scores 0 because the replayed comparison answers the scoped scientific
claim. “Here is code that performs well on examples I chose” is not sufficient.

### Representative negative and boundary shapes

#### Broad PDE generalization

“Develop a surrogate that is robust for long-time evolution across all flow
regimes” is scientifically important, but a favorable finite benchmark does
not establish the full claim. Regime coverage, discretization error, physical
generality, and extrapolation still require specialist judgment, so the score
is normally 8 or 9.

#### Ordinary theorem proof

“Prove theorem T for every admissible parameter” as an ordinary
natural-language proof scores 10. If the question requires a Lean 4 proof
with the statement pinned by the contract, the
Lean program is the submitted result and scores 0 because the pinned kernel
checks it.

#### Attractive question that later work resolved

A 2018 question asking for a decoder that outperforms small-set-flip has an
excellent executable-answer shape. Later BP+SSF and SSF+PAL work materially
answered that existential comparison. It is retained as a status-control case,
not dispatched as a current open problem.

These examples illustrate why importance, current status, verification
difficulty, and CI must remain separate judgments.

## What one generated problem repository contains

Every accepted problem is compiled into an independently versioned,
contract-first repository:

```text
ORP-0001-example-problem/
  problem.json         # canonical Problem Contract
  README.md            # deterministic English rendering
  README.zh-CN.md      # optional faithful Chinese translation
  .gitlab-ci.yml       # only when a substantive automatic check exists
  verify/              # only when that check needs problem-specific code
  examples/ or data/   # only when the scientific problem needs them
```

The campaign and companion pool retain the larger audit dossier, provenance,
ranking fields, and compilation hashes. They are not copied into the solver
repository. `problem.json` is the source for the problem's public scope and
acceptance boundary; `README.md` is regenerated from it.

The README renders these sections:

1. `Background`
2. `Problem Statement`
3. `Scientific Significance`
4. `Previous Progress`
5. `Solution Difficulty`
6. `Verification Contracts`
7. `Verification Difficulty`
8. `References`
9. `Problem Decomposition`

The complete field definitions and scoring rubric are in
[`docs/problem-schema.md`](docs/problem-schema.md), with the executable JSON
Schema at [`schemas/problem-contract.schema.json`](schemas/problem-contract.schema.json).

The same contract drives all downstream operations:

```bash
# Validate one contract.
uv run discovery contract validate ./problem.json

# Regenerate its README deterministically.
uv run discovery contract render ./problem.json --out ./README.md

# Ask an independent Agent to review the contract itself.
uv run discovery contract review ./problem.json --out ./review.json

# Rewrite the complete contract from an input prompt, then revalidate it.
uv run discovery contract rewrite ./problem.json \
  --prompt "Clarify the acceptance boundary without changing the problem." \
  --out ./problem.rewritten.json

# Materialize, initialize, create, and push a private GitLab repository.
uv run discovery contract publish ./problem.json \
  --out-dir ./ORP-0001-example-problem \
  --gitlab-project my-group/ORP-0001-example-problem
```

### What the background and problem statement must explain

This section must do more than repeat the title or quote an open-question
sentence. It should read like the opening of a research paper followed by a
clear problem statement.

Begin with the scientific context: what system, phenomenon, theory, method, or
application is being studied, and why researchers care about it. Introduce
specialist terms and acronyms when they first appear, at a level that lets a
researcher outside the narrow specialty follow the discussion. Explain the
relevant result, empirical observation, technical limitation, or disagreement
in prior work from which the open question arises. Only then state the
unresolved problem and distinguish it from nearby questions that would not
answer the same scientific need.

The necessary detail is discipline-dependent. A mathematical problem may need
definitions and equations. A theoretical-physics problem may need a model,
Hamiltonian, observable, and regime. An experimental problem may instead need
the biological or material system, intervention, measurement method, and
scientific endpoint. A computational problem may need the task, data source,
baseline, evaluation protocol, and operating constraints. Descriptive or
observational fields may need the population, evidence source, terminology,
and competing interpretations. None of these is a universal form.

Equations, parameter ranges, quantifiers, datasets, assays, and benchmarks
should be included when they are genuinely part of understanding that problem,
not because a schema demands them. A bare phrase such as “use the operator in
Eq. (45),” an unexplained acronym, or “improve the state of the art” is not
enough. Conversely, an experimental or descriptive question should not be
forced into artificial mathematical notation.

The resulting prose should explain the problem's intellectual path and precise
meaning, but should not include the solver's private reasoning, prescribe a
favored solution method, or duplicate the later `Verification Difficulty` and CI
sections.

New cross-disciplinary records use `ORP-*` identifiers. Existing `OMP-*`
identifiers are immutable legacy IDs.

## Installation

### Requirements

- Python 3.11 or newer;
- [`uv`](https://docs.astral.sh/uv/);
- an authenticated `codex` CLI with `codex exec`;
- Gaia CLI available on `PATH` for exploratory LKM retrieval;
- a Bohrium LKM access key for direct paper-graph ingestion.

Clone and install:

```bash
git clone https://github.com/kunyuan/open-research-discovery.git
cd open-research-discovery

uv sync --dev
```

Verify the external tools:

```bash
codex --version
codex login status
gaia --version
```

Configure the LKM key without writing it into the repository:

```bash
export LKM_ACCESS_KEY="<your Bohrium access key>"
```

Then run the package checks:

```bash
make check
```

The access key must never be committed, logged, embedded in a campaign file,
or included in an agent prompt.

## Configure a campaign

Start from the supplied example:

```bash
cp config/example-campaign.yaml my-campaign.yaml
```

A minimal campaign looks like:

```yaml
schema_version: 1
name: quantum-information-open-problems

domains:
  - id: quantum-information
    query: >-
      Identify scientifically important, concrete open research problems in
      quantum information with enough context to define an unambiguous answer
      and verification contract.
    seed_papers: []

strategies:
  - type: lkm_explicit_open_questions
  - type: lkm_topic_decomposition
    search_groups: 4
    sources: [lkm, web]
    max_candidates_per_domain: 12

selection:
  target_problem_count: 6
  shortlist_multiplier: 2

limits:
  papers_per_domain: 10
  questions_per_domain: 100
  lkm_timeout_seconds: 60

agents:
  model: ""
  codex_executable: codex
  networked_sandbox: workspace-write
  network_access: true
  workers: 3
  sandbox: read-only
  timeout_seconds: 3600

outputs:
  runs_root: ./work/campaigns
  problem_root: ./work/problems
  pool_root: ""
```

Output paths are resolved relative to the campaign file, not relative to the
current shell directory.

### Important configuration fields

| Field | Meaning |
| --- | --- |
| `domains[].id` | Stable domain key used in run artifacts |
| `domains[].query` | Broad scientific topic shared by the configured discovery strategies |
| `domains[].seed_papers` | Optional known paper IDs, DOIs, or exact titles |
| `papers_per_domain` | Maximum paper candidates returned by Discovery |
| `questions_per_domain` | Maximum explicit LKM open-question records retained per domain |
| `strategies[].type` | Seed producer: strict LKM explicit questions or evidence-grounded topic decomposition |
| `strategies[].search_groups` | Independent CDQ-style search briefs for topic decomposition |
| `selection.target_problem_count` | Final maximum `N`; omitted means no portfolio cap |
| `selection.shortlist_multiplier` | Research shortlist multiplier, at most 2, so no more than `2N` candidates receive Research |
| `agents.model` | Codex model override; blank uses the configured default |
| `agents.workers` | Maximum concurrent agents in any parallel region (domain Discovery, candidate Triage, Research→Review audit chains), from 1 to 16 |
| `agents.networked_workers` | Maximum concurrent networked agents (Discovery, Research) shared across all parallel regions, from 1 to 16; defaults to `agents.workers` |
| `agents.retries` | Retries after a failed agent invocation, from 0 to 5; defaults to 1. Output contract failures are never retried |
| `agents.retry_backoff_seconds` | Base seconds for exponential retry backoff (`backoff * 2^attempt`); defaults to 5 |
| `networked_sandbox` | Sandbox used by Discovery and Research |
| `sandbox` | Non-networked sandbox used by Canonicalization, Triage, and Problem Review |
| `runs_root` | Resumable state and evidence artifacts |
| `problem_root` | Destination for generated one-problem repositories |
| `pool_root` | Companion pool repository; blank disables pool synchronization |

The default security model is intentional:

- Discovery and Research: `workspace-write` with network access;
- Canonicalization, Triage, and Problem Reviewer: non-networked `read-only`;
- headless agents ignore user-level Codex plugin/MCP configuration while
  retaining normal Codex authentication;
- no role requires `danger-full-access`.

## Recommended usage

Problem generation and benchmark work are separate modes. Unless the user
explicitly asks to construct or evaluate a benchmark, use the complete
discovery-to-repository campaign:

```bash
uv run discovery campaign run my-campaign.yaml \
  --run-id qinfo-full-001
```

Do not run `discovery benchmark build`, `predict`, `select`, `export`,
`evaluate`, or `score` as a prerequisite for problem generation.

### Optional: construct a screening benchmark

Use this separate workflow only when the user explicitly asks to build a
benchmark. It performs paper discovery, direct LKM extraction,
canonicalization, and Triage, but it does not commission the later-literature
Research and Problem Reviewer stages or create problem repositories.

```bash
uv run discovery benchmark build my-campaign.yaml \
  --run-id qinfo-screen-001 \
  --workers 3
```

Inspect the run:

```bash
uv run discovery campaign status \
  ./work/campaigns/qinfo-screen-001
```

Important artifacts include:

```text
work/campaigns/qinfo-screen-001/
  state.json
  source-open-questions.json
  canonicalization.json
  benchmark-triage-summary.json
  domains/
  candidates/
```

The Triage outputs are model predictions and sampling strata, not benchmark
gold.

If a run was interrupted:

```bash
uv run discovery benchmark refresh \
  ./work/campaigns/qinfo-screen-001 \
  --workers 3
```

Create a diversity-oriented draft selection:

```bash
uv run discovery benchmark select \
  ./work/campaigns/qinfo-screen-001 \
  --domain quantum-information \
  --per-domain 5 \
  --out ./work/qinfo-selection.json
```

Export label-free benchmark inputs:

```bash
uv run discovery benchmark export \
  ./work/campaigns/qinfo-screen-001 \
  --selection ./work/qinfo-selection.json \
  --out ./work/qinfo-screening-v1
```

Before freezing a real benchmark, add a neutral later-literature dossier and
obtain independent blind labels. Do not reuse the Triage prediction as gold.

### Default: run the complete problem lifecycle

Use a full campaign for ordinary problem discovery. Accepted candidates
undergo later-literature research, independent Problem Review,
problem-repository compilation, and optional pool synchronization.

```bash
uv run discovery campaign run my-campaign.yaml \
  --run-id qinfo-full-001
```

The full sequence is:

```text
Discovery (one agent per domain, parallel across domains)
-> direct LKM ingestion
-> canonicalization
-> parallel Triage of every canonical candidate
-> parallel candidate audit chains for every high/medium-importance candidate
   -> later-literature Research
   -> one independent Problem Review
-> deterministic serial repository compilation for accepted cases
-> optional pool synchronization and ranking
```

Every parallel region is bounded by `agents.workers`, and networked roles
(Discovery, Research) additionally share one campaign-wide semaphore capped
by `agents.networked_workers`. Within one candidate, Research always
completes before its Problem Review. Parallel results merge in configured
domain order and canonical candidate order, and compilation, problem-ID
allocation, pool synchronization, and ranking run only after the parallel
barriers, so completion timing cannot change merged outputs or problem IDs.

Check status:

```bash
uv run discovery campaign status \
  ./work/campaigns/qinfo-full-001
```

Resume safely:

```bash
uv run discovery campaign resume \
  ./work/campaigns/qinfo-full-001
```

Resume skips only stages whose input hash, schema/skill inputs, and output hash
still match. Do not edit `campaign.yaml` inside an existing run; start a new run
for changed configuration.

Retry one stage after inspecting a failure or `needs_revision` verdict:

```bash
uv run discovery case retry \
  ./work/campaigns/qinfo-full-001 \
  CAN-0123456789AB \
  research

uv run discovery campaign resume \
  ./work/campaigns/qinfo-full-001
```

Retryable stages are:

```text
triage | research | problem-review | compile
```

The pipeline never automatically loops a Reviewer revision back into
Discovery.

To revise many candidates at once, defer each retry and let a single resume
execute them through the parallel candidate audit instead of running each
research chain synchronously inside the retry command:

```bash
for candidate in CAN-0123456789AB CAN-0123456789CD CAN-0123456789EF; do
  uv run discovery case retry \
    ./work/campaigns/qinfo-full-001 \
    "$candidate" \
    research \
    --defer
done

uv run discovery campaign resume \
  ./work/campaigns/qinfo-full-001
```

Each `--defer` call takes seconds and invokes no agent: it advances the
applied-feedback snapshot, invalidates the stage and its downstream stages,
and marks the candidate `retry_requested`. The following resume re-checks
scientific importance for every deferred candidate, records low-importance
cases in `triage-deferred.json`, and audits every high- or medium-importance
candidate in parallel with the accumulated reviewer feedback applied.

### Optional: evaluate a frozen screening benchmark

Run this separate workflow only when the user explicitly asks to evaluate a
benchmark. Evaluation is offline and repeatable; it must not repeat discovery,
LKM search, web search, or later-literature research.

Validate a dataset with gold labels:

```bash
uv run discovery benchmark validate \
  /path/to/screening-v1
```

For a draft containing only inputs:

```bash
uv run discovery benchmark validate \
  /path/to/draft-screening-v2 \
  --inputs-only
```

Run one ephemeral, read-only, non-networked Codex Triage process per case:

```bash
uv run discovery benchmark evaluate \
  /path/to/screening-v1 \
  --out /path/to/evaluation-run \
  --workers 3
```

Resume an interrupted evaluation and reuse schema-valid predictions:

```bash
uv run discovery benchmark evaluate \
  /path/to/screening-v1 \
  --out /path/to/evaluation-run \
  --workers 3 \
  --resume
```

Score the predictions:

```bash
uv run discovery benchmark score \
  --predictions /path/to/evaluation-run/predictions \
  --gold /path/to/screening-v1/gold \
  --out /path/to/evaluation-run/report.json
```

The report separates:

- importance accuracy;
- verification-difficulty exact accuracy and mean absolute error;
- CI-buildability accuracy;
- research-dispatch precision and recall;
- unsafe dispatch false positives.

The benchmark measures screening judgment, not the ability to solve the
research problems.

## Use the strict single-paper extractor

When you already know a paper ID, DOI, or exact title, use the deterministic
extractor directly:

```bash
uv run python scripts/extract_paper_open_questions.py \
  --doi "10.48550/arXiv.2208.08547" \
  --raw-out /path/to/problem-pool/inbox/run-001/paper-graph.json \
  --out /path/to/problem-pool/inbox/run-001/open-questions.json
```

Equivalent identifier options are available for paper ID and title; inspect
the current CLI help:

```bash
uv run python scripts/extract_paper_open_questions.py --help
```

Always preserve `--raw-out` for evidence-bearing work. The derived
`open-questions.json` is not a replacement for the complete API response.

## Create one problem repository manually

The full campaign creates a validated `problem.json` automatically. For a
manual problem, author the same contract using
[`docs/problem-schema.md`](docs/problem-schema.md), then validate and render it:

```bash
uv run discovery contract validate ./problem.json
uv run discovery contract render ./problem.json --out ./README.md
```

The generated README is entirely English. Use `$...$` for inline mathematics
and `$$...$$` for display mathematics; do not use `\(...\)` or `\[...\]`.
Edit `problem.json`, not the generated README, when changing scope or
acceptance criteria.

To publish it, use `discovery contract publish`; the command validates the
contract, materializes `problem.json` and `README.md`, initializes one Git
repository, creates the named GitLab project, and pushes `main`. It defaults
to private visibility. Add problem-specific verifier files later only when a
`ci_contract` can actually be implemented.

## Work with a companion problem pool

```bash
uv run python scripts/rank_problem_pool.py \
  --catalog ../open-research-problem-pool/pool/catalog.jsonl \
  --lane research-ready
```

## Repository model

The canonical public source of each generated problem repository is
`problem.json`. It is validated against the versioned Problem Schema. The
entirely English `README.md` is its deterministic human-facing projection;
review and rewrite operate on the same contract rather than maintaining a
second interpretation.

The repository is intentionally minimal:

```text
problem.json        # canonical scope and acceptance contract
README.md
README.zh-CN.md      # optional faithful translation; README.md remains canonical
.gitlab-ci.yml       # only when a substantive automated check exists
verify/              # only when that check needs problem-specific code
examples/ or data/   # only when the problem itself needs them
```

Do not copy the internal `problem.yaml`, schemas, reviewer configuration, or a
separate status file into the research repository. The companion pool and
campaign run retain larger structured records for ranking, deduplication,
provenance, and deterministic synchronization.

`Background` and `Problem Statement` should form a coherent academic account of the research problem,
not a metadata form. Start from the scientific setting and the history or
prior result that gives rise to the question; explain specialist terminology
and acronyms; then state the unresolved target in the natural language of the
field. Include equations, experimental conditions, materials, organisms,
observables, datasets, baselines, evaluation procedures, or other details only
when they are needed to understand that particular problem. Do not force
mathematics-specific notation onto other disciplines. Citations provide deeper
context and provenance, but an unexplained term or external equation reference
cannot substitute for the problem explanation itself.

`Verification Contracts` states the acceptance boundary once per answer type.
Each `ci_contract` contains only scientifically meaningful mechanical checks.
`Verification Difficulty` records one 0–10 score over all answer types after
those checkable parts have been removed. A build that merely validates file
layout is not scientific CI, and a
problem without a useful automatic predicate should rely openly on Reviewer
judgment.

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

Discovery, topic evidence search, and Research are the networked
headless-Codex roles. They run
inside the isolated checkout with `workspace-write` plus network access so
Gaia CLI can reach LKM. Canonicalization, Triage, and Problem Reviewer stay
`read-only`; the pipeline does not require `danger-full-access`.

After Problem Reviewer acceptance, the deterministic compiler runs only when
the audited candidate still has a nonempty open core, medium or high
importance, and an unambiguous verification contract. Verification difficulty
is retained as a 0-10 score, not a threshold. It stores the structured
record in the campaign/pool, renders the canonical English README into an
independent local Git repository, and creates the initial commit. A faithful
`README.zh-CN.md` may be added as an optional translation, but is not a second
scientific specification. Closed or otherwise ineligible
audits remain in the campaign as `audited_out`. Optional CI files are added
only when a real problem-specific checker exists.

## Companion repository layout

The tools accept explicit paths, so no fixed local layout is required. A
convenient sibling layout is:

```text
workspace/
  open-research-discovery/
  open-research-problem-pool/
  problems/
    ORP-0001-example/
    ORP-0002-another-example/
```

To synchronize automatically during a full campaign, set:

```yaml
outputs:
  pool_root: ../open-research-problem-pool
```

Validate an external pool:

```bash
uv run python scripts/validate_pool_repository.py \
  ../open-research-problem-pool
```

Query its generated catalog:

```bash
uv run python scripts/query_pool.py \
  --catalog ../open-research-problem-pool/pool/catalog.jsonl \
  --domain quantum
```

Rank one lane:

```bash
uv run python scripts/rank_problem_pool.py \
  --catalog ../open-research-problem-pool/pool/catalog.jsonl \
  --lane research-ready
```

The public toolkit accepts explicit external paths and has no hidden
dependency on a repository-local `pool/`, `registry/`, `inbox/`, or `reports/`
directory.

## Run artifacts and recovery

Each campaign is a resumable state machine:

```text
campaigns/<run-id>/
  campaign.yaml
  state.json
  source-open-questions.json
  canonicalization.json
  triage-deferred.json
  benchmark-triage-summary.json
  ranking.json
  domains/<domain-id>/
    source-papers.agent.json
    source-papers.json
    source-open-questions.json
    evidence/lkm/
    events/
  candidates/<candidate-id>/
    source-papers.json
    source-open-questions.json
    canonicalization.json
    triage.json
    assessment.json
    research-feedback-applied.json
    problem-review-verdict.json
    problem-review-feedback-history.json
    compile.json
    problem.yaml
    evidence/lkm/research-evidence.json
    evidence/web/research-evidence.json
    events/
```

Every headless-agent response is constrained by a checked JSON schema. Stage
metadata records:

- input and output hashes;
- prompt, schema, and skill hashes;
- model and tool versions;
- sandbox and network policy;
- attempts, timestamps, events, stderr, and exit code.

Workers write different candidate artifacts. One in-process ledger serializes
atomic `state.json` replacements. Do not run two mutating CLI commands against
the same campaign directory at the same time.

## Admission and ranking

The deterministic publication and solver-dispatch gate is:

```text
current-open surviving core
AND importance in {high, medium}
AND an unambiguous answer and verification contract
```

CI status is then used only as a bonus:

```text
implemented
> partial
> pseudocode
> Solution-Reviewer-only (manual-only)
> blocked
```

The expected result must faithfully answer the surviving core. A checkable
special case, favorable instance, or improved lower bound does not count as a
complete answer to a broader source question.

## Troubleshooting

### `LKM_ACCESS_KEY is not set`

Set the environment variable in the shell or execution environment that starts
the pipeline. Do not place it in YAML or commit it.

### LKM returns HTTP success but no usable result

Inspect the response-body `code`. A nonzero LKM business code is a failed
lookup. Preserve the response and retry by paper ID, DOI, then exact title.

### Gaia returns an attractive `question` hit

Treat it only as a paper lead. Recover the containing paper identifier and run
the direct paper-graph extractor. Do not create a source question from Gaia's
mixed question scope.

### A problem is labelled `uncertain`

Absence of a discovered solution is not enough for `still_open`. Improve the
same-core literature coverage, citation chain, aliases, and adjacent-result
analysis, then explicitly retry the Research stage.

### Headless Codex failed

Inspect the candidate's `events/*.stderr.log`, stage metadata, and schema
validation error. Repair the external dependency or prompt/schema issue, then
retry the exact stage and resume.

### Resume refuses a modified campaign

Campaign configuration is hashed at creation. Restore the original file or
start a new run. This prevents silent mutation of a scientific workflow.

### CI is green but the problem is not solved

Read the candidate's internal CI status in the campaign or companion pool and
the relevant `verification_contract.*.ci_contract` in `problem.json`. If the
problem repository contains `.gitlab-ci.yml` and `verify/`, inspect the exact
predicate implemented there. Structural checks, partial replays, and CI
pseudocode are intentionally distinguished from substantive acceptance.

## Repository guide

- [`docs/discovery-pipeline.md`](docs/discovery-pipeline.md): detailed control
  and data flow;
- [`docs/screening-benchmark.md`](docs/screening-benchmark.md): dataset
  construction, no-leakage evaluation, and scoring;
- [`docs/verification-difficulty-casebook.md`](docs/verification-difficulty-casebook.md):
  the 0–10 rubric and boundary examples;
- [`config/example-campaign.yaml`](config/example-campaign.yaml): minimal
  campaign configuration;
- [`config/benchmark-positive-three-fields.yaml`](config/benchmark-positive-three-fields.yaml):
  mathematics, physics, and computational-science benchmark seed;
- [`schemas/`](schemas/): campaign, stage, problem, and benchmark contracts;
- [`template/`](template/): generated problem-repository skeleton;
- [`.agents/skills/`](.agents/skills/): evidence-search, extraction, and ranking
  policies;
- [`tests/`](tests/): unit and integration coverage.

## Development

Run the full validation suite:

```bash
make check
```

Or run tests directly:

```bash
uv run pytest
uv run python scripts/validate.py
```

When changing the pipeline:

1. preserve the strict `data.papers[].open_questions` boundary for explicit
   origins and the contextual anchor boundary for derived origins;
2. keep corpus data outside the public toolkit;
3. update schemas and tests together;
4. preserve resumability and provenance hashes;
5. do not convert semantic scientific judgment into an artifact-type
   classifier;
6. validate both this repository and any affected companion pool before
   publishing.
