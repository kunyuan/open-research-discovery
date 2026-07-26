#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from open_research_discovery.registry import build_registry


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build machine-readable and Markdown indexes from a pool registry."
    )
    parser.add_argument(
        "--source", type=Path, default=Path("registry/repos.yaml")
    )
    parser.add_argument(
        "--jsonl-out", type=Path, default=Path("registry/registry.jsonl")
    )
    parser.add_argument(
        "--index-out", type=Path, default=Path("registry/INDEX.md")
    )
    args = parser.parse_args()
    rows = build_registry(
        args.source,
        args.jsonl_out,
        args.index_out,
    )
    print(f"registered={len(rows)}")


if __name__ == "__main__":
    main()
