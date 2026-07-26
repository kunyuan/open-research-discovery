#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import yaml

from open_research_discovery.common import dump_yaml, problem_repo_paths
from open_research_discovery.verification_contracts import (
    solution_review_and_ci_contracts_for,
    render_ci,
    render_solution_review,
    render_workflow,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Add Solution Reviewer and CI contracts to local problem repositories."
        )
    )
    parser.add_argument("problem_root", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    discovery_root = Path(__file__).resolve().parents[1]
    repos = problem_repo_paths(args.problem_root)
    changed = 0
    for repo in repos:
        problem_path = repo / "problem.yaml"
        problem = yaml.safe_load(problem_path.read_text(encoding="utf-8"))
        solution_review, ci = solution_review_and_ci_contracts_for(
            problem, repo
        )
        problem["solution_review_contract"] = solution_review
        problem["ci_contract"] = ci
        print(
            f"{'update' if args.write else 'would-update'}={problem['id']} "
            f"scope={solution_review['scope']} ci={ci['status']} "
            f"runtime={ci['estimated_runtime']}"
        )
        if not args.write:
            continue
        dump_yaml(problem_path, problem)
        shutil.copy2(
            discovery_root / "schemas" / "problem.schema.json",
            repo / "schema" / "problem.schema.json",
        )
        shutil.copy2(
            discovery_root / "template" / "tools" / "check_problem.py",
            repo / "tools" / "check_problem.py",
        )
        shutil.copy2(
            discovery_root / "template" / "tools" / "ci_verify.py",
            repo / "tools" / "ci_verify.py",
        )
        shutil.copy2(discovery_root / "template" / "Makefile", repo / "Makefile")
        (repo / "verifier" / "solution-review.md").write_text(
            render_solution_review(problem), encoding="utf-8"
        )
        (repo / "verifier" / "ci.md").write_text(
            render_ci(problem), encoding="utf-8"
        )
        (repo / ".github" / "workflows" / "verify.yml").write_text(
            render_workflow(ci["timeout_minutes"]), encoding="utf-8"
        )
        changed += 1
    print(
        f"processed={len(repos)} changed={changed} "
        f"mode={'write' if args.write else 'dry-run'}"
    )


if __name__ == "__main__":
    main()
