#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path

from open_research_discovery.problem_repo import (
    create_problem_repo,
    validate_problem_readme,
    validate_problem_translation,
)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="problem-template-validation-") as tmp:
        rendered = Path(tmp) / "ORP-0000-template-smoke"
        create_problem_repo(
            root / "template",
            rendered,
            problem_id="ORP-0000",
            title="Template validation problem",
            slug="template-validation-problem",
            include_zh_translation=True,
        )
        checks = {
            "rendered-template/README.md": validate_problem_readme(
                rendered / "README.md"
            ),
            "rendered-template/README.zh-CN.md": validate_problem_translation(
                rendered / "README.zh-CN.md"
            ),
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
