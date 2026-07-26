#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from open_research_discovery.common import problem_manifest_paths
from open_research_discovery.resolution import audit_resolution


def audit_one(problem_path: Path, limit: int) -> tuple[str, str]:
    summary = audit_resolution(problem_path, limit=limit)
    return str(summary["problem_id"]), str(summary["review_status"])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run reproducible LKM resolution audits across local problem repositories."
    )
    parser.add_argument("repo_root", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--skip", action="append", default=[])
    args = parser.parse_args()

    problem_paths = problem_manifest_paths(args.repo_root)
    problem_paths = [
        path
        for path in problem_paths
        if path.parent.name.split("-", 2)[:2] != ["OMP", "0001"]
        and not any(path.parent.name.startswith(prefix) for prefix in args.skip)
    ]

    failures: list[tuple[Path, BaseException]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {
            pool.submit(audit_one, path, args.limit): path for path in problem_paths
        }
        for job in as_completed(jobs):
            path = jobs[job]
            try:
                problem_id, review_status = job.result()
                print(
                    f"audited={problem_id} status={review_status} repo={path.parent.name}",
                    flush=True,
                )
            except BaseException as exc:
                failures.append((path, exc))
                print(f"FAILED repo={path.parent.name} error={exc}", flush=True)

    print(
        f"completed={len(problem_paths) - len(failures)} "
        f"failed={len(failures)} total={len(problem_paths)}"
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
