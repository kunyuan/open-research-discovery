#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from open_research_discovery.problem_repo import (
    render_problem_readme,
    validate_problem_readme,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Render a human-facing README from one internal structured problem record."
        )
    )
    parser.add_argument("problem", type=Path)
    parser.add_argument("--assessment", type=Path)
    parser.add_argument("--annotated-references", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    problem = yaml.safe_load(args.problem.read_text(encoding="utf-8")) or {}
    assessment = (
        json.loads(args.assessment.read_text(encoding="utf-8"))
        if args.assessment
        else None
    )
    annotated_references = (
        args.annotated_references.read_text(encoding="utf-8")
        if args.annotated_references
        else ""
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        render_problem_readme(problem, assessment, annotated_references),
        encoding="utf-8",
    )
    errors = validate_problem_readme(args.out)
    if errors:
        raise SystemExit("\n".join(errors))
    print(args.out)


if __name__ == "__main__":
    main()
