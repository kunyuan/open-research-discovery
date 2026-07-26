from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .common import dump_json
from .pool import normalize_text


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
    return {_candidate_id(cluster) for cluster in clusters}


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
    active_ids = _active_candidate_ids(run_dir)
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
        case = {
            "schema_version": 2,
            "case_id": case_id,
            "candidate_id": candidate_id,
            "domain": candidate["domain"],
            "canonical_title": candidate["canonical_title"],
            "canonical_statement": candidate["canonical_statement"],
            "aliases": list(candidate.get("aliases") or []),
            "source_support": list(candidate.get("source_support") or []),
            "source_open_questions": list(
                candidate.get("source_open_questions") or []
            ),
            "evidence_mode": "live-retrieval",
            "task": {
                "judge_importance": True,
                "identify_solution_route": True,
                "judge_review_scope": True,
                "judge_ci_buildability": True,
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
        "schema_version": 2,
        "source_run": str(run_dir.resolve()),
        "case_count": len(cases),
        "cases": cases,
    }
    dump_json(out_dir / "manifest.json", manifest)
    return manifest


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


def _prediction_dispatch_ready(prediction: dict[str, Any]) -> bool:
    return (
        prediction["importance"]["label"] in {"high", "medium"}
        and prediction["review"]["route_sufficiency"]
        and prediction["review"]["scope"] == "result-only"
        and prediction["ci"]["buildability"]
        in {"machine", "bounded-llm", "hybrid"}
    )


def _gold_dispatch_ready(gold: dict[str, Any]) -> bool:
    return (
        gold["current_status"] in {"still-open", "partially-resolved"}
        and gold["importance"]["label"] in {"high", "medium"}
        and gold["review"]["route_sufficiency"]
        and gold["review"]["scope"] == "result-only"
        and gold["ci"]["buildability"]
        in {"machine", "bounded-llm", "hybrid"}
    )


def score_benchmark(
    *,
    predictions_root: Path,
    gold_root: Path,
    prediction_schema: Path,
    gold_schema: Path,
) -> dict[str, Any]:
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
        predicted_dispatch = _prediction_dispatch_ready(prediction)
        gold_dispatch = _gold_dispatch_ready(gold)
        rows.append(
            {
                "case_id": case_id,
                "importance_correct": (
                    prediction["importance"]["label"]
                    == gold["importance"]["label"]
                ),
                "review_scope_correct": (
                    prediction["review"]["scope"] == gold["review"]["scope"]
                ),
                "route_sufficiency_correct": (
                    prediction["review"]["route_sufficiency"]
                    == gold["review"]["route_sufficiency"]
                ),
                "route_effect_correct": (
                    prediction["review"]["route_scientific_effect"]
                    == gold["review"]["route_scientific_effect"]
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
        "importance_accuracy": (
            sum(row["importance_correct"] for row in rows) / count
            if count
            else 0.0
        ),
        "review_scope_accuracy": (
            sum(row["review_scope_correct"] for row in rows) / count
            if count
            else 0.0
        ),
        "route_sufficiency_accuracy": (
            sum(row["route_sufficiency_correct"] for row in rows) / count
            if count
            else 0.0
        ),
        "route_effect_accuracy": (
            sum(row["route_effect_correct"] for row in rows) / count
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
    active_ids = _active_candidate_ids(run_dir)
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
        tags = [
            f"gate:{triage['gate']}",
            f"importance:{triage['importance_level']}",
            f"effect:{triage['route_scientific_effect']}",
            f"sufficient:{triage['route_sufficiency']}",
            f"review:{triage['review_scope']}",
            f"ci:{triage['ci_feasibility']}",
            f"mode:{triage['verification_mode']}",
            f"ease:{triage['verification_ease']}",
            f"artifact:{triage['artifact_type']}",
        ]
        records_by_domain[domain].append(
            {
                "candidate_id": candidate_id,
                "case_id": "ORSB-" + candidate_id.removeprefix("CAN-"),
                "domain": candidate["domain"],
                "title": candidate["canonical_title"],
                "tags": tags,
                "provisional": {
                    "gate": triage["gate"],
                    "importance": triage["importance_level"],
                    "solution_route": triage["solution_route"],
                    "route_scientific_effect": triage[
                        "route_scientific_effect"
                    ],
                    "route_sufficiency": triage["route_sufficiency"],
                    "route_scope_limitations": triage[
                        "route_scope_limitations"
                    ],
                    "review_scope": triage["review_scope"],
                    "ci_feasibility": triage["ci_feasibility"],
                    "verification_mode": triage["verification_mode"],
                    "verification_ease": triage["verification_ease"],
                    "artifact_type": triage["artifact_type"],
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
                    "importance, review, CI, verification, ease, and artifact tags."
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
