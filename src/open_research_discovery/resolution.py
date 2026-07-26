from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .common import dump_json, gaia_version, load_yaml, today, utc_now
from .lkm import run_gaia_knowledge


def build_resolution_queries(problem: dict[str, Any]) -> list[str]:
    question = problem.get("question") or {}
    canonical = str(question.get("canonical_statement") or "").strip()
    aliases = [str(item).strip() for item in question.get("aliases") or [] if str(item).strip()]
    if not canonical:
        raise ValueError("question.canonical_statement is required")
    queries = [
        canonical,
        (
            f"{canonical} solved resolved proof theorem counterexample "
            "refuted disproved validated"
        ),
        (
            f"{canonical} improved bound exact value benchmark special case "
            "remaining open unresolved"
        ),
        (
            f"{canonical} replication reproduction validation experiment "
            "simulation dataset benchmark"
        ),
        *aliases,
    ]
    return list(dict.fromkeys(queries))


def _safe_name(value: str, index: int) -> str:
    words = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return f"{index:02d}-{words[:60] or 'query'}"


def _compact_hit(variable: dict[str, Any], papers: dict[str, Any]) -> dict[str, Any]:
    source_packages = ((variable.get("provenance") or {}).get("source_packages") or [])
    return {
        "id": variable.get("id"),
        "type": variable.get("type"),
        "role": variable.get("role"),
        "content": variable.get("content"),
        "score": variable.get("score"),
        "rerank_score": variable.get("rerank_score"),
        "source_packages": source_packages,
        "papers": {package: papers.get(package) for package in source_packages if package in papers},
    }


def audit_resolution(
    problem_path: Path,
    *,
    out_dir: Path | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    problem = load_yaml(problem_path)
    problem_root = problem_path.parent
    run_stamp = utc_now().replace(":", "").replace("+", "-")
    if out_dir is None:
        out_dir = problem_root / "evidence" / "resolution-searches" / run_stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    for query_index, query in enumerate(build_resolution_queries(problem), start=1):
        for sort_by in ("comprehensive", "recent"):
            name = f"{_safe_name(query, query_index)}-{sort_by}.json"
            raw_path = out_dir / name
            payload = run_gaia_knowledge(
                query,
                raw_path,
                scopes=("claim", "question"),
                sort_by=sort_by,
                limit=limit,
            )
            data = payload.get("data") or {}
            papers = data.get("papers") or {}
            records.append(
                {
                    "query": query,
                    "sort_by": sort_by,
                    "raw_file": name,
                    "trace_id": payload.get("trace_id"),
                    "has_more": data.get("has_more"),
                    "hits": [
                        _compact_hit(variable, papers)
                        for variable in (data.get("variables") or [])
                    ],
                }
            )

    summary = {
        "schema_version": 1,
        "problem_id": problem.get("id"),
        "executed_at": utc_now(),
        "checked_through": today(),
        "coverage": "lkm_only",
        "gaia_version": gaia_version(),
        "review_status": "requires_human_or_agent_review",
        "allowed_outcomes": [
            "still_open",
            "partially_resolved",
            "resolved",
            "refuted",
            "uncertain",
        ],
        "warning": "No matching solution is evidence of uncertainty, not proof that the problem is still open.",
        "searches": records,
    }
    dump_json(out_dir / "summary.json", summary)
    return summary
