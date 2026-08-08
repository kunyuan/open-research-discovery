from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import yaml

from .common import load_yaml, pool_snapshot_paths


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

VIEW_SPECS = {
    "high-significance": (
        "High-significance problems",
        "scientific_significance_level",
        {"high"},
    ),
    "medium-significance": (
        "Medium-significance problems",
        "scientific_significance_level",
        {"medium"},
    ),
    "low-significance": (
        "Low-significance problems",
        "scientific_significance_level",
        {"low"},
    ),
    "verification-0": (
        "Problems with fully mechanical verification",
        "verification_difficulty",
        {"0"},
    ),
    "ci-specified": (
        "Problems with a specified mechanical check",
        "ci_status",
        {"specified"},
    ),
    "delegated": (
        "Parent problems delegating verification to subproblems",
        "ci_status",
        {"delegated"},
    ),
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
    if problem.get("schema_version") != "1.0" or not problem.get("problem_id"):
        raise ValueError("only Problem Contract schema_version 1.0 is supported")
    significance = problem["scientific_significance"]
    level_order = {"high": 0, "medium": 1, "low": 2}
    significance_level = min(
        (str(item["level"]) for item in significance.values()),
        key=level_order.__getitem__,
    )
    verification = problem.get("verification_contract")
    difficulty = problem.get("verification_difficulty")
    if verification is None:
        ci_status = "delegated"
    elif any(item.get("ci_contract") for item in verification.values()):
        ci_status = "specified"
    else:
        ci_status = "manual-only"
    statement = str(problem["problem_statement"])
    problem_id = str(problem["problem_id"])
    domain = ", ".join(str(field) for field in significance)
    return {
        "schema_version": "1.0",
        "id": problem_id,
        "title": str(problem["title"]),
        "domain": domain,
        "canonical_statement": statement,
        "scientific_significance_level": significance_level,
        "scientific_significance_rationale": str(
            " ".join(item["description"] for item in significance.values())
        ),
        "verification_difficulty": (
            int(difficulty["score"]) if difficulty is not None else None
        ),
        "answer_types": list((verification or {}).keys()),
        "ci_status": ci_status,
        "subproblem_ids": list(problem["subproblem_ids"]),
        "source_nodes": [],
        "source_local_ids": [],
        "source_papers": list(problem["references"]),
        "statement_sha256": statement_fingerprint(statement),
        "search_text": normalize_text(
            " ".join([str(problem["title"]), domain, statement])
        ),
        "snapshot": f"problems/{problem_id}.json",
        "local_repo": repo_name,
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
        left_sources = set(left["source_nodes"]) | set(left["source_local_ids"])
        for right in records[index + 1 :]:
            pair = frozenset({left["id"], right["id"]})
            right_sources = set(right["source_nodes"]) | set(right["source_local_ids"])
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


def field_matches(record: dict[str, Any], field: str, values: set[Any]) -> bool:
    """Type-normalized membership check for view and filter selection.

    Values are compared as strings so an integer field such as
    verification_difficulty matches a spec written as {"0"}; unlike
    ``record.get(field) or ""`` this keeps a legitimate 0 truthy.
    """
    value = record.get(field)
    if value is None:
        return False
    return str(value).lower() in {str(item).lower() for item in values}


def filter_records(
    records: Iterable[dict[str, Any]], filters: dict[str, set[str]]
) -> list[dict[str, Any]]:
    selected = []
    for record in records:
        if all(
            field_matches(record, field, allowed)
            for field, allowed in filters.items()
            if allowed
        ):
            selected.append(record)
    return selected


def render_table(title: str, records: Iterable[dict[str, Any]]) -> str:
    rows = sorted(records, key=lambda item: item["id"])
    lines = [
        f"# {title}",
        "",
        f"Count: {len(rows)}",
        "",
        "| ID | Title | Affected fields | Significance | Verification difficulty | CI |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        verification_difficulty = row["verification_difficulty"]
        rendered_difficulty = (
            "delegated"
            if verification_difficulty is None
            else f"{verification_difficulty}/10"
        )
        lines.append(
            "| [{id}](../{snapshot}) | {title} | {domain} | {significance} | "
            "{verification_difficulty} | {ci_status} |".format(
                id=row["id"],
                snapshot=row["snapshot"],
                title=row["title"].replace("|", "\\|"),
                domain=row["domain"].replace("|", "\\|"),
                significance=row["scientific_significance_level"],
                verification_difficulty=rendered_difficulty,
                ci_status=row["ci_status"],
            )
        )
    return "\n".join(lines) + "\n"


def render_views(records: list[dict[str, Any]]) -> dict[str, str]:
    """Render every generated pool view deterministically.

    Returns a mapping of view filename to file content. The output depends
    only on ``records`` (rows are sorted by id, no timestamps), so
    ``validate_pool`` can re-render and byte-compare against disk.
    """
    views: dict[str, str] = {}
    for view_name, (title, field, values) in VIEW_SPECS.items():
        selected = [row for row in records if field_matches(row, field, values)]
        views[f"{view_name}.md"] = render_table(title, selected)
    views["all.md"] = render_table("All canonical problems", records)

    domain_groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        domain_groups.setdefault(record["domain"], []).append(record)
    domain_lines = ["# Problems by domain", ""]
    for domain, domain_records in sorted(domain_groups.items()):
        domain_lines.extend(
            [
                f"## {domain}",
                "",
                *[
                    f"- [{row['id']}](../{row['snapshot']}): {row['title']}"
                    for row in sorted(domain_records, key=lambda item: item["id"])
                ],
                "",
            ]
        )
    views["by-domain.md"] = "\n".join(domain_lines).rstrip() + "\n"
    return views


def pool_statistics(records: list[dict[str, Any]]) -> dict[str, Any]:
    fields = (
        "scientific_significance_level",
        "verification_difficulty",
        "ci_status",
    )
    return {
        "schema_version": 1,
        "total": len(records),
        "counts": {
            field: dict(
                sorted(Counter(str(row[field]) for row in records).items())
            )
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
        path.stem: path for path in pool_snapshot_paths(pool_root / "problems")
    }
    if set(ids) != set(snapshots):
        errors.append(
            "catalog/snapshot ID mismatch: "
            f"catalog={len(set(ids))} snapshots={len(snapshots)}"
        )
    for record in records:
        problem_id = record["id"]
        snapshot = load_yaml(snapshots[problem_id])
        snapshot_id = snapshot.get("problem_id")
        if snapshot_id != problem_id:
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
    for view_file, expected in render_views(records).items():
        view_path = pool_root / "views" / view_file
        if not view_path.is_file():
            errors.append(f"missing generated view: {view_file}")
        elif view_path.read_text(encoding="utf-8") != expected:
            errors.append(
                f"stale generated view: {view_file} (re-run scripts/sync_pool.py)"
            )
    return errors
