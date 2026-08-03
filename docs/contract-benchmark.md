# Problem Contract Benchmark

The benchmark measures whether a fixed candidate satisfies the complete public
Problem Contract, and whether an independent Reviewer detects every field-level
defect. It is not a screening benchmark and does not generate research
problems. Topic Main Agents and other discovery workflows remain the producers
under test.

## Boundary

The benchmark has one fixed unit: a candidate `problem.json` plus the frozen
evidence dossier available when that candidate was written. A generated output
enters the dataset only after it is frozen as a case. The benchmark never calls
the generator and never performs LKM or Web retrieval during evaluation.

The same case supports two measurements:

- producer quality is the independently adjudicated reference verdict on the
  frozen generated Contract;
- Reviewer quality is the agreement between a review prediction and that
  field-level reference review.

Do not use a reference Contract or text similarity as gold. More than one
wording may satisfy the same scientific contract.

## Reviewed fields

Every review covers all public schema fields:

- `schema_version`, `problem_id`, `parent_problem_id`, `subproblem_ids`;
- `title`, `abstract`, `background`, `references`, `previous_progress`;
- `problem_statement`, `scientific_significance`, `solution_difficulty`;
- `verification_contract`, `verification_difficulty`.

It also covers `cross_field_consistency` and `evidence_fidelity`. Each field is
labelled `pass`, `minor_issue`, or `major_issue`. An overall verdict is:

- `accept` only when every field passes;
- `rewrite` when the same scientific problem can be repaired from frozen
  evidence;
- `reject` when repair changes problem identity or requires new evidence.

Scientific significance is reviewed as part of the Contract: affected fields,
`high`/`medium`/`low`, and the concrete effect must all be justified.
Verification review covers every accepted answer type, its complete acceptance
contract, truthful CI scope, and the single residual 0-10 review-difficulty
score after mechanical work is excluded.

## Dataset layout

Corpus data stays in the private companion repository:

```text
contract-v0/
  manifest.json
  cases/<case-id>/input.json
  gold/<case-id>/gold.json
```

`input.json` contains the fixed candidate and frozen evidence, with no review
labels. `gold.json` contains a separately adjudicated field review. A single
review is `provisional`; two agreeing blind reviews may become `silver`; expert
adjudication may mark it `gold`. Disagreement remains `disputed`.

## Offline evaluation

Validate a dataset:

```bash
uv run discovery benchmark validate /path/to/contract-v0
```

Run one ephemeral, read-only, non-networked Reviewer per case:

```bash
uv run discovery benchmark evaluate /path/to/contract-v0 \
  --out /path/to/evaluation-run \
  --workers 4
```

Score Reviewer outputs against the separate reference directory:

```bash
uv run discovery benchmark score \
  --predictions /path/to/evaluation-run/predictions \
  --gold /path/to/contract-v0/gold \
  --out /path/to/evaluation-run/report.json
```

There is deliberately no `benchmark generate` command. Generation belongs to
the normal topic or campaign workflow.

## Metrics

Reports retain the individual cases and include:

- overall-verdict accuracy;
- acceptance-decision accuracy, which treats `rewrite` and `reject` as distinct
  exact verdicts but the same safe non-dispatch decision;
- exact field-label accuracy and per-field accuracy;
- issue-detection precision and recall;
- major-issue recall;
- unsafe accepts and unsafe rejects.

`unsafe_accept_count` is the primary safety metric: it counts incomplete
Contracts that the evaluated Reviewer would dispatch. Reports identify
provisional references and never present them as formal gold.
