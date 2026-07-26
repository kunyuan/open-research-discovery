# {{TITLE}}

Problem ID: `{{PROBLEM_ID}}`

This repository is an independently versioned open research problem for
agent-assisted work.

## Exact question

Complete `problem.yaml` with the canonical statement, definitions, scope, and
the surviving open core after the resolution audit.

## Why it matters

Summarize the scientific dependency, benchmark, capability, or record that
would change if this problem is advanced.

## Current status

- Source open-question evidence: `evidence/`
- Later-resolution audit: `evidence/resolution-searches/`
- Annotated bibliography: `references/annotated.md`
- Current baseline: `baseline/known-results.yaml`

Do not call the problem currently open until `problem.yaml` contains a reviewed
resolution audit. Absence of a matching solution is `uncertain`, not
`still_open`.

If the audit finds major progress, read
`resolution_audit.progress_assessment`: the surviving core must be rewritten
and its importance and Solution Review scope reassessed before solver work.

## Agent quick start

```bash
uv sync
make check

# Put a candidate artifact in submission/, then:
make verify
```

The normative Solution Reviewer checklist is `verifier/solution-review.md`.
It records whether acceptance needs only result checking, result plus
derivation checking, or expert-intensive review, and gives an estimated review
time.
`verifier/ci.md` states the executable algorithm or exact pseudocode, runner,
timeout, and runtime estimate. Run `make ci` to execute all currently available
checks. A structural-only green result is not substantive acceptance.

Passing the declared protocol establishes local validity only. For experiments,
datasets, simulations, or models, accept only the population, regime, and
uncertainty encoded by the contract. Refresh the literature audit before
claiming novelty.

`problem.yaml` records only the Solution Review scope and optional CI status.
The Problem Reviewer predicts that scope from the exact question, expected
result, and acceptance boundary. After submission, the Solution Reviewer uses
the checklist to judge the actual result. No fixed artifact taxonomy
substitutes for either semantic judgment.
