# Discovery pipeline

The pipeline is a deterministic state machine around a few coarse-grained
headless Codex roles. Programs own control flow, provenance, schemas, retries,
IDs, compilation, synchronization, and ranking. Agents own the scientific
judgments that cannot be reduced to a stable rule.

```mermaid
flowchart TD
    C["Campaign configuration"] --> D["Codex Discovery Agent"]
    D -. "uses" .-> S["$research-evidence-search<br/>LKM / Web capability"]
    D --> P["Candidate papers<br/>paper_id / DOI / title"]
    P --> A["Program: direct LKM papers/graph API"]
    A --> O["Program: extract only<br/>data.papers[].open_questions"]
    O --> H["Program heuristic dedup<br/>+ Codex semantic canonicalization"]
    H --> T["Codex Triage Agent"]
    T -->|"not important or review boundary missing"| L["Low-priority inventory"]
    T -->|"important and operationally reviewable"| R["Codex Research Agent"]
    R -. "uses" .-> S
    R --> E["Status, major progress,<br/>surviving core, verification contracts"]
    E --> V["Independent Reviewer Agent"]
    V -->|"revise"| R
    V -->|"reject"| X["Retained rejected record"]
    V -->|"accept"| G["Program: compile problem repo"]
    G --> Y["Program: sync pool and deterministic rank"]
```

`$research-evidence-search` is a capability, not a data-flow or state node.
Discovery uses it to find papers. Research uses it to reconstruct later
evidence. After Research searches, its output goes directly to the structured
assessment and Reviewer; it never returns to Discovery.

## Two LKM boundaries

Source-question ingestion and evidence search have different trust contracts.

### Strict source-question ingestion

For every candidate paper, the program sends:

```http
POST https://open.bohrium.com/openapi/v1/lkm/papers/graph
accessKey: ...
Content-Type: application/json
```

The JSON body contains exactly one of `paper_id`, `doi`, or `title`. The
program requires response-body `code == 0`, preserves the raw response and
`trace_id`, and reads only:

```text
data.papers[].open_questions[]
```

It keeps each item's `content`, `id`, and `global_id`, plus its paper ID,
title, DOI, and the exact source path. Ordinary question, problem, subproblem,
motivation, and graph nodes cannot create candidates.

### Research evidence retrieval

Discovery and Research agents may use the web and Gaia CLI in any useful
order. Common Gaia commands are:

```text
gaia search lkm knowledge
gaia search lkm reasoning
gaia search lkm nodes
gaia search lkm package
```

LKM provides metadata and abstracts as well as compressed conclusion claims
and reasoning chains. The web may provide metadata, abstracts, preprints, and
partial or complete accessible text. Evidence therefore carries one honest
content-level label:

```text
metadata | abstract | compressed_claim | reasoning_chain |
partial_full_text | full_text
```

Retrieval rank is never treated as confidence. Search results from ordinary
LKM question nodes are evidence leads, not source open questions.

Gaia question scope is mixed and may return `problem`, `subproblem`,
`question`, and `open_question` provenance. Even an `::open_question` hit is
only a paper lead until the direct paper-graph endpoint confirms it under
`data.papers[].open_questions`. A nonzero LKM business code is a failed lookup,
not an empty extraction; the collector preserves it and retries the paper by
paper ID, DOI, then exact title.

Discovery and Research run as headless Codex roles in an isolated
`workspace-write` sandbox with network access enabled so Gaia CLI can reach
LKM. Canonicalization, Triage, and Reviewer stay in the configured
non-networked `read-only` sandbox. No role uses `danger-full-access`.

## Agent contracts

The Discovery Agent returns only candidate papers. The Triage Agent evaluates
intrinsic scientific importance and the boundary/cost of independent review;
it must not rank on solve difficulty, searchability, expected runtime to find
an answer, or probability of success.

The Research Agent directly returns:

- current status and confidence;
- what later literature does to the same core;
- major-progress classification;
- a precise surviving open core;
- post-progress importance;
- expected answer artifact and success condition;
- reviewer scope, ordered checklist, and time estimate;
- problem-specific CI code or pseudocode, runner, runtime, and timeout;
- source-tagged evidence.

The independent Reviewer checks those judgments. A `revise` verdict feeds only
the instructions and prior artifacts back to Research. The pipeline never asks
Discovery to repair a status or verification assessment.

## Screening benchmark construction

The screening benchmark evaluates an agent's judgments, not its ability to
solve the research problem. Preserve all canonical candidates, including
predicted failures and boundary cases. Generate one baseline prediction for
every candidate before commissioning expensive later-literature research:

```bash
uv run discovery benchmark predict <campaign-run-directory> --workers 3
```

This writes `benchmark-triage-summary.json` and per-candidate `triage.json`
files. These are model predictions, not gold labels. Stratify the benchmark
from passes, failures, and disagreements; then independently adjudicate the
selected cases. Do not allow the same agent output to serve as both prediction
and gold.

Workers write disjoint candidate artifacts. One in-process StageLedger
serializes atomic state-file replacements, so bounded parallel headless Codex
execution preserves one resumable `state.json`. Do not run two mutating CLI
commands against the same campaign directory at once.

Canonicalization atomizes explicitly separable targets from one source
`open_questions` record and preserves a candidate-specific exact excerpt. It
also records whether that excerpt explicitly requests a formal or
machine-checkable proof; ordinary proof questions record false.
Triage then chooses one scientifically sufficient solution route. Review scope
and CI buildability apply to that route, not indiscriminately to every possible
proof, refutation, construction, or algorithmic answer.

Triage enumerates every load-bearing acceptance obligation. Direct artifacts
and source-requested formal proofs are compatible with `result-only`; a
remaining derivation raises scope to `result-and-derivation`, and expert
judgment raises it to `expert-intensive`. The program validates exact source
support and scope consistency before accepting an agent artifact.
The semantic decision that an excerpt truly requests formal proof remains an
audited Canonicalization/Reviewer judgment; deterministic code verifies exact
provenance and downstream consistency rather than guessing from keywords.

For `result-only`, retain the declared final deliverable but hide the producing
solver's search and reasoning process and every undeclared auxiliary
explanation. The frozen problem, deliverable, trusted verifier, and frozen
reference data must still decide the same verdict. Lean, Coq, or Isabelle proof
code is the result only when the source question explicitly requests
formalization or a machine-checkable proof/certificate; it cannot be imposed
on an ordinary proof question. Counterexamples, exact solutions, certificates,
executable algorithms, and first-principles models retain their
source-grounded delivery contracts. Executable CI is a separate label and
does not by itself make a route result-only.

## State and recovery

Each run has this external, pool-compatible layout:

```text
campaigns/<run-id>/
  campaign.yaml
  state.json
  source-open-questions.json
  canonicalization.json
  low-priority.json
  ranking.json
  domains/<domain-id>/
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
    reviewer-verdict.json
    compile.json
    events/
```

`state.json` stores each stage's input and output hashes, schema and skill
hashes, prompt/model/tool metadata, attempt, timestamps, exit code, artifact
paths, and failure. Resume reuses a stage only when its recorded input and
output still match. A targeted retry invalidates the selected candidate stage
and its downstream stages.

## Deterministic completion

Agents never write the corpus. After schema validation and Reviewer acceptance,
the program compiles `problem.yaml`, source evidence, the reviewer checklist,
and CI pseudocode into one problem repository. It validates the repository,
synchronizes the explicitly configured companion pool, and applies the
deterministic ranking policy.

Ranking uses only scientific importance, reviewer scope, CI or bounded-review
feasibility, verification latency/resource ceiling, and current-open
eligibility. A problem-specific CI design is sufficient for the
`research-ready` lane; a checker must be implemented only for automatic
acceptance.
