from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .common import load_yaml
from .validation import validate_registry


def _markdown_repo_link(repo: str, source: Path, index_out: Path) -> str:
    if "://" in repo or repo.startswith(("/", "#")):
        return repo
    repo_path = source.parent.parent / repo
    return os.path.relpath(repo_path, start=index_out.parent)


def build_registry(source: Path, jsonl_out: Path, index_out: Path) -> list[dict[str, Any]]:
    errors = validate_registry(source)
    if errors:
        raise ValueError("\n".join(errors))
    data = load_yaml(source)
    rows = sorted(data.get("repos") or [], key=lambda item: str(item.get("id")))

    jsonl_out.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    lines = [
        "# Open Problem Repository Index",
        "",
        "| ID | Title | Domain | Status | Importance | Priority | Route | Artifact | Verification | Ease | Review scope | CI | Audit date | Repository |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        repo = str(row.get("repo") or "")
        repo_link = _markdown_repo_link(repo, source, index_out)
        lines.append(
            "| {id} | {title} | {domain} | {status} | {importance} | {priority} | "
            "{route} | {artifact} | {verification} | {ease} | "
            "{review_scope} | {ci_status} | {date} | "
            "[repo]({repo}) |".format(
                id=row.get("id", ""),
                title=row.get("title", ""),
                domain=row.get("domain", ""),
                status=row.get("status", ""),
                importance=row.get("importance_level", "unassessed"),
                priority=row.get("post_audit_priority", "unassessed"),
                route=row.get("route", "unassessed"),
                artifact=row.get("artifact_type", ""),
                verification=row.get("verification_mode", "unclassified"),
                ease=row.get("verification_ease", "unclassified"),
                review_scope=row.get("review_scope", "unclassified"),
                ci_status=row.get("ci_status", "blocked"),
                date=row.get("resolution_checked_at", ""),
                repo=repo_link,
            )
        )
    index_out.parent.mkdir(parents=True, exist_ok=True)
    index_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows
