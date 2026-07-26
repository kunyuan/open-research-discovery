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
and its importance and verification profile reassessed before solver work.

## Agent quick start

```bash
uv sync
make check

# Put a candidate artifact in submission/, then:
make verify
```

For an `llm-reviewable` problem, follow the bounded checklist named by
`discovery_contract.verification_profile.protocol` instead of pretending that
the template `make verify` stub is an executable proof checker.

The normative reviewer-agent checklist is `verifier/review.md`. It classifies
whether acceptance needs only result checking, result plus derivation checking,
or expert-intensive review, and gives an estimated review time.
`verifier/ci.md` states the executable algorithm or exact pseudocode, runner,
timeout, and runtime estimate. Run `make ci` to execute all currently available
checks. A structural-only green result is not substantive acceptance.

Passing the declared protocol establishes local validity only. For experiments,
datasets, simulations, or models, accept only the population, regime, and
uncertainty encoded by the contract. Refresh the literature audit before
claiming novelty.

`problem.yaml` must label the verification mode. A bounded LLM checklist is a
valid protocol when the entire decision fits in explicit local context; label
long or tacit expert review honestly instead of treating it as an easy check.
