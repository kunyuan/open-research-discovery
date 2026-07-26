#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from open_research_discovery.common import problem_repo_paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print a compact, deduplicated review sheet for LKM resolution audits."
    )
    parser.add_argument("repo_root", type=Path)
    parser.add_argument("--hits", type=int, default=8)
    args = parser.parse_args()

    for repo in problem_repo_paths(args.repo_root):
        problem_path = repo / "problem.yaml"
        if not problem_path.exists():
            continue
        problem = yaml.safe_load(problem_path.read_text())
        source_packages = {
            f"paper:{item['paper_id']}"
            for item in problem.get("source_open_questions", [])
        }
        summaries = sorted(
            (repo / "evidence" / "resolution-searches").glob("*/summary.json")
        )
        if not summaries:
            continue
        summary = json.loads(summaries[-1].read_text())
        papers: dict[str, dict] = {}
        scores: dict[str, float] = {}
        snippets: dict[str, str] = {}
        for search in summary["searches"]:
            for hit in search["hits"]:
                rank_score = float(hit.get("rerank_score") or 0)
                for package, paper in (hit.get("papers") or {}).items():
                    if package in source_packages or not paper:
                        continue
                    if rank_score >= scores.get(package, -1):
                        papers[package] = paper
                        scores[package] = rank_score
                        snippets[package] = " ".join(
                            str(hit.get("content") or "").split()
                        )[:220]
        ranked = sorted(
            papers,
            key=lambda package: (
                str(papers[package].get("publication_date") or ""),
                scores[package],
            ),
            reverse=True,
        )
        print(f"\n{problem['id']} | {problem['title']}")
        if not ranked:
            print("  NO_NON_SOURCE_HITS")
        for package in ranked[: args.hits]:
            paper = papers[package]
            print(
                "  "
                f"{paper.get('publication_date', '')} | "
                f"{scores[package]:.3f} | "
                f"{paper.get('en_title') or paper.get('zh_title') or package}"
            )
            print(f"    {snippets[package]}")


if __name__ == "__main__":
    main()
