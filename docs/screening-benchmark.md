# Research-problem screening benchmark

Benchmark construction and evaluation are separate from the default
problem-generation campaign. Use this workflow only when the user explicitly
requests a benchmark; ordinary requests to find, audit, or publish research
problems should run `discovery campaign`, not any `discovery benchmark`
command.

The benchmark measures whether an agent can screen a sourced open research
question. It does not measure whether the agent can solve that question.

## Evaluation target

Each prediction has three independent dimensions:

1. **Scientific importance** — `high`, `medium`, `low`, or `unassessed`.
2. **Verification difficulty for the expected result** — an integer from 0
   to 10.
3. **CI buildability** — `machine`, `bounded-llm`, `hybrid`,
   `not-buildable`, or `unassessed`, with a bounded verification contract.

Difficulty of finding a solution, probability of success, and solver compute
are not screening dimensions.

Verification difficulty is the residual burden left on an independent
reviewer after every mechanically delegable check has been delegated. Score 0
when every load-bearing claim is discharged by mechanical checks, replay, or
certificates and specification fidelity is trivial — the formal statement,
protocol, or target is pinned by the contract. This does not require CI to
exist. Use 1–3 for a few independent, local, standard reasoning units; 4–6
for connected derivations or substantial specification-fidelity
reconstruction; 7–9 for long, fragile, or novel chains, or code that must be
reviewed for correctness rather than run; and 10 when the essential claim
cannot be decomposed into independently checkable units.

Executable scientific code may also be the natural final result. For example,
if the source asks for a decoder that beats a named baseline under an already
defined noise model, accuracy metric, and resource constraint, the submitted
program, locked environment, source-faithful comparison configuration, and
machine-readable outputs can score 0: the Reviewer reruns the
comparison rather than inspecting the solver's search or design reasoning.
This is not a new artifact type or schema field. It is the same sufficiency
test applied to an executable answer.

Do not create this outcome by freezing a convenient benchmark after the fact.
If the source instead asks for robustness across unspecified regimes, a
general convergence or complexity guarantee, causal explanation, or hardware
behavior not captured by the executable model, a favorable run is only partial
evidence. The expected result scores 0 only when the replayed
comparison itself is scientifically sufficient for the exact scoped claim.

Distinguish scientific target selection from routine reproducibility. The
source must ground the target, baseline, applicable regime, and comparison
axes. It need not enumerate a software version, random seed, repetition count,
or statistical tolerance. Freezing those routine details in the final result
does not invent a new benchmark. By contrast, choosing a favorable dataset,
metric, physical regime, or success threshold that changes what the source
asks would be an invalid weakening.

When several outcomes can conclusively answer the question, the agent chooses
one source-faithful expected result for dispatch. A finite counterexample can
therefore score 0 even if a proof of the positive statement would
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
all accompany score-0 problems; having executable CI does not prove that the
final artifact is sufficient. Conversely, `not-buildable` CI does not
disqualify an important score-0 problem; CI is scored as a separate bonus. Set
`timeout_minutes` to zero only when no machine CI can run.

The evaluated agent describes the expected result without proposing a solving
method. Its rationale must explain why that result genuinely answers the
source question, any claim limitations, and whether review must substantively
assess a derivation rather than only the final answer or artifact. This one
rationale replaces separate route, effect, sufficiency, and limitation fields.

The expected result must preserve the answer format requested or naturally
committed to by the source question.
Required formal proof code scores 0 when the contract pins the formal
statement and the kernel checks the submitted result; an ordinary
natural-language theorem proof scores 10.
Likewise, an exact optimum problem cannot be upgraded by requiring an SOS,
primal-dual certificate, or special file format absent from the source answer
contract.
Production difficulty is irrelevant; changing the delivery contract,
weakening the claim, or pretending ambiguous scientific semantics are frozen
is not allowed.

Predictions and gold labels describe the expected result and rationale in
plain language. The evaluated Problem Reviewer makes the
verification-difficulty judgment directly; deterministic code checks the
schema but does not infer scientific semantics from an artifact type. See
[the verification-difficulty casebook](verification-difficulty-casebook.md).

## No-leakage layers

- `input.json` contains the current canonical question, exact source
  `data.papers[].open_questions` records, and a frozen neutral evidence dossier.
  It contains no benchmark labels.
- `prediction.json` is produced by the evaluated agent.
- `gold.json` is produced by independent blind adjudication and kept separate
  from evaluated-agent context.

The same agent output cannot serve as both prediction and gold. Schema
version 9 records importance, expected result, verification difficulty and
rationale, optional CI, and the normative scoring rubric. It uses the
pipeline's snake_case vocabulary: `still_open`/`partially_resolved` for
current status and `unassessed` for a missing importance or CI judgment.
Gold records
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
  --workers 3

# Resume a build or deliberately refresh the candidate pool:
uv run discovery benchmark refresh <run> \
  --workers 3

# Generate sampling strata; these are not gold labels:
uv run discovery benchmark provisional-triage <run> --workers 3
```

Every atomic candidate receives Triage. Build a smaller frozen evaluation set
only afterward with `discovery benchmark select`, which stratifies the complete
prediction inventory without hiding candidates from screening.

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

The selector greedily covers rare provisional gate, importance, verification
difficulty, and CI labels within each domain. These labels are sampling
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

Report exact accuracy for importance and CI buildability. For verification
difficulty, report both exact accuracy and mean absolute error. Also report
precision and false-positive count for the combined research-dispatch
decision. A score that is too low is operationally more dangerous than a
conservative false negative, so never hide it inside one aggregate score.

Score separated prediction and gold directories with:

```bash
uv run discovery benchmark score \
  --predictions /path/to/predictions \
  --gold /path/to/gold \
  --out /path/to/report.json
```

The report includes per-dimension accuracy, dispatch precision and recall, and
an explicit count of unsafe dispatch false positives.
