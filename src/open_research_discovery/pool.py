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
    "ready": ("Operational verifier-ready problems", "status", {"ready"}),
    "candidate-result": (
        "Scientifically important research candidates",
        "route",
        {"candidate-result"},
    ),
    "status-audit": ("Needs current-status audit", "route", {"status-audit"}),
    "reformulation": (
        "Needs source-grounded reformulation",
        "route",
        {"reformulation"},
    ),
    "confirmed-open": (
        "Open with strong later-literature support",
        "resolution_conclusion",
        {"confirmed_open"},
    ),
    "likely-open": (
        "Likely open after citation-chain audit",
        "resolution_conclusion",
        {"likely_open"},
    ),
    "manual-review": ("Expert-review research problems", "route", {"manual-review"}),
    "closed": ("Closed or externally resolved", "route", {"closed"}),
    "derived-audit": (
        "Post-progress derived-problem audit",
        "route",
        {"derived-audit"},
    ),
    "verification-0": (
        "Final-result-scoped verification contracts",
        "verification_difficulty",
        {"0"},
    ),
    "ci-implemented": (
        "Problems with implemented substantive CI",
        "ci_status",
        {"implemented"},
    ),
    "ci-pseudocode": (
        "Problems whose substantive CI is still pseudocode",
        "ci_status",
        {"pseudocode"},
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
    question = problem.get("question") or {}
    triage = problem.get("research_triage") or {}
    contract = problem.get("discovery_contract") or {}
    solution_review = problem.get("solution_review_contract") or {}
    ci = problem.get("ci_contract") or {}
    audit = problem.get("resolution_audit") or {}
    conclusion = audit.get("conclusion") or {}
    progress = audit.get("progress_assessment") or {}
    sources = problem.get("sources") or problem.get("source_open_questions") or []
    importance = problem.get("importance") or {}
    statement = str(question.get("canonical_statement") or "")
    aliases = [str(value) for value in question.get("aliases") or []]
    # Only problem-level nodes may feed the shared-sources dedup signal:
    # source_open_questions entries carry node_id, and lkm_open_question
    # generic sources carry the open-question node id as their identifier.
    # A book/paper/web identifier names the whole work, not the question, so
    # counting it would flag every problem sourced from the same work as a
    # 1.0-scored duplicate.
    source_nodes = sorted(
        {
            str(source.get("node_id") or source.get("identifier") or "")
            for source in sources
            if (source.get("node_id") or source.get("identifier"))
            and source.get("kind", "lkm_open_question") == "lkm_open_question"
        }
    )
    source_local_ids = sorted(
        {
            str(source.get("local_id") or "")
            for source in sources
            if source.get("local_id")
        }
    )
    source_papers = sorted(
        {
            str(source.get("paper_id") or "")
            for source in sources
            if source.get("paper_id")
        }
    )
    search_text = " ".join(
        [
            str(problem.get("title") or ""),
            str(problem.get("domain") or ""),
            statement,
            *aliases,
        ]
    )
    return {
        "schema_version": 2,
        "id": str(problem["id"]),
        "title": str(problem["title"]),
        "domain": str(problem.get("domain") or ""),
        "topic_id": str(problem.get("topic_id") or problem.get("domain") or ""),
        "status": str(problem.get("status") or ""),
        "resolution_status": str(audit.get("status") or ""),
        "resolution_checked_at": str(audit.get("checked_at") or ""),
        "resolution_conclusion": str(conclusion.get("label") or "unclassified"),
        "resolution_confidence": str(conclusion.get("confidence") or "unclassified"),
        "resolution_rationale": str(conclusion.get("rationale") or ""),
        "canonical_statement": statement,
        "aliases": aliases,
        "importance_level": str(triage.get("importance_level") or "unassessed"),
        "scientific_significance_score": int(
            importance.get("scientific_significance_score", 0)
        ),
        "scientific_significance_rationale": str(
            importance.get("scientific_significance_rationale") or ""
        ),
        "audit_priority": str(triage.get("audit_priority") or "unassessed"),
        "post_audit_priority": str(triage.get("post_audit_priority") or "unassessed"),
        "route": str(triage.get("route") or "unassessed"),
        "max_verification_difficulty": int(
            triage.get(
                "max_verification_difficulty",
                3,
            )
        ),
        "verification_threshold_applied": bool(
            triage.get("verification_threshold_applied", True)
        ),
        "verification_difficulty": int(
            solution_review.get("verification_difficulty", 10)
        ),
        "verification_clarity": str(
            solution_review.get("verification_clarity") or "clear"
        ),
        "answer_types": [str(value) for value in contract.get("answer_types") or []],
        "estimated_solution_review_time": str(
            solution_review.get("estimated_review_time") or ""
        ),
        "ci_status": str(ci.get("status") or "blocked"),
        "ci_estimated_runtime": str(ci.get("estimated_runtime") or ""),
        "ci_timeout_minutes": int(ci.get("timeout_minutes") or 0),
        "progress_decision": str(progress.get("decision") or "unassessed"),
        "derived_problem_ids": sorted(
            str(value) for value in progress.get("derived_problem_ids") or []
        ),
        "source_nodes": source_nodes,
        "source_local_ids": source_local_ids,
        "source_papers": source_papers,
        "statement_sha256": statement_fingerprint(statement),
        "search_text": normalize_text(search_text),
        "snapshot": f"problems/{problem['id']}.yaml",
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
        "| ID | Title | Domain | Status | Importance | Priority | Route | Verification difficulty | CI |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| [{id}](../{snapshot}) | {title} | {domain} | {status} | "
            "{importance} | {priority} | {route} | {verification_difficulty}/10 | "
            "{ci_status} |".format(
                id=row["id"],
                snapshot=row["snapshot"],
                title=row["title"].replace("|", "\\|"),
                domain=row["domain"].replace("|", "\\|"),
                status=row["status"],
                importance=row["importance_level"],
                priority=row["post_audit_priority"],
                route=row["route"],
                verification_difficulty=row["verification_difficulty"],
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
        "status",
        "resolution_status",
        "resolution_conclusion",
        "resolution_confidence",
        "importance_level",
        "post_audit_priority",
        "route",
        "verification_difficulty",
        "ci_status",
    )
    return {
        "schema_version": 1,
        "total": len(records),
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
        if snapshot.get("id") != problem_id:
            errors.append(f"{problem_id} snapshot id mismatch")
        statement = str(
            (snapshot.get("question") or {}).get("canonical_statement") or ""
        )
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
