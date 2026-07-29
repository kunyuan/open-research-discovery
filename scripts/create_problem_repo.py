#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from open_research_discovery.problem_repo import create_problem_repo


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Create one agent-ready problem repository")
    parser.add_argument("--id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-node")
    parser.add_argument(
        "--with-zh-translation",
        action="store_true",
        help="also create README.zh-CN.md as a faithful translation scaffold",
    )
    parser.add_argument("--git-init", action="store_true")
    args = parser.parse_args()
    path = create_problem_repo(
        root / "template",
        args.out,
        problem_id=args.id,
        title=args.title,
        slug=args.slug,
        source_node=args.source_node,
        include_zh_translation=args.with_zh_translation,
        git_init=args.git_init,
    )
    print(path)


if __name__ == "__main__":
    main()
