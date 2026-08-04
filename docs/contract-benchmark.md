# Problem Contract Benchmark Standard

The Contract Benchmark measures whether an independent Reviewer can determine
that a proposed open scientific problem is faithful, scientifically solid,
important at its claimed level, scoped as generally as verification permits,
and resolvable under explicit acceptance contracts. It does not screen topic
ideas and does not generate problems.

## First principle

The target is the **largest source-faithful scientific scope that still has a
determinate resolution criterion**.

Specificity is not automatically good. A Contract that fixes one model, one
parameter point, or one method may weaken the source problem and reduce its
impact. Generality is not automatically good either. A broad aspiration is not
a leaf problem when no submitted solution can be judged to have resolved it.

Original literature is an allowed dependency. A Contract need not reproduce a
cited theorem, model, or definition when the reference and locator make the
dependency unambiguous and the benchmark supplies the source. A constructive
or existential problem may let an answer choose a method or witness only inside
an admissible universe and predicate already fixed by the Contract. It may not
delegate selection of the scientific target, model family, parameter domain,
benchmark, hypotheses, or meaning of success to the answer.

The Topic Main Agent owns scope selection. Before emitting a leaf it must freeze
the named scientific object and every load-bearing quantifier from evidence. A
leaf fails the scope-ownership gate when two complete-looking answers could
choose materially different scientific targets and both claim success. When the
evidence cannot support a fixed target, discovery must search again or emit a
parent with fixed child problems rather than passing target selection onward.

## Unit and case eligibility

One benchmark case contains:

- one fixed candidate `problem.json`;
- the source packet available to the Reviewer;
- an as-of date for claims about openness and progress;
- no reference labels or review text in the Reviewer input.

The source packet must provide the original literature, or complete relevant
sections with stable identifiers and precise locators, needed to check the
candidate's interpretation. Search snippets alone are insufficient for claims
that depend on a paper's hypotheses, quantifiers, or limitations. If the source
packet is inadequate, the case is ineligible for scored adjudication; this is a
dataset defect, not evidence that the scientific problem should be rejected.

Evaluation remains offline and repeatable. Discovery, LKM/Web search, and
later-literature audit happen before the case is frozen. Offline means the
Reviewer receives a frozen source packet, not that original papers are
forbidden.

## Review axes

### Contract fields

Every review covers all public Problem Contract fields:

- `schema_version`, `problem_id`, `parent_problem_id`, `subproblem_ids`;
- `title`, `abstract`, `background`, `references`, `previous_progress`;
- `problem_statement`, `scientific_significance`, `solution_difficulty`;
- `verification_contract`, `verification_difficulty`.

The review also covers three cross-cutting fields:

- `scientific_solidity`: premises, objects, openness, answer branches, and
  consequences form a defensible scientific problem;
- `cross_field_consistency`: every field describes the same problem;
- `evidence_fidelity`: the source packet supports the interpretation, progress,
  impact, and open-status claims without quote mining or unsupported extension.

Each field receives `pass`, `minor_issue`, or `major_issue` with evidence and a
rationale.

`must_fix` is a compact list of blocking repair priorities. It may select the
few issues that determine the verdict and need not repeat every non-pass field.
It must never name a field or derived axis that the same review marks as
passing.

### Source fidelity

The Reviewer checks whether the Contract:

- preserves the source problem's claims, assumptions, quantifiers, and known
  boundaries;
- avoids turning a conjecture into an established theorem or a conditional
  result into a universal claim;
- avoids replacing the original problem with an easier special case;
- distinguishes established progress from the surviving open core;
- uses later literature to avoid presenting a solved question as open.

References may carry definitions and hypotheses. The defect is an ambiguous or
incorrect dependency, not the existence of a dependency.

### Scientific solidity

The Reviewer checks that the requested mathematical object, physical regime,
experiment, algorithm, or certificate is coherent; that every proposed answer
branch actually answers the stated question; and that the claimed consequence
would follow from such an answer. A fashionable topic name does not compensate
for a false premise, mismatched quantifier, or scientifically irrelevant
acceptance object.

### Impact and scope

`scope_assessment` records:

- `impact`: `high`, `medium`, or `low`;
- why progress would matter and whether a narrow task is a load-bearing
  bottleneck or merely incremental;
- `scope_verdict`;
- a generalization action and any unnecessary restrictions.

The overall impact level is the strongest **direct, source-supported**
consequence of a complete solution. Speculative downstream possibilities do
not raise the level.

Impact uses the same semantics as `scientific_significance`:

- `high`: directly changes a core understanding, method, or capability;
- `medium`: clear scientific progress or material downstream impact;
- `low`: local, indirect, or incremental effect.

Impact is reported, not used as an automatic publication threshold. A narrow
lemma can have high impact when it unlocks a major theorem; a broad slogan can
have low impact when no concrete consequence follows.

The scope verdict and required action are:

| `scope_verdict` | Meaning | Action |
| --- | --- | --- |
| `appropriate` | Largest justified scope that remains resolvable | `keep` |
| `unnecessarily_narrow` | A restriction weakens the source problem without being scientifically or verification-necessary | `broaden` |
| `too_broad` | Scope has no determinate answer or combines separable problems | `narrow` or `decompose` |
| `source_misaligned` | Scope weakens, strengthens, or replaces the source problem | `broaden`, `narrow`, or `decompose` |

The Reviewer should test restrictions one at a time. Remove a restriction when
the broader statement remains source-faithful and has a complete verification
contract. Stop broadening at the first point where the answer ceases to be
determinate or the literature no longer supports the formulation.

### Resolution gate

Every leaf problem must satisfy:

> Given a purported complete solution, can an independent Reviewer determine
> whether it resolves the stated problem?

`resolution_gate.status` is:

- `pass`: a leaf has clear quantifiers, accepted answer branches, and pass/fail
  contracts that distinguish a solution from partial progress;
- `fail`: at least one complete-looking answer cannot be classified without the
  Reviewer inventing a new scientific criterion;
- `delegated_parent`: a parent intentionally delegates verification to its
  listed child problems.

Different methods or answers are allowed. A problem such as "does there exist
an object in class C with P and not Q?" is determinate when C, P, and Q are
fixed and checkable before an answer exists, even though answers may contain
different witnesses. Asking the answer to choose C, P, or Q fails the gate.

A broad parent may omit `verification_contract` and
`verification_difficulty` only when `subproblem_ids` names the leaves that carry
the acceptance work. Such a parent organizes a program; it is not itself scored
as a dispatchable leaf.

### Verification and difficulty

`verification_contract` must cover every accepted answer type, including
relevant proof, counterexample, exact solution, computation, experiment, code,
dataset, or impossibility branches. Each branch states:

- the accepted object;
- the conditions that make it solve the problem;
- how complete and partial answers differ;
- what CI can check mechanically;
- what remains for Agent or expert review.

CI is the mechanically executable subset of verification. It may parse an
artifact, run tests, replay calculations, check certificates, enumerate finite
cases, validate hashes, or invoke a formal kernel. CI does not replace review of
scientific correspondence or a novel non-formalized argument.

`verification_difficulty` is one 0-10 score for the residual acceptance burden
after all mechanically checkable work is removed across every answer branch. It
does not measure scientific importance or solution difficulty and is never a
threshold.

`solution_difficulty` is a list of plausible scientific obstacles. The Reviewer
checks whether those obstacles are real and relevant, rather than grading them
numerically.

## Verdicts

An overall verdict is:

- `accept`: every field passes, scope is `appropriate`, and the resolution gate
  is `pass` or `delegated_parent`;
- `rewrite`: a defensible source-faithful problem survives, but the Contract
  needs correction, broader or narrower scope, decomposition, completed
  verification, or recalibrated impact/difficulty;
- `reject`: the sources do not support a defensible open problem, the premise is
  false or already resolved, the candidate fabricates or materially replaces
  the source problem, or no coherent formulation can be recovered.

Consulting supplied original literature never causes `reject` by itself. Most
repairable scientific and Contract defects are `rewrite`, not `reject`.

## Adjudication standard

A reference label begins as `provisional`. Promotion requires two independent
blind reviews that do not see each other or the provisional label.

Promotion to `silver` requires agreement on:

- overall verdict;
- every field severity label;
- impact level, scope verdict, and generalization action;
- resolution-gate status.

Rationales need not have identical wording, but they must identify compatible
scientific reasons. Any substantive disagreement remains `disputed` until an
independent arbitrator inspects the original literature and records a resolved
label. Domain-expert adjudication may promote a stable label to `gold`.

A run under a superseded rubric remains provenance only. It cannot vote in a
later adjudication.

## Dataset layout

Corpus data stays in the private companion repository:

```text
contract-v1/
  manifest.json
  cases/<case-id>/input.json
  gold/<case-id>/gold.json
```

`input.json` contains the candidate and source packet. `gold.json` contains the
separate adjudicated review. Rewritten positive examples are new cases; they do
not overwrite negative or disputed inputs.

## Commands

```bash
uv run discovery benchmark validate /path/to/contract-v1

uv run discovery benchmark evaluate /path/to/contract-v1 \
  --out /path/to/evaluation-run \
  --workers 4

uv run discovery benchmark score \
  --predictions /path/to/evaluation-run/predictions \
  --gold /path/to/contract-v1/gold \
  --out /path/to/evaluation-run/report.json
```

There is deliberately no `benchmark generate` command. Generation remains in
the topic or campaign workflow.

## Metrics

Reports include:

- overall-verdict and acceptance-decision accuracy;
- exact field-label accuracy, issue precision/recall, and major-issue recall;
- impact, scope-verdict, generalization-action, and resolution-gate accuracy;
- unsafe accepts, unsafe rejects, and unsafe resolution passes;
- per-case labels and reference-adjudication status.

Text similarity is not a metric. More than one wording, method, witness, or
answer branch may satisfy the same scientific Contract.
