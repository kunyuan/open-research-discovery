from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .agent import AgentRun, CodexRunner, file_sha256
from .common import candidate_identity_text, dump_json, load_yaml
from .pool import normalize_text
from .ranking import (
    DEFAULT_MAX_VERIFICATION_DIFFICULTY,
    VERIFICATION_DIFFICULTY_RUBRIC,
)


class BenchmarkError(RuntimeError):
    """A benchmark artifact is incomplete or violates its schema."""


def _load_object(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise BenchmarkError(f"expected JSON object: {path}")
    return value


def _selected_ids(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, list):
        return {str(item) for item in value}
    if isinstance(value, dict) and isinstance(value.get("candidate_ids"), list):
        return {str(item) for item in value["candidate_ids"]}
    raise BenchmarkError(
        "selection must be a JSON list or an object with candidate_ids[]"
    )


def _candidate_id(cluster: dict[str, Any]) -> str:
    identity = {
        "statement": normalize_text(str(cluster["canonical_statement"])),
        "sources": sorted(cluster["source_keys"]),
    }
    rendered = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "CAN-" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()[
        :12
    ].upper()


def _exact_candidate_id(cluster: dict[str, Any]) -> str:
    identity = {
        "statement": candidate_identity_text(
            str(cluster["canonical_statement"])
        ),
        "sources": sorted(cluster["source_keys"]),
    }
    rendered = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "CAN-" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()[
        :12
    ].upper()


def _cluster_candidate_ids(clusters: list[dict[str, Any]]) -> set[str]:
    candidate_ids: set[str] = set()
    exact_candidate_ids: set[str] = set()
    for cluster in clusters:
        candidate_id = _candidate_id(cluster)
        exact_candidate_id = _exact_candidate_id(cluster)
        if candidate_id in candidate_ids:
            if exact_candidate_id in exact_candidate_ids:
                raise BenchmarkError(
                    "canonicalization contains duplicate candidates"
                )
            candidate_id = exact_candidate_id
        if candidate_id in candidate_ids:
            raise BenchmarkError(
                f"unresolved candidate ID collision: {candidate_id}"
            )
        candidate_ids.add(candidate_id)
        exact_candidate_ids.add(exact_candidate_id)
    return candidate_ids


def _active_candidate_ids(run_dir: Path) -> set[str]:
    state_path = run_dir / "state.json"
    if state_path.is_file():
        state = _load_object(state_path)
        recorded = state.get("active_candidate_ids")
        if isinstance(recorded, list) and recorded:
            return {str(candidate_id) for candidate_id in recorded}
    canonicalization_path = run_dir / "canonicalization.json"
    if not canonicalization_path.is_file():
        raise BenchmarkError(
            f"canonicalization does not exist: {canonicalization_path}"
        )
    canonicalization = _load_object(canonicalization_path)
    clusters = canonicalization.get("clusters")
    if not isinstance(clusters, list):
        raise BenchmarkError("canonicalization.json is missing clusters[]")
    return _cluster_candidate_ids(clusters)


def _triage_candidate_ids(run_dir: Path) -> set[str]:
    state_path = run_dir / "state.json"
    if state_path.is_file():
        state = _load_object(state_path)
        recorded = state.get("triage_candidate_ids")
        if isinstance(recorded, list) and recorded:
            return {str(candidate_id) for candidate_id in recorded}
    return _active_candidate_ids(run_dir)


def _validate(instance: dict[str, Any], schema_path: Path) -> None:
    schema = _load_object(schema_path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        rendered = "; ".join(
            f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: "
            f"{error.message}"
            for error in errors[:8]
        )
        raise BenchmarkError(rendered)


def export_benchmark_inputs(
    *,
    run_dir: Path,
    out_dir: Path,
    schema_path: Path,
    selection_path: Path | None = None,
) -> dict[str, Any]:
    selected = _selected_ids(selection_path)
    active_ids = _triage_candidate_ids(run_dir)
    candidate_root = run_dir / "candidates"
    if not candidate_root.is_dir():
        raise BenchmarkError(f"candidate directory does not exist: {candidate_root}")
    cases: list[dict[str, Any]] = []
    found_ids: set[str] = set()
    for canonical_path in sorted(candidate_root.glob("CAN-*/canonicalization.json")):
        candidate = _load_object(canonical_path)
        candidate_id = str(candidate.get("candidate_id") or "")
        if candidate_id not in active_ids:
            continue
        if selected is not None and candidate_id not in selected:
            continue
        found_ids.add(candidate_id)
        case_id = "ORSB-" + candidate_id.removeprefix("CAN-")
        source_open_questions = list(
            candidate.get("source_open_questions") or []
        )
        case = {
            "schema_version": 9,
            "case_id": case_id,
            "candidate_id": candidate_id,
            "domain": candidate["domain"],
            "canonical_title": candidate["canonical_title"],
            "canonical_statement": candidate["canonical_statement"],
            "aliases": list(candidate.get("aliases") or []),
            "source_support": list(candidate.get("source_support") or []),
            "source_open_questions": source_open_questions,
            "frozen_evidence": [
                {
                    "evidence_id": (
                        str(item.get("global_id") or item.get("id") or "")
                    ),
                    "kind": "source-open-question",
                    "title": str(item.get("paper_title") or ""),
                    "identifier": str(
                        item.get("paper_doi")
                        or item.get("paper_id")
                        or ""
                    ),
                    "content_level": "lkm_open_question",
                    "content": str(item.get("content") or ""),
                }
                for item in source_open_questions
            ],
            "evidence_mode": "frozen-evidence",
            "task": {
                "judge_importance": True,
                "describe_expected_result": True,
                "judge_verification_difficulty": True,
                "judge_ci_buildability": True,
                "verification_difficulty_rubric": VERIFICATION_DIFFICULTY_RUBRIC,
            },
        }
        _validate(case, schema_path)
        case_dir = out_dir / "cases" / case_id
        dump_json(case_dir / "input.json", case)
        cases.append(
            {
                "case_id": case_id,
                "candidate_id": candidate_id,
                "domain": case["domain"],
                "title": case["canonical_title"],
                "input_path": str((case_dir / "input.json").relative_to(out_dir)),
            }
        )
    if selected is not None:
        missing = sorted(selected - found_ids)
        if missing:
            raise BenchmarkError(
                "selection contains unknown candidate IDs: " + ", ".join(missing)
            )
    manifest = {
        "schema_version": 9,
        "source_run": str(run_dir.resolve()),
        "case_count": len(cases),
        "cases": cases,
    }
    dump_json(out_dir / "manifest.json", manifest)
    return manifest


def _benchmark_case_paths(
    dataset_dir: Path,
    manifest: dict[str, Any],
) -> list[tuple[dict[str, Any], Path]]:
    records = manifest.get("cases")
    if not isinstance(records, list):
        raise BenchmarkError("manifest.json is missing cases[]")
    declared_count = manifest.get("case_count")
    if declared_count != len(records):
        raise BenchmarkError(
            f"manifest case_count={declared_count!r} does not match "
            f"{len(records)} cases"
        )
    resolved: list[tuple[dict[str, Any], Path]] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise BenchmarkError("manifest cases[] must contain objects")
        case_id = str(record.get("case_id") or "")
        input_path = str(record.get("input_path") or "")
        if not case_id or not input_path:
            raise BenchmarkError(
                "every manifest case needs case_id and input_path"
            )
        if case_id in seen:
            raise BenchmarkError(f"duplicate manifest case_id {case_id}")
        seen.add(case_id)
        path = (dataset_dir / input_path).resolve()
        try:
            path.relative_to(dataset_dir.resolve())
        except ValueError as error:
            raise BenchmarkError(
                f"input path escapes dataset directory: {input_path}"
            ) from error
        if not path.is_file():
            raise BenchmarkError(f"benchmark input does not exist: {path}")
        resolved.append((record, path))
    return resolved


def _evaluation_prompt(case: dict[str, Any]) -> str:
    rendered = json.dumps(case, ensure_ascii=False, indent=2, sort_keys=True)
    return f"""\
You are the evaluated Triage Agent in an offline research-problem screening
benchmark. Use only the frozen dossier below. Do not search the web, call LKM,
read unrelated repository files, or use outside evidence. If the dossier is
insufficient for a judgment, use the `unassessed` label.

Judge exactly three independent dimensions:
1. scientific importance;
2. verification difficulty from 0 to 10;
3. whether useful CI can be built in principle, independently of dimension 2.

Use the supplied verification-difficulty rubric. Score 0 when every
load-bearing claim is discharged by mechanical checks, replay, or
certificates with trivial specification fidelity; this does not require CI.
Explicit counterexamples, exact solutions, finite constructions,
fixed code-to-experiment comparisons, and required proof-assistant artifacts
with contract-pinned statements
may all be 0. Use 1-9 for the increasing residual derivation review and
10 for an essential claim that cannot be decomposed into independently
checkable units. CI remains a separate layer that cannot lower the score. The chosen result must
fully answer the scoped question, not merely constitute partial progress.
Describe the expected final result, not a solving route.

Return one JSON object matching the supplied schema. Set case_id exactly to
{case["case_id"]}.

Frozen dossier:
{rendered}
"""


def evaluate_benchmark(
    *,
    dataset_dir: Path,
    out_dir: Path,
    input_schema: Path,
    prediction_schema: Path,
    runner: CodexRunner,
    workers: int = 1,
    case_ids: set[str] | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """Run schema-constrained Triage on frozen cases without retrieval."""

    if workers < 1:
        raise BenchmarkError("workers must be positive")
    manifest_path = dataset_dir / "manifest.json"
    if not manifest_path.is_file():
        raise BenchmarkError(f"benchmark manifest does not exist: {manifest_path}")
    manifest = _load_object(manifest_path)
    case_paths = _benchmark_case_paths(dataset_dir, manifest)
    if case_ids is not None:
        known = {str(record["case_id"]) for record, _ in case_paths}
        unknown = sorted(case_ids - known)
        if unknown:
            raise BenchmarkError(
                "unknown benchmark case IDs: " + ", ".join(unknown)
            )
        case_paths = [
            item for item in case_paths if item[0]["case_id"] in case_ids
        ]

    def evaluate_one(
        record_and_path: tuple[dict[str, Any], Path],
    ) -> dict[str, Any]:
        record, input_path = record_and_path
        case = _load_object(input_path)
        _validate(case, input_schema)
        case_id = str(record["case_id"])
        if case.get("case_id") != case_id:
            raise BenchmarkError(
                f"manifest/input case mismatch for {case_id}: "
                f"{case.get('case_id')!r}"
            )
        if case.get("evidence_mode") != "frozen-evidence":
            raise BenchmarkError(
                f"{case_id} is not frozen-evidence; formal evaluation "
                "must not trigger retrieval"
            )
        case_dir = out_dir / "predictions" / case_id
        prediction_path = case_dir / "prediction.json"
        metadata_path = case_dir / "metadata.json"
        if resume and prediction_path.is_file():
            prediction = _load_object(prediction_path)
            _validate(prediction, prediction_schema)
            if prediction.get("case_id") != case_id:
                raise BenchmarkError(
                    f"existing prediction case_id mismatch for {case_id}"
                )
            return {
                "case_id": case_id,
                "domain": case["domain"],
                "prediction_path": str(
                    prediction_path.relative_to(out_dir)
                ),
                "metadata_path": (
                    str(metadata_path.relative_to(out_dir))
                    if metadata_path.is_file()
                    else ""
                ),
                "reused": True,
            }
        result: AgentRun = runner.run(
            role="benchmark-triage",
            prompt=_evaluation_prompt(case),
            schema_path=prediction_schema,
            output_path=prediction_path,
            events_path=case_dir / "events.jsonl",
        )
        if result.output.get("case_id") != case_id:
            raise BenchmarkError(
                f"prediction case_id mismatch for {case_id}: "
                f"{result.output.get('case_id')!r}"
            )
        metadata = {
            **result.metadata,
            "input_path": str(input_path),
            "input_sha256": file_sha256(input_path),
            "network_policy": "offline",
        }
        dump_json(metadata_path, metadata)
        return {
            "case_id": case_id,
            "domain": case["domain"],
            "prediction_path": str(
                prediction_path.relative_to(out_dir)
            ),
            "metadata_path": str(
                metadata_path.relative_to(out_dir)
            ),
            "reused": False,
        }

    completed: list[dict[str, Any]] = []
    if workers == 1:
        completed = [evaluate_one(item) for item in case_paths]
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(evaluate_one, item): item[0]["case_id"]
                for item in case_paths
            }
            for future in as_completed(futures):
                completed.append(future.result())
    completed.sort(key=lambda item: item["case_id"])
    output_manifest = {
        "schema_version": 1,
        "benchmark_manifest": str(manifest_path.resolve()),
        "benchmark_manifest_sha256": file_sha256(manifest_path),
        "evidence_mode": "frozen-evidence",
        "network_policy": "offline",
        "case_count": len(completed),
        "predictions": completed,
    }
    dump_json(out_dir / "evaluation.json", output_manifest)
    return output_manifest


def validate_benchmark_dataset(
    *,
    dataset_dir: Path,
    input_schema: Path,
    gold_schema: Path,
    require_gold: bool = True,
) -> dict[str, Any]:
    """Validate a frozen benchmark and report its positive/negative balance."""

    manifest_path = dataset_dir / "manifest.json"
    if not manifest_path.is_file():
        raise BenchmarkError(f"benchmark manifest does not exist: {manifest_path}")
    manifest = _load_object(manifest_path)
    case_paths = _benchmark_case_paths(dataset_dir, manifest)
    inputs: dict[str, dict[str, Any]] = {}
    domains: Counter[str] = Counter()
    for record, path in case_paths:
        case = _load_object(path)
        _validate(case, input_schema)
        case_id = str(record["case_id"])
        if case.get("case_id") != case_id:
            raise BenchmarkError(f"manifest/input case mismatch for {case_id}")
        if case.get("evidence_mode") != "frozen-evidence":
            raise BenchmarkError(f"{case_id} is not frozen-evidence")
        if record.get("domain") != case.get("domain"):
            raise BenchmarkError(f"manifest/input domain mismatch for {case_id}")
        inputs[case_id] = case
        domains[str(case["domain"])] += 1
    expected_domain_counts = manifest.get("expected_domain_counts")
    if expected_domain_counts is not None:
        if not isinstance(expected_domain_counts, dict):
            raise BenchmarkError("expected_domain_counts must be an object")
        expected = {
            str(domain): int(count)
            for domain, count in expected_domain_counts.items()
        }
        actual = dict(domains)
        if actual != expected:
            raise BenchmarkError(
                f"domain counts do not match manifest; expected={expected}, "
                f"actual={actual}"
            )

    gold_root = dataset_dir / "gold"
    if require_gold and not gold_root.is_dir():
        raise BenchmarkError(f"benchmark gold directory does not exist: {gold_root}")
    gold = (
        _documents(gold_root, gold_schema)
        if gold_root.is_dir()
        else {}
    )
    if gold and set(gold) != set(inputs):
        raise BenchmarkError(
            "input/gold case mismatch; "
            f"missing gold={sorted(set(inputs) - set(gold))}, "
            f"extra gold={sorted(set(gold) - set(inputs))}"
        )

    balance: dict[str, Counter[str]] = defaultdict(Counter)
    for case_id, label in gold.items():
        if label["current_status"] not in {
            "still_open",
            "partially_resolved",
        }:
            raise BenchmarkError(
                f"{case_id} has closed or uncertain gold status; freeze the "
                "surviving current-open core before formal evaluation"
            )
        if label["label_status"] == "disputed":
            raise BenchmarkError(
                f"{case_id} has disputed labels and is not formal-gold ready"
            )
        domain = str(inputs[case_id]["domain"])
        lane = "positive" if _gold_dispatch_ready(label) else "negative"
        balance[domain][lane] += 1
    for domain in domains:
        if gold and (
            balance[domain]["positive"] == 0
            or balance[domain]["negative"] == 0
        ):
            raise BenchmarkError(
                f"domain {domain} must contain both positive and negative cases"
            )
    return {
        "schema_version": 1,
        "case_count": len(inputs),
        "gold_count": len(gold),
        "evidence_mode": "frozen-evidence",
        "domains": {
            domain: {
                "case_count": count,
                "positive": balance[domain]["positive"],
                "negative": balance[domain]["negative"],
            }
            for domain, count in sorted(domains.items())
        },
    }


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


def _campaign_max_verification_difficulty(run_dir: Path | None) -> int:
    """Read the campaign-configured threshold, falling back to the default."""
    if run_dir is None:
        return DEFAULT_MAX_VERIFICATION_DIFFICULTY
    campaign_path = run_dir / "campaign.yaml"
    if not campaign_path.is_file():
        return DEFAULT_MAX_VERIFICATION_DIFFICULTY
    campaign = load_yaml(campaign_path)
    return int(
        (campaign.get("limits") or {}).get(
            "max_verification_difficulty",
            DEFAULT_MAX_VERIFICATION_DIFFICULTY,
        )
    )


def _prediction_dispatch_ready(
    prediction: dict[str, Any],
    max_verification_difficulty: int = DEFAULT_MAX_VERIFICATION_DIFFICULTY,
) -> bool:
    return (
        prediction["importance"]["label"] in {"high", "medium"}
        and prediction["solution_review"]["verification_difficulty"]
        <= max_verification_difficulty
    )


def _gold_dispatch_ready(
    gold: dict[str, Any],
    max_verification_difficulty: int = DEFAULT_MAX_VERIFICATION_DIFFICULTY,
) -> bool:
    return (
        gold["current_status"] in {"still_open", "partially_resolved"}
        and gold["importance"]["label"] in {"high", "medium"}
        and gold["solution_review"]["verification_difficulty"]
        <= max_verification_difficulty
    )


def score_benchmark(
    *,
    predictions_root: Path,
    gold_root: Path,
    prediction_schema: Path,
    gold_schema: Path,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    max_verification_difficulty = _campaign_max_verification_difficulty(run_dir)
    predictions = _documents(predictions_root, prediction_schema)
    labels = _documents(gold_root, gold_schema)
    missing = sorted(set(labels) - set(predictions))
    extra = sorted(set(predictions) - set(labels))
    if missing or extra:
        raise BenchmarkError(
            f"case mismatch; missing predictions={missing}, extra predictions={extra}"
        )
    rows: list[dict[str, Any]] = []
    for case_id in sorted(labels):
        prediction = predictions[case_id]
        gold = labels[case_id]
        predicted_dispatch = _prediction_dispatch_ready(
            prediction, max_verification_difficulty
        )
        gold_dispatch = _gold_dispatch_ready(gold, max_verification_difficulty)
        rows.append(
            {
                "case_id": case_id,
                "importance_correct": (
                    prediction["importance"]["label"]
                    == gold["importance"]["label"]
                ),
                "verification_difficulty_exact": (
                    prediction["solution_review"]["verification_difficulty"]
                    == gold["solution_review"]["verification_difficulty"]
                ),
                "verification_difficulty_absolute_error": abs(
                    prediction["solution_review"]["verification_difficulty"]
                    - gold["solution_review"]["verification_difficulty"]
                ),
                "ci_buildability_correct": (
                    prediction["ci"]["buildability"]
                    == gold["ci"]["buildability"]
                ),
                "predicted_dispatch_ready": predicted_dispatch,
                "gold_dispatch_ready": gold_dispatch,
                "unsafe_dispatch_false_positive": (
                    predicted_dispatch and not gold_dispatch
                ),
            }
        )
    count = len(rows)
    true_positive = sum(
        row["predicted_dispatch_ready"] and row["gold_dispatch_ready"]
        for row in rows
    )
    predicted_positive = sum(row["predicted_dispatch_ready"] for row in rows)
    gold_positive = sum(row["gold_dispatch_ready"] for row in rows)
    return {
        "schema_version": 2,
        "case_count": count,
        "max_verification_difficulty": max_verification_difficulty,
        "importance_accuracy": (
            sum(row["importance_correct"] for row in rows) / count
            if count
            else 0.0
        ),
        "verification_difficulty_exact_accuracy": (
            sum(row["verification_difficulty_exact"] for row in rows) / count
            if count
            else 0.0
        ),
        "verification_difficulty_mean_absolute_error": (
            sum(
                row["verification_difficulty_absolute_error"]
                for row in rows
            )
            / count
            if count
            else 0.0
        ),
        "ci_buildability_accuracy": (
            sum(row["ci_buildability_correct"] for row in rows) / count
            if count
            else 0.0
        ),
        "dispatch_precision": (
            true_positive / predicted_positive if predicted_positive else 0.0
        ),
        "dispatch_recall": (
            true_positive / gold_positive if gold_positive else 0.0
        ),
        "unsafe_dispatch_false_positives": sum(
            row["unsafe_dispatch_false_positive"] for row in rows
        ),
        "cases": rows,
    }


def select_stratified_cases(
    *,
    run_dir: Path,
    per_domain: int,
    domains: list[str] | None = None,
    out_path: Path,
) -> dict[str, Any]:
    if per_domain < 1:
        raise BenchmarkError("per_domain must be positive")
    domain_filter = {domain.strip() for domain in domains or [] if domain.strip()}
    records_by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    active_ids = _triage_candidate_ids(run_dir)
    max_verification_difficulty = _campaign_max_verification_difficulty(run_dir)
    missing_triage: list[str] = []
    for canonical_path in sorted(
        (run_dir / "candidates").glob("CAN-*/canonicalization.json")
    ):
        candidate = _load_object(canonical_path)
        candidate_id = str(candidate.get("candidate_id") or "")
        if candidate_id not in active_ids:
            continue
        domain = str(candidate["domain"])
        if domain_filter and domain not in domain_filter:
            continue
        triage_path = canonical_path.parent / "triage.json"
        if not triage_path.is_file():
            missing_triage.append(candidate_id)
            continue
        triage = _load_object(triage_path)
        passes_gate = (
            triage["importance_level"] in {"high", "medium"}
            and triage["verification_difficulty"]
            <= max_verification_difficulty
        )
        gate = "pass" if passes_gate else "deferred"
        tags = [
            f"gate:{gate}",
            f"importance:{triage['importance_level']}",
            f"verification-difficulty:{triage['verification_difficulty']}",
            f"ci:{triage['ci_status']}",
        ]
        records_by_domain[domain].append(
            {
                "candidate_id": candidate_id,
                "case_id": "ORSB-" + candidate_id.removeprefix("CAN-"),
                "domain": candidate["domain"],
                "title": candidate["canonical_title"],
                "tags": tags,
                "provisional": {
                    "gate": gate,
                    "importance": triage["importance_level"],
                    "expected_result": triage["expected_result"],
                    "verification_difficulty": triage[
                        "verification_difficulty"
                    ],
                    "max_verification_difficulty": max_verification_difficulty,
                    "ci_status": triage["ci_status"],
                },
            }
        )
    if missing_triage:
        raise BenchmarkError(
            f"triage incomplete for {len(missing_triage)} candidates: "
            + ", ".join(sorted(missing_triage)[:8])
        )
    missing_domains = sorted(domain_filter - set(records_by_domain))
    if missing_domains:
        raise BenchmarkError(
            "requested domains have no active candidates: "
            + ", ".join(missing_domains)
        )
    selected: list[dict[str, Any]] = []
    for domain in sorted(records_by_domain):
        candidates = records_by_domain[domain]
        if len(candidates) < per_domain:
            raise BenchmarkError(
                f"domain {domain} has {len(candidates)} candidates, "
                f"needs {per_domain}"
            )
        counts = Counter(tag for item in candidates for tag in item["tags"])
        covered: set[str] = set()
        remaining = list(candidates)
        for _ in range(per_domain):
            def key(item: dict[str, Any]) -> tuple[float, str]:
                novelty = sum(
                    (2.0 if tag not in covered else 0.15) / counts[tag]
                    for tag in item["tags"]
                )
                return (novelty, item["candidate_id"])

            chosen = max(remaining, key=key)
            chosen = {
                **chosen,
                "selection_rationale": (
                    "Greedy rare-label coverage over provisional gate, "
                    "importance, verification-difficulty, and CI tags."
                ),
            }
            selected.append(chosen)
            covered.update(chosen["tags"])
            remaining = [
                item
                for item in remaining
                if item["candidate_id"] != chosen["candidate_id"]
            ]
    output = {
        "schema_version": 1,
        "source_run": str(run_dir.resolve()),
        "per_domain": per_domain,
        "domains": sorted(records_by_domain),
        "candidate_ids": [item["candidate_id"] for item in selected],
        "selected": selected,
    }
    dump_json(out_path, output)
    return output
