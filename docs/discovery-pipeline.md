# Discovery Pipeline

This document specifies the schema-v2 problem-generation path. Schema-v1 is
retained only for compatibility with existing campaigns and frozen benchmarks.

## Lifecycle

```mermaid
flowchart LR
    T["Topics"] --> D["Discovery"]
    D --> L["Dedicated LKM open questions"]
    D --> Q["Contextual topic-search leads"]
    L --> U["Unified source records"]
    Q --> U
    U --> C["Source-faithful canonicalization"]
    C --> I["Intrinsic triage"]
    I -->|"needs decomposition"| S["Materialize child candidates"]
    S --> I
    I -->|"clear + important"| B["Per-topic audit budget"]
    B --> R["Later-literature research"]
    R --> V["Independent Problem Review"]
    V -->|"clear verification"| G["Compile one solution repo per problem"]
    V -->|"unfaithful or unclear"| X["Revise or withhold"]
```

## 1. Topic input

Each topic has a stable ID, title, query, enabled source routes, optional seed
papers, and optional books or other references. Multiple
topics may run concurrently. Completion order never changes deterministic
merge or problem-ID order.

Campaign execution defaults to four ordinary workers and four network-enabled
workers. These are upper bounds: a stage with fewer independent tasks uses only
the available parallelism.

## 2. Discovery and source ingestion

### Dedicated LKM route

Discovery returns paper identifiers. The deterministic pipeline calls the
direct paper-graph endpoint, requires response-body `code == 0`, preserves raw
responses and identifier attempts, and ingests only
`data.papers[].open_questions`. Every schema-v2 paper candidate also carries an
abstract-level-or-better context summary and source intent, so canonicalization
does not interpret the dedicated question sentence in isolation.
The dedicated field proves LKM provenance, not verbatim author attribution;
Research checks the extracted formulation against accessible paper text before
the final repository describes who posed it.

### Topic-search route

Discovery may search LKM and the web or inspect configured references. A lead
must include a verbatim excerpt, surrounding context, source intent, derivation
rationale, source metadata, and evidence-level labels. The exact excerpt must
be a substring of the preserved context. A lead is not marked as an explicit
open question.

Both routes become unified `source_records`. Each retains its source kind and
whether openness was explicitly declared.

## 3. Context fidelity and canonicalization

Canonicalization consumes the complete source record, not a search snippet.
For inferred leads it must inspect the excerpt, context, intent, and derivation
together. It may merge equivalent formulations, but not related questions.

The stage is source-faithful first. It preserves the natural generality,
objects, assumptions, and quantifiers of the literature problem. It does not
add finite-size, parameter, geometry, method, or answer-form restrictions to
make verification easier. Genuinely conjunctive source questions may be split
along source-supported boundaries; a restricted special case remains a named
derived problem and never replaces its parent. Famous or named problems use a
primary or standard authoritative formulation. Each candidate records a parent
theme, descriptive answer types, verification plan, and formulation rationale.
Candidate-specific excerpts are checked against the preserved source text.
The pipeline derives each cluster's `topic_id` from its source records and
rejects cross-topic clusters. A narrower method or theme belongs in
`parent_theme`; it never creates a new repository container.

## 4. Intrinsic triage

Triage evaluates the source-era problem before the expensive status audit. It
records:

- coarse importance plus scientific significance from 0 to 10;
- a specific significance rationale;
- expected result and descriptive answer types;
- verification clarity and concrete standard;
- proposed subproblems (empty when clarity is `clear`; at least one, with
  `complete` or `partial` parent coverage, when clarity is
  `needs_decomposition` or `unverifiable` — the conditional rule is enforced
  by pipeline validation, since agent structured output cannot express it);
- verification difficulty from 0 to 10;
- CI status independently.

When triage returns `needs_decomposition`, the deterministic pipeline may turn
source-supported components into child candidates, preserves the parent's
complete source trail, and triages the children again up to the configured
depth. A convenient restricted instance is not a valid decomposition of a
general question. Proposed subproblems that are not materialized within the
depth frontier are appended to the persistent topic queue (section 6) instead
of being dropped. Only
high- or medium-importance candidates with a clear verification contract
proceed to later-literature research. An optional per-topic audit budget ranks
those clear candidates by scientific significance and coarse importance.
Verification difficulty never blocks that audit and never gates schema-v2
publication.

## 5. Research and Problem Review

Research searches LKM and the web adaptively for closure, refutation, special
cases, improved bounds, reformulations, and continuing treatment of the same
core. It must distinguish direct support from inference and may not use a new
agent-created solution as literature evidence.

The schema-v2 Research stage returns one JSON object
(`schemas/stages/research-topic.schema.json`) holding two artifacts plus
structured decomposition fields:

- `problem`: a problem draft whose nested sections (title, question,
  resolution_audit, importance, research_triage, discovery_contract,
  solution_review_contract, ci_contract, compute) mirror
  `schemas/problem.schema.json` (schema v4). Every mechanical field — ids,
  status, schema_version, topic_id, repository, source records,
  `question.lineage`, `resolution_audit.checked_at`, the conclusion
  rationale/literature_treatment strings, the `progress_assessment` decision,
  reassessment flags and derived_problem_ids, and the research_triage
  priorities, route, and rationale — is derived or injected by the
  deterministic pipeline and must not appear in the agent output.
- `report_markdown`: a free-form English audit narrative carrying what the
  earlier flat assessment called `literature_treatment` and
  `status_rationale` — the literature lineage, how later work treats the
  problem, the importance argument, and an explicit statement of search
  coverage and remaining uncertainty. The pipeline writes it to the candidate
  directory as `report.md` and shows it verbatim to the Problem Reviewer.
- `proposed_subproblems` and `decomposition_parent_coverage`: structured
  subproblem proposals conditional on `verification_clarity` exactly as in
  triage (section 4); every proposed subproblem enters the persistent topic
  queue (section 6).

The validated draft is stored as `candidates/<candidate-id>/research.json`.
Schema-v1 campaigns still use the legacy flat assessment schema and write
`assessment.json` instead.

The progress decision is never an agent judgment. The pipeline derives it
mechanically from the audit's status, `major_progress_found`, `effect`, and a
mechanical formulation diff between the input candidate and the audited draft:

- no major progress: `continue` for a surviving open target (`still_open` or
  `partially_resolved`), `unassessed` for `uncertain` status, `stop` for
  `resolved` or `refuted`;
- major progress: `stop` when the target is resolved/refuted or the effect
  resolves/refutes it; `unassessed` when status or effect is `uncertain`; a
  contract error when the effect is `none`; otherwise `rewrite-core` when the
  formulation diff changed, `continue` when it did not.

The same mechanical diff flags a changed formulation for the publication gate
and the Problem Reviewer's `scope_change` check; the frozen no-progress fields
(reassessment flags, derived_problem_ids) are pipeline-fixed as well. When
later work changes the core, Research re-scores significance and verification
from scratch. The Problem Reviewer independently checks source fidelity,
authoritative alignment for famous problems, absence of artificial
restrictions, context sufficiency, status, significance, answer types,
verification clarity and standard, score calibration, and evidence honesty.

Publication requires:

```text
current open core
AND high or medium importance
AND verification_clarity == clear
AND nonempty verification_standard
AND independent reviewer acceptance
```

There is deliberately no `verification_difficulty <= threshold` clause.

A candidate that survives the audit but remains too general or unverifiable is
not discarded: its required `proposed_subproblems` flow back into the
persistent topic queue so a later campaign can pose the refined questions.

## 6. Persistent topic queue

Every schema-v2 run root retains `<runs_root>/topic-queue.jsonl`, one JSON
entry per line conforming to `schemas/topic-queue.schema.json`. The queue
implements three behavior rules:

1. Output follows the schema strictly. `verification_clarity: clear` requires
   an empty `proposed_subproblems` and `decomposition_parent_coverage:
   not_applicable`; `needs_decomposition` or `unverifiable` requires at least
   one subproblem and `complete` or `partial` coverage. Agent structured
   output cannot express such conditionals, so the deterministic pipeline
   enforces them after the agent returns.
2. Retention over rejection. `unverifiable` is not a terminal verdict: a
   literature-grounded scientific question that is not yet specific enough is
   decomposed into subproblems and queued, never silently dropped. The same
   holds for research-stage candidates that remain too general after the
   audit.
3. Lifecycle. The pipeline appends entries as `pending` with a stable
   `queue_id` (`q` plus 16 lowercase hex characters), decomposition depth,
   lineage, and source keys. The next campaign for the topic replays pending
   entries into canonicalization as `queue:<queue_id>` derived-subproblem
   source records — whose source text is the queued statement — and marks
   them `consumed` with the consuming run id. Dedicated LKM `open_questions`
   records remain the highest-priority source; queued entries retain
   decomposition work across runs and never replace direct sources.

## 7. Solution-repository compilation

The compiler allocates a stable ORP ID and writes one README-first solution
repository for every accepted problem. `topic_id` remains grouping metadata, so
related repositories can be indexed together without forcing different
questions into a shared specification. Every README has exactly seven ordered
top-level sections: Background, Problem Statement, Scientific Significance,
Answer Types, Verification Standard, Current Progress, and References. It also
preserves the exact supporting excerpt and the dated literature audit. Internal
YAML records remain in campaign and pool storage.

Compilation is deterministic and refuses to overwrite an untracked or manually
modified solution repository. Each accepted problem receives its own Git
history, so updating one question cannot change a sibling's scientific contract.
The orchestrator first reserves ORP IDs in stable candidate order, then compiles
the independent solution repositories in parallel. Worker completion order never
changes the ID or summary order. Pool synchronization remains a serial barrier
after every compile worker has finished.

## 8. Pool and ranking

The pool retains one structured record per ORP. `topic_id` groups related
solution repositories without making them share a README or acceptance contract.

Ranking prioritizes:

1. current-open status;
2. scientific significance;
3. coarse importance;
4. verification difficulty and CI as secondary reviewer/scheduling metadata.

No ranking rule may treat easy verification as scientific value.

## 9. Reliability

The ledger hashes inputs, prompts, schemas, skills, and outputs. Cached stages
are reused only when their inputs match. Agent retries clear stale structured
output before invocation. Timeout handling terminates the whole process group.
Agent stages run through a configurable headless backend (`agents.backend`):
`codex` enforces the output schema via structured output inside an OS sandbox;
`kimi` (Kimi Code CLI headless mode) carries the schema in the prompt and
enforces it by post-hoc parsing and validation, with no sandbox — role
isolation then relies on environment sanitization alone. In both backends,
output-contract failures are never retried.
An exclusive, same-thread-reentrant file lock serializes `run`, `resume`, and
`retry` mutations for one run directory across processes; a process that waited
for the lock refreshes newer on-disk state before writing. Parallel discovery,
triage, audit, depth-frontier decomposition, and solution compilation outputs
merge in configured order.
The summary separately reports canonical candidates, active decomposition
leaves, generated children, and candidates deferred by the audit budget.

## 10. Benchmark separation

`discovery benchmark ...` is an explicit dataset/evaluation workflow. It is
never a prerequisite for `discovery campaign run`. Frozen schema-v1 benchmarks
may preserve their historical threshold labels for reproducibility; those
labels do not control schema-v2 publication.
