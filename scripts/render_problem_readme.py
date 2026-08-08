#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from open_research_discovery.problem_contract import (
    load_problem_contract,
    render_problem_contract_readme,
    validate_problem_readme,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Render README.md deterministically from one Problem Contract."
        )
    )
    parser.add_argument("problem", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    problem = load_problem_contract(args.problem)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        render_problem_contract_readme(problem),
        encoding="utf-8",
    )
    errors = validate_problem_readme(args.out, problem)
    if errors:
        raise SystemExit("\n".join(errors))
    print(args.out)


if __name__ == "__main__":
    main()
