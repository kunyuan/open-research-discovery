#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from open_research_discovery.resolution import audit_resolution


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect later-result evidence from LKM")
    parser.add_argument("problem", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    summary = audit_resolution(args.problem, out_dir=args.out_dir, limit=args.limit)
    print(
        f"problem={summary.get('problem_id')} "
        f"searches={len(summary['searches'])} "
        f"review_status={summary['review_status']}"
    )


if __name__ == "__main__":
    main()
