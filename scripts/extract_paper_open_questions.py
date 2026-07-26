#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from open_research_discovery.lkm import collect_paper_open_questions


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Extract dedicated open questions from one LKM paper graph. "
            "No ordinary question/problem/subproblem nodes are considered."
        )
    )
    identifiers = parser.add_mutually_exclusive_group(required=True)
    identifiers.add_argument("--paper-id")
    identifiers.add_argument("--doi")
    identifiers.add_argument("--title")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--raw-out",
        type=Path,
        help="optional path for preserving the complete papers/graph response",
    )
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    result = collect_paper_open_questions(
        paper_id=args.paper_id,
        doi=args.doi,
        title=args.title,
        raw_out=args.raw_out,
        out=args.out,
        timeout=args.timeout,
    )
    print(f"open_questions={result['count']} output={args.out}")


if __name__ == "__main__":
    main()
