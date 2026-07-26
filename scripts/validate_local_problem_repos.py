#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from open_research_discovery.common import problem_repo_paths


def validate_one(repo: Path) -> tuple[str, str]:
    result = subprocess.run(
        [sys.executable, "tools/check_problem.py"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = (result.stdout + result.stderr).strip()
        raise RuntimeError(detail)
    if not (repo / ".git").is_dir():
        raise RuntimeError("missing .git directory")
    if not list((repo / "evidence" / "resolution-searches").glob("*/summary.json")):
        raise RuntimeError("missing resolution-search summary")
    return repo.name, result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_root", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    repos = problem_repo_paths(args.repo_root)
    failures: list[tuple[Path, BaseException]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(validate_one, repo): repo for repo in repos}
        for job in as_completed(jobs):
            repo = jobs[job]
            try:
                name, result = job.result()
                print(f"valid={name} result={result}")
            except BaseException as exc:
                failures.append((repo, exc))
                print(f"FAILED={repo.name} error={exc}")
    print(f"valid={len(repos) - len(failures)} failed={len(failures)} total={len(repos)}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
