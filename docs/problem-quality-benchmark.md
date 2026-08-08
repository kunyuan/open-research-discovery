# Problem Contract benchmark

This benchmark evaluates whether a producer or reviewer can create or audit a complete, self-consistent, scientifically meaningful, and verifiable Problem Contract.

## Evaluation object

The input is a schema-valid `problem.json`, its deterministic README projection when available, and frozen citation metadata extracted from `references`. Producer traces and pipeline verdicts are excluded from the blind reviewer input.

## Review dimensions

Each dimension is scored from 0 to 3:

- `citation_accuracy`: referenced identifiers resolve and their metadata match the cited works;
- `scientific_soundness`: background, previous progress, statement, and significance form a scientifically coherent target;
- `scope_fidelity`: the formulation is accurately related to its sources, justified generalizations are sound, and the resolution boundary is determinate;
- `verification_executability`: all accepted answer types have decisive contracts, CI covers only mechanical checks, and the residual difficulty score is calibrated;
- `evidence_relevance`: references support the formulation, progress, and claimed field-level impact without inflation.

Scores mean:

- `3`: sound, no defect found;
- `2`: minor repair that does not undermine the claim;
- `1`: significant defect requiring revision;
- `0`: the central claim of the dimension fails.

Overall grades are A (publishable), B (minor revision), or C (major defects).

## Mechanical checks

Before blind review, the builder validates the Problem Contract schema, freezes DOI/arXiv/URL metadata found in `references`, checks citation resolution and obvious metadata mismatches, validates README structure, and flags near-duplicate problem statements.

These checks do not decide scientific correctness. They provide reproducible evidence to the independent reviewer.

## Commands

```bash
discovery benchmark build --manifest problem.json --out quality-data
discovery benchmark validate quality-data --inputs-only
discovery benchmark evaluate quality-data --out quality-run --workers 4
discovery benchmark score --dataset quality-data --predictions quality-run/predictions
```
