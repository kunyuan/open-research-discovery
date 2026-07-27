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

When several outcomes can conclusively answer the question, the agent chooses
one source-faithful expected result for dispatch. A finite counterexample can
therefore be `result-only` even if a proof of the positive statement would
require derivation review. This does not authorize weakening the claim: the
chosen result must completely answer the scoped question, not merely improve a
bound or settle one favorable instance.

Apply the same completeness test to finite optimization and parameter-family
questions. A maximizing object establishes a lower bound but does not by
itself establish an exact optimum; the missing upper bound still needs
derivation review unless the final result naturally contains independently
replayable decisive evidence. Likewise, one checkable instance does not resolve
a source question asking for a nontrivial family. CI that validates examples is
useful, but it does not turn partial evidence into a complete answer.

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

- `input.json` contains the current canonical question, exact source
  `data.papers[].open_questions` records, and a frozen neutral evidence dossier.
  It contains no benchmark labels.
- `prediction.json` is produced by the evaluated agent.
- `gold.json` is produced by independent blind adjudication and kept separate
  from evaluated-agent context.

The same agent output cannot serve as both prediction and gold. Schema version
7 records importance, expected result, Solution Review scope and rationale,
optional CI, and the normative result-only definition. Gold records
include the as-of date and current-status audit because later progress can
change the meaningful surviving core.

## Two separate workflows

Do not search again whenever the benchmark is scored.

### Build or refresh a dataset version

This workflow is networked and runs only when creating a new benchmark version.
It discovers source papers, performs strict LKM extraction, canonicalizes
questions, audits later literature, selects cases, freezes the evidence, and
obtains independent labels.

```bash
uv run discovery benchmark build /path/to/campaign.yaml \
  --run-id benchmark-v1-build \
  --triage-per-domain 8 \
  --workers 3

# Resume a build or deliberately refresh the candidate pool:
uv run discovery benchmark refresh <run> \
  --triage-per-domain 8 \
  --workers 3

# Generate sampling strata; these are not gold labels:
uv run discovery benchmark provisional-triage <run> --workers 3
```

When atomic decomposition produces a large pool, `--triage-per-domain` runs one
bounded Prescreen Agent per domain and retains every unselected candidate in
the campaign while limiting expensive per-candidate Triage. Prescreen output is
recall prioritization, never a benchmark label or gold judgment.

`--workers` bounds concurrent headless Codex processes. Each worker owns a
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
  --out /path/to/benchmark-v1
```

`export` writes `evidence_mode: frozen-evidence`. Add neutral later-literature
and current-baseline records to `frozen_evidence` before adjudication. The
evaluated agent must be able to judge the three screening dimensions without
retrieval, but it must not see gold labels or gold rationales.

Use two or more blind adjudications for each selected case. Matching labels
form a silver label; disagreements remain `disputed` until independent
arbitration. Human-confirmed labels are `gold`. Before freezing the version,
remove resolved, refuted, uncertain-identity, and no-surviving-core cases.
Current openness is therefore a dataset-construction condition, not a fourth
prediction target.

Version the result rather than mutating it in place. A literature refresh
creates `v2`; it does not silently change `v1`.

The initial benchmark version is intentionally limited to mathematics,
physics, and computational science, with five cases per domain and at least
one dispatch-positive and one dispatch-negative case in each domain. The
discovery pipeline itself remains discipline-neutral.

### Evaluate a frozen version

This workflow is offline and repeatable. It does not call LKM or Web search.

```bash
uv run discovery benchmark validate /path/to/benchmark-v1

uv run discovery benchmark evaluate /path/to/benchmark-v1 \
  --out /path/to/evaluation-run \
  --workers 3

# Reuse schema-valid predictions and retry only missing cases:
uv run discovery benchmark evaluate /path/to/benchmark-v1 \
  --out /path/to/evaluation-run \
  --workers 3 \
  --resume

uv run discovery benchmark score \
  --predictions /path/to/evaluation-run/predictions \
  --gold /path/to/benchmark-v1/gold \
  --out /path/to/evaluation-run/report.json
```

`evaluate` invokes one ephemeral headless Codex Triage process per case with
`read-only` sandboxing and `network_access=false`. Its prompt contains only the
frozen `input.json`. Run metadata records the input hash, schema hash, command,
model, Codex version, sandbox, and network policy.

`prepare`, `resume-prepare`, and `predict` remain compatibility aliases for
`build`, `refresh`, and `provisional-triage`. They are dataset-construction
commands, never the formal evaluation loop.

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
