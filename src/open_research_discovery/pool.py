from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from .common import load_yaml, pool_snapshot_paths
from .ranking import RESOLVED_STATUSES


def snapshot_relpath(problem: dict[str, Any]) -> str:
    """Pool-relative snapshot path, routed by the manifest's status."""

    folder = (
        "resolved"
        if str(problem.get("status") or "") in RESOLVED_STATUSES
        else "problems"
    )
    return f"{folder}/{problem['problem_id']}.yaml"


STOPWORDS = {
    "a",
    "an",
    "and",
    "any",
    "are",
    "be",
    "by",
    "does",
    "every",
    "find",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}

def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    normalized = re.sub(r"\\[a-zA-Z]+", " ", normalized)
    return " ".join(re.findall(r"[a-z0-9]+", normalized))


def text_tokens(value: str) -> set[str]:
    return {
        token
        for token in normalize_text(value).split()
        if token not in STOPWORDS and len(token) > 1
    }


def statement_fingerprint(statement: str) -> str:
    normalized = normalize_text(statement)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def problem_to_record(problem: dict[str, Any], repo_name: str) -> dict[str, Any]:
    """Project a Problem Schema v1.0 manifest into a flat pool record."""

    significance = problem.get("scientific_significance") or {}
    affected = significance.get("affected_field") or {}
    difficulty = problem.get("verification_difficulty") or {}
    contract = problem.get("verification_contract") or {}
    statement = str(problem.get("problem_statement") or "")
    search_text = " ".join(
        [
            str(problem.get("title") or ""),
            str(problem.get("domain") or ""),
            statement,
        ]
    )
    return {
        "schema_version": 2,
        "id": str(problem["problem_id"]),
        "title": str(problem["title"]),
        "domain": str(problem.get("domain") or ""),
        "topic_id": str(problem.get("topic_id") or problem.get("domain") or ""),
        "status": str(problem.get("status") or ""),
        "significance_level": str(affected.get("level") or "unassessed"),
        "significance_description": str(affected.get("description") or ""),
        "verification_difficulty": int(
            difficulty.get("score")
            if isinstance(difficulty.get("score"), int)
            and not isinstance(difficulty.get("score"), bool)
            else 10
        ),
        "verification_difficulty_rationale": str(difficulty.get("rationale") or ""),
        "answer_types": [str(value) for value in contract],
        "has_ci": any(
            str((entry or {}).get("ci_contract") or "").strip()
            for entry in contract.values()
        ),
        "statement_sha256": statement_fingerprint(statement),
        "search_text": normalize_text(search_text),
        "snapshot": snapshot_relpath(problem),
        "local_repo": str((problem.get("repository") or {}).get("slug") or repo_name),
    }


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def relation_pairs(relations: dict[str, Any]) -> dict[frozenset[str], str]:
    pairs: dict[frozenset[str], str] = {}
    for relation in relations.get("relations") or []:
        source = str(relation.get("source") or "")
        target = str(relation.get("target") or "")
        relation_type = str(relation.get("type") or "")
        if source and target:
            pairs[frozenset({source, target})] = relation_type
    return pairs


def dedup_candidates(
    records: list[dict[str, Any]],
    *,
    relations: dict[str, Any] | None = None,
    threshold: float = 0.25,
) -> list[dict[str, Any]]:
    known = relation_pairs(relations or {})
    candidates: list[dict[str, Any]] = []
    for index, left in enumerate(records):
        left_tokens = text_tokens(left["search_text"])
        left_title = text_tokens(left["title"])
        left_domain = text_tokens(left["domain"])
        left_sources = set(left.get("source_nodes") or []) | set(
            left.get("source_local_ids") or []
        )
        for right in records[index + 1 :]:
            pair = frozenset({left["id"], right["id"]})
            right_sources = set(right.get("source_nodes") or []) | set(
                right.get("source_local_ids") or []
            )
            exact_statement = left["statement_sha256"] == right["statement_sha256"]
            shared_sources = sorted(left_sources & right_sources)
            lexical = jaccard(left_tokens, text_tokens(right["search_text"]))
            title_similarity = jaccard(left_title, text_tokens(right["title"]))
            domain_similarity = jaccard(left_domain, text_tokens(right["domain"]))
            score = (
                1.0
                if exact_statement or shared_sources
                else 0.65 * lexical + 0.25 * title_similarity + 0.10 * domain_similarity
            )
            if score < threshold and not exact_statement and not shared_sources:
                continue
            known_relation = known.get(pair, "")
            candidates.append(
                {
                    "left": left["id"],
                    "right": right["id"],
                    "score": round(score, 6),
                    "signals": {
                        "exact_statement": exact_statement,
                        "shared_sources": shared_sources,
                        "lexical_jaccard": round(lexical, 6),
                        "title_jaccard": round(title_similarity, 6),
                        "domain_jaccard": round(domain_similarity, 6),
                    },
                    "known_relation": known_relation,
                    "decision": (
                        f"known-{known_relation}" if known_relation else "review"
                    ),
                }
            )
    return sorted(
        candidates,
        key=lambda item: (-float(item["score"]), item["left"], item["right"]),
    )


def load_catalog(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def pool_statistics(records: list[dict[str, Any]]) -> dict[str, Any]:
    fields = (
        "status",
        "significance_level",
        "verification_difficulty",
        "has_ci",
    )
    return {
        "schema_version": 1,
        "total": len(records),
        "resolved": sum(
            1 for row in records if str(row.get("status")) in RESOLVED_STATUSES
        ),
        "counts": {
            field: dict(sorted(Counter(row[field] for row in records).items()))
            for field in fields
        },
    }


def validate_relations(relations: dict[str, Any], problem_ids: set[str]) -> list[str]:
    errors: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    allowed_types = {"duplicate", "related", "derived", "supersedes"}
    for index, relation in enumerate(relations.get("relations") or []):
        source = str(relation.get("source") or "")
        target = str(relation.get("target") or "")
        relation_type = str(relation.get("type") or "")
        if source not in problem_ids:
            errors.append(f"relations[{index}] unknown source: {source}")
        if target not in problem_ids:
            errors.append(f"relations[{index}] unknown target: {target}")
        if source == target:
            errors.append(f"relations[{index}] self relation: {source}")
        if relation_type not in allowed_types:
            errors.append(f"relations[{index}] invalid type: {relation_type}")
        key = (source, target, relation_type)
        if key in seen:
            errors.append(f"relations[{index}] duplicate relation: {key}")
        seen.add(key)
    return errors


def validate_pool(pool_root: Path) -> list[str]:
    errors: list[str] = []
    catalog_path = pool_root / "catalog.jsonl"
    if not catalog_path.is_file():
        return ["missing pool/catalog.jsonl"]
    records = load_catalog(catalog_path)
    ids = [str(record.get("id") or "") for record in records]
    if len(ids) != len(set(ids)):
        errors.append("catalog contains duplicate problem IDs")
    snapshots = {
        path.stem: path
        for folder in ("problems", "resolved")
        for path in pool_snapshot_paths(pool_root / folder)
    }
    if set(ids) != set(snapshots):
        errors.append(
            "catalog/snapshot ID mismatch: "
            f"catalog={len(set(ids))} snapshots={len(snapshots)}"
        )
    for record in records:
        problem_id = record["id"]
        snapshot = load_yaml(snapshots[problem_id])
        if snapshot.get("problem_id") != problem_id:
            errors.append(f"{problem_id} snapshot id mismatch")
        statement = str(snapshot.get("problem_statement") or "")
        if statement_fingerprint(statement) != record.get("statement_sha256"):
            errors.append(f"{problem_id} statement fingerprint mismatch")
    relations_path = pool_root / "relations.yaml"
    if not relations_path.is_file():
        errors.append("missing pool/relations.yaml")
    else:
        errors.extend(
            validate_relations(
                yaml.safe_load(relations_path.read_text(encoding="utf-8")) or {},
                set(ids),
            )
        )
    return errors
