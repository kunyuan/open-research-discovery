from __future__ import annotations

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .agent import AgentRun, CodexRunner, file_sha256
from .common import dump_json
from .problem_contract import (
    SCHEMA_VERSION as PROBLEM_CONTRACT_SCHEMA_VERSION,
    SCIENTIFIC_SIGNIFICANCE_RUBRIC,
    VERIFICATION_DIFFICULTY_RUBRIC,
    require_valid_problem_contract,
)


class BenchmarkError(RuntimeError):
    """A Contract Benchmark artifact is incomplete or inconsistent."""


BENCHMARK_RUBRIC_VERSION = "scientific-problem-contract-v2"


CONTRACT_REVIEW_FIELDS = (
    "schema_version",
    "problem_id",
    "parent_problem_id",
    "subproblem_ids",
    "title",
    "abstract",
    "background",
    "references",
    "previous_progress",
    "problem_statement",
    "scientific_significance",
    "solution_difficulty",
    "verification_contract",
    "verification_difficulty",
    "scientific_solidity",
    "cross_field_consistency",
    "evidence_fidelity",
)


CONTRACT_FIELD_STANDARDS = {
    "schema_version": "Matches the public Problem Contract schema version.",
    "problem_id": "Is stable, nonempty, and identifies this problem rather than a source or topic.",
    "parent_problem_id": "Correctly declares or omits the parent relationship without hiding an undecomposed broad problem.",
    "subproblem_ids": "Lists real delegated children when used and is consistent with the parent's empty delegated fields.",
    "title": "Accurately names the source-aligned scientific target without understating or overstating its generality.",
    "abstract": "Summarizes the scientific claim, significance, and boundary; precisely cited source definitions may remain external dependencies.",
    "background": "Gives source-grounded context without quote mining, weakening, strengthening, or otherwise changing the original problem.",
    "references": "Are traceable, include sufficiently precise locators, and support the claims for which they are cited; citing an original source is not a defect.",
    "previous_progress": "Separates established results, partial progress, and the surviving open core with evidence support.",
    "problem_statement": "States a precise source-aligned claim whose target model or class, physical system, parameter domain, representation, intrinsic benchmark population, and load-bearing quantifiers are fixed before any answer exists. An answer may choose a method or witness only inside that fixed domain; unnecessary restrictions are defects.",
    "scientific_significance": "Names real affected fields, honestly assigns high/medium/low, explains the concrete effect, and distinguishes a merely local technical task from a load-bearing bottleneck.",
    "solution_difficulty": "Lists plausible solving obstacles without inventing a score or confusing them with acceptance burden.",
    "verification_contract": "Covers every accepted answer type and states a complete, unambiguous pass/fail contract plus truthful mechanical CI scope.",
    "verification_difficulty": "Gives one combined 0-10 residual-review score after excluding every mechanical check across all accepted answer types.",
    "scientific_solidity": "The premises, objects, claimed openness, proposed answer branches, and scientific consequences are coherent and defensible under the cited literature.",
    "cross_field_consistency": "Title, scope, significance, answer types, CI, difficulty, progress, hierarchy, and references describe the same problem.",
    "evidence_fidelity": "The supplied original literature and evidence support the background, progress, impact, and open claim as of the case date; failed search alone is not proof of openness.",
}


SCOPE_ASSESSMENT_STANDARD = (
    "Judge the problem's actual scientific impact, not its apparent breadth. A "
    "narrow lemma may have high impact when it removes a load-bearing bottleneck; "
    "a broad slogan may have low usable impact. The overall impact is the strongest "
    "direct, source-supported consequence of a complete solution, not a speculative "
    "downstream possibility. Then choose the largest "
    "source-faithful scope that still has a determinate resolution criterion. "
    "The Topic Main Agent must own and freeze the scientific target; delegating "
    "the choice of model, class, domain, benchmark, hypotheses, or success meaning "
    "to a future answer is not generality. It is an unresolved scope. "
    "Mark unnecessary restrictions, recommend broadening when a stronger "
    "verifiable formulation preserves the original intent, and recommend "
    "narrowing or decomposition only when broader wording loses a definite answer."
)


RESOLUTION_GATE_STANDARD = (
    "For every leaf problem, a submitted solution must be classifiable as solving "
    "or not solving the problem from the stated quantifiers and verification "
    "contracts. Different methods or witnesses are allowed only inside an "
    "admissible universe and predicate already fixed by the Contract. A leaf fails "
    "when a future answer can choose or redefine its target model, family, domain, "
    "benchmark, hypotheses, or acceptance scope. Use delegated_parent only "
    "for a parent whose verification is explicitly delegated to listed children; "
    "a broad parent is not itself a dispatchable leaf."
)


def _load_object(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise BenchmarkError(f"expected JSON object: {path}")
    return value


def _validate(instance: dict[str, Any], schema_path: Path) -> None:
    schema = _load_object(schema_path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        rendered = "; ".join(
            f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
            for error in errors[:8]
        )
        raise BenchmarkError(rendered)


def _case_paths(
    dataset_dir: Path,
    manifest: dict[str, Any],
) -> list[tuple[dict[str, Any], Path]]:
    records = manifest.get("cases")
    if not isinstance(records, list):
        raise BenchmarkError("manifest.json is missing cases[]")
    if manifest.get("case_count") != len(records):
        raise BenchmarkError("manifest case_count does not match cases[]")
    root = dataset_dir.resolve()
    resolved: list[tuple[dict[str, Any], Path]] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise BenchmarkError("manifest cases[] must contain objects")
        case_id = str(record.get("case_id") or "")
        input_path = str(record.get("input_path") or "")
        if not case_id or not input_path:
            raise BenchmarkError("every manifest case needs case_id and input_path")
        if case_id in seen:
            raise BenchmarkError(f"duplicate manifest case_id {case_id}")
        seen.add(case_id)
        path = (dataset_dir / input_path).resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise BenchmarkError(
                f"input path escapes dataset directory: {input_path}"
            ) from error
        if not path.is_file():
            raise BenchmarkError(f"benchmark input does not exist: {path}")
        resolved.append((record, path))
    return resolved


def _documents(root: Path, schema_path: Path) -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*.json")):
        document = _load_object(path)
        case_id = str(document.get("case_id") or "")
        if not case_id:
            continue
        _validate(document, schema_path)
        if case_id in documents:
            raise BenchmarkError(f"duplicate case_id {case_id} under {root}")
        documents[case_id] = document
    return documents


def _review_issue_fields(review: dict[str, Any]) -> set[str]:
    issues = {
        field
        for field, detail in review["field_reviews"].items()
        if detail["verdict"] != "pass"
    }
    if review["scope_assessment"]["scope_verdict"] != "appropriate":
        issues.add("scope_assessment")
    if review["resolution_gate"]["status"] == "fail":
        issues.add("resolution_gate")
    return issues


def _validate_review_semantics(
    review: dict[str, Any],
    *,
    case_id: str,
    candidate: dict[str, Any] | None = None,
) -> None:
    issues = _review_issue_fields(review)
    must_fix_fields = {item["field"] for item in review["must_fix"]}
    if not must_fix_fields.issubset(issues):
        raise BenchmarkError(
            f"review must_fix contains a passing field for {case_id}"
        )
    verdict = review["overall_verdict"]
    if (verdict == "accept") != (not issues):
        raise BenchmarkError(
            f"review overall verdict is inconsistent with review issues for {case_id}"
        )
    rewrite_prompt = review["rewrite_prompt"].strip()
    if verdict == "rewrite" and not rewrite_prompt:
        raise BenchmarkError(f"rewrite review prompt is empty for {case_id}")
    if verdict != "rewrite" and rewrite_prompt:
        raise BenchmarkError(
            f"non-rewrite review has a rewrite prompt for {case_id}"
        )
    if verdict != "accept" and not review["must_fix"]:
        raise BenchmarkError(f"non-accept review has no must_fix items for {case_id}")

    scope = review["scope_assessment"]
    expected_actions = {
        "appropriate": {"keep"},
        "unnecessarily_narrow": {"broaden"},
        "too_broad": {"narrow", "decompose"},
        "source_misaligned": {"broaden", "narrow", "decompose"},
    }
    if scope["generalization_action"] not in expected_actions[scope["scope_verdict"]]:
        raise BenchmarkError(
            f"scope verdict/action mismatch for {case_id}"
        )
    if scope["scope_verdict"] == "appropriate" and scope["unnecessary_restrictions"]:
        raise BenchmarkError(
            f"appropriate scope lists unnecessary restrictions for {case_id}"
        )

    if candidate is None:
        return
    delegated_contract = (
        candidate.get("verification_contract") is None
        and bool(candidate.get("subproblem_ids"))
    )
    resolution_status = review["resolution_gate"]["status"]
    if delegated_contract and resolution_status != "delegated_parent":
        raise BenchmarkError(
            f"delegated parent does not use delegated_parent resolution for {case_id}"
        )
    if not delegated_contract and resolution_status == "delegated_parent":
        raise BenchmarkError(
            f"non-delegated problem uses delegated_parent resolution for {case_id}"
        )


def _review_prompt(case: dict[str, Any]) -> str:
    standards = "\n".join(
        f"- {field}: {CONTRACT_FIELD_STANDARDS[field]}"
        for field in CONTRACT_REVIEW_FIELDS
    )
    return f"""\
You are the evaluated Reviewer in an offline Problem Contract Benchmark.
Review the supplied candidate; do not solve it and do not generate a replacement
contract. Use only the frozen evidence below. Do not search the web, call LKM,
or read unrelated files.

Original literature is an allowed dependency. Do not require the Contract to
restate a cited theorem, model, or definition when the reference and locator make
the dependency unambiguous and the source is supplied in the case packet. Do not
penalize an answer for choosing a method or witness inside an admissible universe
and predicate already fixed by an explicit existential quantifier.

Apply a hard scope-ownership gate. The Topic Main Agent must have fixed the
scientific target before emitting a leaf. Mark problem_statement and
cross_field_consistency as major_issue, fail resolution_gate, and return rewrite
when a future answer is asked to choose, select, define, or delimit the target
model or class, physical system, parameter domain, representation, intrinsic
benchmark population, hypotheses, or meaning of success. Ask whether two
complete-looking answers could choose materially different scientific targets
and both claim success. If yes, the leaf is not dispatchable. This does not
forbid different witnesses inside one fixed quantified domain.

The candidate Problem Contract schema and this Reviewer prediction schema are
different documents. A candidate schema_version of
{PROBLEM_CONTRACT_SCHEMA_VERSION!r} is the current valid Problem Contract
version. The integer schema_version required in your output belongs only to the
benchmark prediction. Never mark the candidate invalid by comparing those two
version fields.

Return one field review for every required benchmark field. Use pass only when
the field meets its standard. Use minor_issue for a local defect and major_issue
for scientific distortion, unsupported claims, unnecessary weakening, excessive
generality without a determinate answer, incomplete verification, or another
load-bearing defect. An absent parent is a valid value to review, not a reason to
skip the field.

Also return scope_assessment and resolution_gate. Maximize scientific reach
subject to source fidelity and determinate resolution: restrictions should be
kept only when scientifically necessary, source-mandated, or needed to state a
verifiable claim. A leaf passes the resolution gate when a complete submitted
solution can be unambiguously judged to solve or not solve the stated problem.
A parent with verification delegated to named children uses delegated_parent.

Return overall_verdict=accept only when every field passes, scope_verdict is
appropriate, and resolution_gate is pass or delegated_parent. Return rewrite
when a source-faithful scientific problem survives but the Contract should be
corrected, broadened, narrowed, decomposed, or given complete verification.
Return reject only when the sources do not support a defensible open problem,
the premise is false or already resolved, the candidate fabricates or materially
replaces the source problem, or no scientifically coherent formulation can be
recovered. Needing to consult supplied original literature is never by itself a
reason to reject.
Evidence references must identify records in the frozen dossier; use an empty
list for a purely structural judgment. must_fix is a compact list of blocking
repair priorities; every entry must name an issue axis, but it need not repeat
every minor or major field review.

Field standards:
{standards}

Scientific-significance rubric:
{SCIENTIFIC_SIGNIFICANCE_RUBRIC}

Scope-and-impact standard:
{SCOPE_ASSESSMENT_STANDARD}

Resolution-gate standard:
{RESOLUTION_GATE_STANDARD}

Verification-difficulty rubric:
{VERIFICATION_DIFFICULTY_RUBRIC}

Set case_id exactly to {case["case_id"]} and problem_id exactly to
{case["candidate_contract"]["problem_id"]}.

Candidate Problem Contract:
{json.dumps(case["candidate_contract"], ensure_ascii=False, indent=2)}

Frozen evidence dossier:
{json.dumps(case["frozen_evidence"], ensure_ascii=False, indent=2)}
"""


def evaluate_benchmark(
    *,
    dataset_dir: Path,
    out_dir: Path,
    input_schema: Path,
    prediction_schema: Path,
    problem_schema: Path,
    runner: CodexRunner,
    workers: int = 1,
    case_ids: set[str] | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """Evaluate a Reviewer on fixed Problem Contracts; never generate one."""

    if workers < 1:
        raise BenchmarkError("workers must be positive")
    manifest_path = dataset_dir / "manifest.json"
    if not manifest_path.is_file():
        raise BenchmarkError(f"benchmark manifest does not exist: {manifest_path}")
    manifest = _load_object(manifest_path)
    cases = _case_paths(dataset_dir, manifest)
    if case_ids is not None:
        known = {str(record["case_id"]) for record, _ in cases}
        unknown = sorted(case_ids - known)
        if unknown:
            raise BenchmarkError("unknown benchmark case IDs: " + ", ".join(unknown))
        cases = [item for item in cases if item[0]["case_id"] in case_ids]

    def evaluate_one(item: tuple[dict[str, Any], Path]) -> dict[str, Any]:
        record, input_path = item
        case = _load_object(input_path)
        _validate(case, input_schema)
        case_id = str(record["case_id"])
        if case.get("case_id") != case_id:
            raise BenchmarkError(f"manifest/input case mismatch for {case_id}")
        if case.get("evidence_mode") != "frozen-evidence":
            raise BenchmarkError(
                f"{case_id} is not frozen-evidence; evaluation must be offline"
            )
        try:
            require_valid_problem_contract(case["candidate_contract"], problem_schema)
        except ValueError as error:
            raise BenchmarkError(
                f"{case_id} has invalid candidate contract: {error}"
            ) from error

        case_dir = out_dir / "predictions" / case_id
        prediction_path = case_dir / "prediction.json"
        metadata_path = case_dir / "metadata.json"
        if resume and prediction_path.is_file():
            prediction = _load_object(prediction_path)
            _validate(prediction, prediction_schema)
            if prediction.get("case_id") != case_id:
                raise BenchmarkError(f"existing prediction case mismatch for {case_id}")
            _validate_review_semantics(
                prediction,
                case_id=case_id,
                candidate=case["candidate_contract"],
            )
            return {
                "case_id": case_id,
                "prediction_path": str(prediction_path.relative_to(out_dir)),
                "metadata_path": (
                    str(metadata_path.relative_to(out_dir))
                    if metadata_path.is_file()
                    else ""
                ),
                "reused": True,
            }

        result: AgentRun = runner.run(
            role="contract-benchmark-reviewer",
            prompt=_review_prompt(case),
            schema_path=prediction_schema,
            output_path=prediction_path,
            events_path=case_dir / "events.jsonl",
        )
        prediction = result.output
        if prediction.get("case_id") != case_id:
            raise BenchmarkError(f"prediction case_id mismatch for {case_id}")
        if prediction.get("problem_id") != case["candidate_contract"]["problem_id"]:
            raise BenchmarkError(f"prediction problem_id mismatch for {case_id}")
        _validate_review_semantics(
            prediction,
            case_id=case_id,
            candidate=case["candidate_contract"],
        )
        metadata = {
            **result.metadata,
            "input_path": str(input_path),
            "input_sha256": file_sha256(input_path),
            "network_policy": "offline",
            "task": "review-fixed-problem-contract",
            "rubric_version": BENCHMARK_RUBRIC_VERSION,
        }
        dump_json(metadata_path, metadata)
        return {
            "case_id": case_id,
            "prediction_path": str(prediction_path.relative_to(out_dir)),
            "metadata_path": str(metadata_path.relative_to(out_dir)),
            "reused": False,
        }

    completed: list[dict[str, Any]] = []
    if workers == 1:
        completed = [evaluate_one(item) for item in cases]
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(evaluate_one, item): item[0]["case_id"]
                for item in cases
            }
            for future in as_completed(futures):
                completed.append(future.result())
    completed.sort(key=lambda item: item["case_id"])
    output = {
        "schema_version": 1,
        "benchmark_manifest": str(manifest_path.resolve()),
        "benchmark_manifest_sha256": file_sha256(manifest_path),
        "task": "review-fixed-problem-contract",
        "rubric_version": BENCHMARK_RUBRIC_VERSION,
        "evidence_mode": "frozen-evidence",
        "network_policy": "offline",
        "case_count": len(completed),
        "predictions": completed,
    }
    dump_json(out_dir / "evaluation.json", output)
    return output


def validate_benchmark_dataset(
    *,
    dataset_dir: Path,
    input_schema: Path,
    prediction_schema: Path,
    gold_schema: Path,
    problem_schema: Path,
    require_gold: bool = True,
) -> dict[str, Any]:
    """Validate fixed contracts, evidence, and field-level reference reviews."""

    manifest_path = dataset_dir / "manifest.json"
    if not manifest_path.is_file():
        raise BenchmarkError(f"benchmark manifest does not exist: {manifest_path}")
    manifest = _load_object(manifest_path)
    cases = _case_paths(dataset_dir, manifest)
    inputs: dict[str, dict[str, Any]] = {}
    domains: Counter[str] = Counter()
    for record, path in cases:
        case = _load_object(path)
        _validate(case, input_schema)
        case_id = str(record["case_id"])
        if case.get("case_id") != case_id:
            raise BenchmarkError(f"manifest/input case mismatch for {case_id}")
        if record.get("domain") != case.get("domain"):
            raise BenchmarkError(f"manifest/input domain mismatch for {case_id}")
        if case.get("evidence_mode") != "frozen-evidence":
            raise BenchmarkError(f"{case_id} is not frozen-evidence")
        try:
            require_valid_problem_contract(case["candidate_contract"], problem_schema)
        except ValueError as error:
            raise BenchmarkError(
                f"{case_id} has invalid candidate contract: {error}"
            ) from error
        inputs[case_id] = case
        domains[str(case["domain"])] += 1

    gold_root = dataset_dir / "gold"
    if require_gold and not gold_root.is_dir():
        raise BenchmarkError(f"benchmark gold directory does not exist: {gold_root}")
    labels = _documents(gold_root, gold_schema) if gold_root.is_dir() else {}
    if labels and set(labels) != set(inputs):
        raise BenchmarkError(
            "input/gold case mismatch; "
            f"missing gold={sorted(set(inputs) - set(labels))}, "
            f"extra gold={sorted(set(labels) - set(inputs))}"
        )

    label_statuses: Counter[str] = Counter()
    verdicts: Counter[str] = Counter()
    for case_id, gold in labels.items():
        reference = gold["review"]
        _validate(reference, prediction_schema)
        candidate = inputs[case_id]["candidate_contract"]
        if reference["case_id"] != case_id:
            raise BenchmarkError(f"gold review case_id mismatch for {case_id}")
        if reference["problem_id"] != candidate["problem_id"]:
            raise BenchmarkError(f"gold problem_id mismatch for {case_id}")
        _validate_review_semantics(
            reference,
            case_id=case_id,
            candidate=candidate,
        )
        reviewers = gold["adjudication"]["reviewers"]
        if gold["label_status"] in {"silver", "gold"} and len(reviewers) < 2:
            raise BenchmarkError(
                f"{case_id} claims {gold['label_status']} with fewer than two reviewers"
            )
        label_statuses[str(gold["label_status"])] += 1
        verdicts[str(reference["overall_verdict"])] += 1
    return {
        "schema_version": 1,
        "benchmark_id": manifest.get("benchmark_id", ""),
        "benchmark_version": manifest.get("benchmark_version", ""),
        "rubric_version": BENCHMARK_RUBRIC_VERSION,
        "case_count": len(inputs),
        "reference_count": len(labels),
        "evidence_mode": "frozen-evidence",
        "domains": dict(sorted(domains.items())),
        "label_statuses": dict(sorted(label_statuses.items())),
        "contract_verdicts": dict(sorted(verdicts.items())),
        "formal_gold_ready": bool(labels)
        and not ({"provisional", "disputed"} & set(label_statuses)),
    }


def score_benchmark(
    *,
    predictions_root: Path,
    gold_root: Path,
    prediction_schema: Path,
    gold_schema: Path,
) -> dict[str, Any]:
    """Compare Reviewer field judgments with adjudicated reference reviews."""

    if predictions_root.resolve() == gold_root.resolve():
        raise BenchmarkError("predictions and gold roots must be distinct directories")
    predictions = _documents(predictions_root, prediction_schema)
    labels = _documents(gold_root, gold_schema)
    missing = sorted(set(labels) - set(predictions))
    extra = sorted(set(predictions) - set(labels))
    if missing or extra:
        raise BenchmarkError(
            f"case mismatch; missing predictions={missing}, extra predictions={extra}"
        )
    for case_id in labels:
        _validate_review_semantics(
            labels[case_id]["review"],
            case_id=case_id,
        )
        if predictions[case_id] == labels[case_id]["review"]:
            raise BenchmarkError(
                f"prediction identical to gold review for {case_id}; possible label leakage"
            )
        if (
            predictions[case_id]["problem_id"]
            != labels[case_id]["review"]["problem_id"]
        ):
            raise BenchmarkError(f"prediction problem_id mismatch for {case_id}")

    rows: list[dict[str, Any]] = []
    per_field: dict[str, dict[str, int]] = {
        field: {"correct": 0, "count": 0, "gold_issues": 0, "detected_issues": 0}
        for field in CONTRACT_REVIEW_FIELDS
    }
    issue_true_positive = 0
    predicted_issues = 0
    gold_issues = 0
    major_true_positive = 0
    gold_major = 0
    scope_verdict_correct = 0
    impact_correct = 0
    generalization_action_correct = 0
    resolution_gate_correct = 0
    unsafe_resolution_pass = 0
    for case_id in sorted(labels):
        prediction = predictions[case_id]
        gold = labels[case_id]["review"]
        field_rows: dict[str, Any] = {}
        for field in CONTRACT_REVIEW_FIELDS:
            predicted = prediction["field_reviews"][field]["verdict"]
            expected = gold["field_reviews"][field]["verdict"]
            correct = predicted == expected
            predicted_issue = predicted != "pass"
            gold_issue = expected != "pass"
            field_rows[field] = {
                "predicted": predicted,
                "gold": expected,
                "correct": correct,
            }
            per_field[field]["count"] += 1
            per_field[field]["correct"] += int(correct)
            per_field[field]["gold_issues"] += int(gold_issue)
            per_field[field]["detected_issues"] += int(predicted_issue and gold_issue)
            predicted_issues += int(predicted_issue)
            gold_issues += int(gold_issue)
            issue_true_positive += int(predicted_issue and gold_issue)
            gold_major += int(expected == "major_issue")
            major_true_positive += int(
                expected == "major_issue" and predicted == "major_issue"
            )
        predicted_verdict = prediction["overall_verdict"]
        gold_verdict = gold["overall_verdict"]
        predicted_scope = prediction["scope_assessment"]
        gold_scope = gold["scope_assessment"]
        predicted_resolution = prediction["resolution_gate"]["status"]
        gold_resolution = gold["resolution_gate"]["status"]
        scope_verdict_correct += int(
            predicted_scope["scope_verdict"] == gold_scope["scope_verdict"]
        )
        impact_correct += int(predicted_scope["impact"] == gold_scope["impact"])
        generalization_action_correct += int(
            predicted_scope["generalization_action"]
            == gold_scope["generalization_action"]
        )
        resolution_gate_correct += int(predicted_resolution == gold_resolution)
        unsafe_resolution_pass += int(
            gold_resolution == "fail" and predicted_resolution != "fail"
        )
        rows.append(
            {
                "case_id": case_id,
                "label_status": labels[case_id]["label_status"],
                "predicted_verdict": predicted_verdict,
                "gold_verdict": gold_verdict,
                "overall_verdict_correct": predicted_verdict == gold_verdict,
                "acceptance_decision_correct": (
                    (predicted_verdict == "accept") == (gold_verdict == "accept")
                ),
                "unsafe_accept": predicted_verdict == "accept"
                and gold_verdict != "accept",
                "unsafe_reject": predicted_verdict == "reject"
                and gold_verdict == "accept",
                "scope_assessment": {
                    "predicted_impact": predicted_scope["impact"],
                    "gold_impact": gold_scope["impact"],
                    "predicted_scope_verdict": predicted_scope["scope_verdict"],
                    "gold_scope_verdict": gold_scope["scope_verdict"],
                    "predicted_generalization_action": predicted_scope[
                        "generalization_action"
                    ],
                    "gold_generalization_action": gold_scope[
                        "generalization_action"
                    ],
                },
                "resolution_gate": {
                    "predicted": predicted_resolution,
                    "gold": gold_resolution,
                    "correct": predicted_resolution == gold_resolution,
                },
                "fields": field_rows,
            }
        )
    field_count = len(rows) * len(CONTRACT_REVIEW_FIELDS)
    return {
        "schema_version": 1,
        "task": "review-fixed-problem-contract",
        "rubric_version": BENCHMARK_RUBRIC_VERSION,
        "case_count": len(rows),
        "reference_statuses": dict(
            sorted(Counter(row["label_status"] for row in rows).items())
        ),
        "formal_gold_ready": not any(
            row["label_status"] in {"provisional", "disputed"} for row in rows
        ),
        "overall_verdict_accuracy": (
            sum(row["overall_verdict_correct"] for row in rows) / len(rows)
            if rows
            else 0.0
        ),
        "acceptance_decision_accuracy": (
            sum(row["acceptance_decision_correct"] for row in rows) / len(rows)
            if rows
            else 0.0
        ),
        "field_exact_accuracy": (
            sum(detail["correct"] for row in rows for detail in row["fields"].values())
            / field_count
            if field_count
            else 0.0
        ),
        "issue_detection_precision": (
            issue_true_positive / predicted_issues if predicted_issues else 0.0
        ),
        "issue_detection_recall": (
            issue_true_positive / gold_issues if gold_issues else 0.0
        ),
        "major_issue_recall": (major_true_positive / gold_major if gold_major else 0.0),
        "impact_accuracy": impact_correct / len(rows) if rows else 0.0,
        "scope_verdict_accuracy": (
            scope_verdict_correct / len(rows) if rows else 0.0
        ),
        "generalization_action_accuracy": (
            generalization_action_correct / len(rows) if rows else 0.0
        ),
        "resolution_gate_accuracy": (
            resolution_gate_correct / len(rows) if rows else 0.0
        ),
        "unsafe_resolution_pass_count": unsafe_resolution_pass,
        "unsafe_accept_count": sum(row["unsafe_accept"] for row in rows),
        "unsafe_reject_count": sum(row["unsafe_reject"] for row in rows),
        "per_field": {
            field: {
                **counts,
                "accuracy": counts["correct"] / counts["count"]
                if counts["count"]
                else 0.0,
                "issue_recall": (
                    counts["detected_issues"] / counts["gold_issues"]
                    if counts["gold_issues"]
                    else 0.0
                ),
            }
            for field, counts in per_field.items()
        },
        "cases": rows,
    }
