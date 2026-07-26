# Research-problem screening benchmark

The benchmark measures whether an agent can screen a sourced open research
question. It does not measure whether the agent can solve that question.

## Evaluation target

Each prediction has three independent dimensions:

1. **Scientific importance** — `high`, `medium`, `low`, or `uncertain`, with
   the concrete consequences of progress.
2. **Review scope for one explicit solution route** — `result-only`,
   `result-and-derivation`,
   `expert-intensive`, or `uncertain`.
3. **CI buildability** — `machine`, `bounded-llm`, `hybrid`,
   `not-buildable`, or `uncertain`, with a bounded verification contract.

Difficulty of finding a solution, probability of success, and solver compute
are not screening dimensions.

`result-only` has a strict input boundary. Review may use the frozen problem
specification, declared final deliverable, trusted verifiers, and frozen
reference data. Retain the deliverable, but hide the solver's search and
reasoning process and every undeclared auxiliary explanation; the verdict must
not change. The deliverable may be a counterexample, exact solution,
executable algorithm or first-principles model, certificate, or formal proof
code. Lean/Coq/Isabelle source checked by a pinned trusted kernel is the result,
not hidden process. If acceptance still requires reconstructing an argument,
reading an additional prose proof, supplying a missing lemma, or defending a
generality or causal claim outside the deliverable, label the route
`result-and-derivation` or `expert-intensive`.

This is independent of CI mode. Machine, bounded-LLM, and hybrid checkers can
all be result-only; having executable CI does not prove that the final artifact
is sufficient.

The evaluated agent must identify one scientifically sufficient route before
classifying review and CI. A route may be one-sided, such as a finite
counterexample that refutes a conjecture. A benchmark-conditioned algorithm is
not a clean positive when the benchmark or threshold was invented merely to
make a broad research direction finite.

## No-leakage layers

- `input.json` contains only the canonical question and exact source
  `data.papers[].open_questions` records, including the exact excerpt supporting
  an atomic candidate.
- `prediction.json` is produced by the evaluated agent.
- `gold.json` is produced by independent blind adjudication and kept separate
  from evaluated-agent context.

The same agent output cannot serve as both prediction and gold. Schema version
3 records the proposed solution route, scientific effect, sufficiency, scope
limitations, and the normative result-only definition explicitly. Gold records
include the as-of date and current-status audit because later progress can
change the meaningful surviving core.

## Construction workflow

The initial benchmark profile is intentionally limited to mathematics,
physics, and computational science. The discovery pipeline remains
discipline-neutral; chemistry, biology, and engineering records may remain in
the source pool without entering this benchmark version.

Generate provisional predictions for every canonical candidate:

```bash
uv run discovery benchmark prepare /path/to/campaign.yaml \
  --run-id benchmark-v0 \
  --triage-per-domain 8

# Resume a failed or interrupted recall/atomization run:
uv run discovery benchmark resume-prepare <run> --triage-per-domain 8

# Resume or regenerate only the provisional triage labels later:
uv run discovery benchmark predict <run>
```

When atomic decomposition produces a large pool, `--triage-per-domain` runs one
bounded Prescreen Agent per domain and retains every unselected candidate in
the campaign while limiting expensive per-candidate Triage. Prescreen output is
recall prioritization, never a benchmark label or gold judgment.

Stratify candidates by domain and provisional labels. Keep likely positives,
likely negatives, and boundary or disagreement cases. Do not select only
pipeline passes.

Create a deterministic diversity-oriented draft selection:

```bash
uv run discovery benchmark select <run> \
  --domain mathematics \
  --domain physics \
  --domain computational-science \
  --per-domain 5 \
  --out selection.json
```

The selector greedily covers rare provisional gate, importance, review, CI,
verification, ease, and artifact labels within each domain. These labels are
sampling strata, not gold.

Export all candidates or a JSON selection:

```bash
uv run discovery benchmark export <run> \
  --selection selection.json \
  --out /path/to/benchmark-v0
```

Use two or more blind adjudications for each selected case. Matching labels
form a silver label; disagreements remain `disputed` until independent
arbitration. Human-confirmed labels are `gold`.

## Primary metric

Report exact accuracy separately for importance, review scope, and CI
buildability. Also report precision and false-positive count for the combined
research-dispatch decision. A false claim that expert-intensive work is
result-only or CI-buildable is more operationally dangerous than a conservative
false negative, so never hide it inside one aggregate score.

Score separated prediction and gold directories with:

```bash
uv run discovery benchmark score \
  --predictions /path/to/predictions \
  --gold /path/to/gold \
  --out /path/to/report.json
```

The report includes per-dimension accuracy, dispatch precision and recall, and
an explicit count of unsafe dispatch false positives.
