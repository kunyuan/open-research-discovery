# Research-problem screening benchmark

The benchmark measures whether an agent can screen a sourced open research
question. It does not measure whether the agent can solve that question.

## Evaluation target

Each prediction has three independent dimensions:

1. **Scientific importance** — `high`, `medium`, `low`, or `uncertain`.
2. **Future Solution Review scope for the expected result** —
   `result-only`,
   `result-and-derivation`,
   `expert-intensive`, or `uncertain`.
3. **CI buildability** — `machine`, `bounded-llm`, `hybrid`,
   `not-buildable`, or `uncertain`, with a bounded verification contract.

Difficulty of finding a solution, probability of success, and solver compute
are not screening dimensions.

`result-only` has one test: without reviewing the solver's reasoning process,
can an independent Reviewer basically decide correctness from only the final
result naturally required by the original problem? An ordinary written proof
therefore remains `result-and-derivation`; executable formal proof code counts
as the result only when requested by the original problem. If acceptance still
requires substantive derivation review, supplying a missing lemma, or
defending a generality or causal claim outside the final result, label it
`result-and-derivation` or `expert-intensive`.

This is independent of CI mode. Machine, bounded-LLM, and hybrid checkers can
all be result-only; having executable CI does not prove that the final artifact
is sufficient. Conversely, `not-buildable` CI does not disqualify an important
`result-only` problem; CI is scored as a separate bonus. Set
`timeout_minutes` to zero only when no machine CI can run.

The evaluated agent describes the expected result without proposing a solving
method. Its rationale must explain why that result genuinely answers the
source question, any claim limitations, and whether review must substantively
assess a derivation rather than only the final answer or artifact. This one
rationale replaces separate route, effect, sufficiency, and limitation fields.

The expected result must preserve the answer format requested or naturally
committed to by the source question.
Formal proof code is the result only when the source explicitly asks for
formalization or a machine-checkable proof/certificate; an ordinary theorem
proof cannot be upgraded to result-only by imposing Lean after the fact.
Likewise, an exact optimum problem cannot be upgraded by requiring an SOS,
primal-dual certificate, or special file format absent from the source answer
contract.
Production difficulty is irrelevant; changing the delivery contract,
weakening the claim, or pretending ambiguous scientific semantics are frozen
is not allowed.

Predictions and gold labels describe the expected result and rationale in
plain language. The evaluated Problem Reviewer makes the
future Solution Review-scope judgment directly; deterministic code checks the
schema but does not infer scientific semantics from an artifact type. See
[the Solution Review-scope casebook](solution-review-scope-casebook.md).

## No-leakage layers

- `input.json` contains only the canonical question and exact source
  `data.papers[].open_questions` records, including the exact excerpt supporting
  an atomic candidate.
- `prediction.json` is produced by the evaluated agent.
- `gold.json` is produced by independent blind adjudication and kept separate
  from evaluated-agent context.

The same agent output cannot serve as both prediction and gold. Schema version
7 records importance, expected result, Solution Review scope and rationale,
optional CI, and the normative result-only definition. Gold records
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
  --triage-per-domain 8 \
  --workers 3

# Resume a failed or interrupted recall/atomization run:
uv run discovery benchmark resume-prepare <run> \
  --triage-per-domain 8 \
  --workers 3

# Resume or regenerate only the provisional triage labels later:
uv run discovery benchmark predict <run> --workers 3
```

When atomic decomposition produces a large pool, `--triage-per-domain` runs one
bounded Prescreen Agent per domain and retains every unselected candidate in
the campaign while limiting expensive per-candidate Triage. Prescreen output is
recall prioritization, never a benchmark label or gold judgment.

`--workers` bounds concurrent headless Codex subagents. Each worker owns a
different candidate artifact, while one in-process StageLedger serializes
atomic `state.json` replacements. Do not run two mutating CLI commands against
the same campaign directory at once.

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

The selector greedily covers rare provisional gate, importance, Solution
Review scope, and CI labels within each domain. These labels are sampling
strata, not gold.

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

Report exact accuracy separately for importance, Solution Review scope, and CI
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
