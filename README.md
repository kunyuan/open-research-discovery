# Open Research Discovery

This repository turns one or more scientific topics into complete, source-grounded, and verifiable open-research Problem Contracts.

The design has one scientific artifact: [`problem.json`](schemas/problem.schema.json). Search traces, Agent logs, routing, rankings, and publication metadata are run artifacts, not fields in the Problem Contract.

## Minimal workflow

```text
topics
  → multi-source discovery (LKM open questions + topic search)
  → source-grounded research and formulation
  → problem.json
  → independent review / optional rewrite
  → deterministic README.md
  → GitLab solution repository
```

Each topic has one orchestrating Agent. Discovery workers may search different keyword families in parallel. The orchestrator consolidates distinct candidate problems and produces the contract. Independent review is a separate headless step, so it does not share the producing Agent's context.

## Problem Contract

The complete contract has exactly 14 top-level fields:

```text
schema_version
problem_id
parent_problem_id
subproblem_ids
title
abstract
background
references
previous_progress
problem_statement
scientific_significance
solution_difficulty
verification_contract
verification_difficulty
```

See [`docs/problem-schema.md`](docs/problem-schema.md) for the JSON format and scoring rules.

Important boundaries:

- `scientific_significance` records affected fields, a `high` / `medium` / `low` impact level, and the concrete effect. It has no numeric score.
- `verification_contract` is keyed by answer type. Each entry contains the complete acceptance contract and the part that can be executed mechanically as CI.
- `verification_difficulty` is one 0–10 score for residual human or Agent judgment after all mechanically checkable parts are removed. It is descriptive, not a publication threshold.
- A parent with listed subproblems may set `verification_contract` and `verification_difficulty` to `null`, delegating acceptance to its children.
- Workflow state, rankings, compute estimates, search evidence, and review verdicts remain separate run artifacts.

## Commands

Create a campaign configuration from one or more topics:

```bash
discovery campaign init \
  --topic "fermion sign problem" \
  --topic "exact solutions" \
  --out campaign.yaml

discovery campaign run campaign.yaml
```

Operate directly on a Problem Contract:

```bash
discovery contract validate problem.json
discovery contract render problem.json --out README.md
discovery contract review problem.json --out review.json
discovery contract rewrite problem.json \
  --prompt "Remove unnecessary restrictions without changing the scientific target" \
  --out rewritten.json
discovery contract publish problem.json \
  --out-dir ./solution \
  --gitlab-project group/project \
  --visibility private
```

`render` is deterministic: the README is a projection of `problem.json`, not a second source of truth.

## Contract benchmark

The quality benchmark consumes completed Problem Contracts and their README projections. It checks schema validity and citation metadata mechanically, then supports blind offline review of:

- scientific soundness and internal consistency;
- faithful but possibly motivated generalization of source problems;
- a determinate resolution boundary;
- scientific significance without impact inflation;
- complete verification contracts and truthful CI descriptions;
- calibration of the residual verification-difficulty score.

```bash
discovery benchmark build --manifest ./solution/problem.json --out ./quality-data
discovery benchmark evaluate ./quality-data --out ./quality-run --workers 4
discovery benchmark score --dataset ./quality-data --predictions ./quality-run/predictions
```

The reviewer receives frozen evidence and no producer context. A source formulation need not be copied literally: a scientifically justified generalization is allowed, but it must remain attributable, precise, and decisively verifiable.

## Development

```bash
uv run pytest -q
```
