#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path

from open_research_discovery.problem_repo import create_problem_repo
from open_research_discovery.validation import validate_problem


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="problem-template-validation-") as tmp:
        rendered = Path(tmp) / "ORP-0000-template-smoke"
        create_problem_repo(
            root / "template",
            rendered,
            schema_path=root / "schemas" / "problem.schema.json",
            problem_id="ORP-0000",
            title="Template validation problem",
            slug="template-validation-problem",
        )
        checks = {
            "rendered-template/problem.yaml": validate_problem(
                rendered / "problem.yaml",
                root / "schemas" / "problem.schema.json",
            )
        }
    errors = [
        f"{name}: {error}"
        for name, findings in checks.items()
        for error in findings
    ]
    if errors:
        raise SystemExit("\n".join(errors))
    print("discovery validation passed")


if __name__ == "__main__":
    main()
