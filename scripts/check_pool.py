#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from open_research_discovery.pool import validate_pool


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the portable problem pool.")
    parser.add_argument("pool_root", type=Path, nargs="?", default=Path("pool"))
    args = parser.parse_args()
    errors = validate_pool(args.pool_root)
    if errors:
        raise SystemExit("\n".join(errors))
    print("problem pool validation passed")


if __name__ == "__main__":
    main()
