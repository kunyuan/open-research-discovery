# Discovery pipeline

The pipeline has one output contract and four operational stages.

## 1. Discover

For every input topic, generate several distinct keyword families and search them independently. Supported source routes are:

- explicit LKM open questions;
- LKM and web topic search for source-grounded candidate questions.

Store quotations, surrounding context, identifiers, URLs, search queries, and retrieval dates in the campaign run directory. They are evidence for producing and reviewing a contract, not Problem Contract fields.

## 2. Formulate

One topic Agent consolidates the evidence into distinct candidate Problem Contracts. It must:

- read enough surrounding context to avoid misquotation or scope drift;
- align famous problems with authoritative formulations;
- allow justified generalization when it increases scientific value;
- avoid unnecessary restrictions introduced only to simplify checking;
- fix the scientific target and resolution boundary in the statement;
- split an indeterminate parent into verifiable subproblems when needed.

The output is validated against [`../schemas/problem.schema.json`](../schemas/problem.schema.json).

## 3. Review and rewrite

An independent headless reviewer receives the complete Problem Contract and source dossier. It evaluates the scientific artifact rather than literal equality with the source.

Review covers scientific soundness, attribution, scope, impact, previous progress, answer-type coverage, CI descriptions, and residual verification-difficulty calibration. The verdict and findings are stored next to the run, not added to the contract.

When revision is requested, the rewrite Agent receives the current contract, the review findings, and a specific instruction. It must preserve `problem_id` and return another schema-valid complete contract.

## 4. Publish

A validated contract produces exactly two scientific files:

```text
problem.json   # source of truth
README.md      # deterministic human-readable projection
```

The README sections are Background, Problem Statement, Scientific Significance, Answer Types, Verification Standard, Current Progress, and References.

Publication metadata such as repository URL, commit SHA, and visibility is returned by the publisher but is not inserted into `problem.json`.

## Acceptance boundary

There is no verification-difficulty threshold or pre-review clarity gate. Every generated candidate may enter independent review. A leaf is dispatchable only when its own statement and verification contracts make resolution decidable. A parent may instead delegate verification to explicitly listed subproblems.
