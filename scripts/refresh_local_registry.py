#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from open_research_discovery.common import problem_manifest_paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a pool registry from local problem repositories."
    )
    parser.add_argument("problem_root", type=Path)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("registry/repos.yaml"),
    )
    args = parser.parse_args()

    rows = []
    for problem_path in problem_manifest_paths(args.problem_root):
        problem = yaml.safe_load(problem_path.read_text(encoding="utf-8"))
        rows.append(
            {
                "id": problem["id"],
                "title": problem["title"],
                "domain": problem["domain"],
                "status": problem["status"],
                "importance_level": (
                    problem.get("research_triage", {}).get(
                        "importance_level", "unassessed"
                    )
                ),
                "post_audit_priority": (
                    problem.get("research_triage", {}).get(
                        "post_audit_priority", "unassessed"
                    )
                ),
                "route": (
                    problem.get("research_triage", {}).get(
                        "route", "unassessed"
                    )
                ),
                "review_scope": (
                    problem.get("reviewer_contract", {}).get(
                        "scope", "unclassified"
                    )
                ),
                "estimated_review_time": (
                    problem.get("reviewer_contract", {}).get(
                        "estimated_review_time", ""
                    )
                ),
                "ci_status": (
                    problem.get("ci_contract", {}).get("status", "blocked")
                ),
                "ci_estimated_runtime": (
                    problem.get("ci_contract", {}).get(
                        "estimated_runtime", ""
                    )
                ),
                "resolution_status": problem["resolution_audit"]["status"],
                "resolution_checked_at": problem["resolution_audit"]["checked_at"],
                "resolution_conclusion": (
                    problem["resolution_audit"]
                    .get("conclusion", {})
                    .get("label", "unclassified")
                ),
                "resolution_confidence": (
                    problem["resolution_audit"]
                    .get("conclusion", {})
                    .get("confidence", "unclassified")
                ),
                "source_open_question_nodes": [
                    source["node_id"]
                    for source in problem["source_open_questions"]
                ],
                "repo": f"../{problem_path.parent.name}",
            }
        )

    args.out.write_text(
        yaml.safe_dump(
            {"schema_version": 1, "repos": rows},
            sort_keys=False,
            allow_unicode=True,
            width=100,
        ),
        encoding="utf-8",
    )
    print(f"registered={len(rows)} out={args.out}")


if __name__ == "__main__":
    main()
