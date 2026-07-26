#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml


def run(command: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    contract = run([sys.executable, "tools/check_problem.py"], root)
    if contract.returncode:
        sys.stdout.write(contract.stdout)
        sys.stderr.write(contract.stderr)
        return contract.returncode

    problem = yaml.safe_load((root / "problem.yaml").read_text(encoding="utf-8"))
    mode = problem["discovery_contract"]["verification_profile"]["mode"]
    ci_status = problem["ci_contract"]["status"]
    submission_files = [
        path
        for path in (root / "submission").rglob("*")
        if path.is_file() and path.name != "README.md"
    ]
    unit_test_files = sorted((root / "verifier").glob("test_*.py"))
    if unit_test_files:
        unit_tests = run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "verifier",
                "-p",
                "test_*.py",
            ],
            root,
        )
        if unit_tests.returncode:
            sys.stdout.write(unit_tests.stdout)
            sys.stderr.write(unit_tests.stderr)
            return unit_tests.returncode

    result = {
        "problem_id": problem["id"],
        "contract_valid": True,
        "ci_status": ci_status,
        "verifier_unit_tests": len(unit_test_files),
        "submission_present": bool(submission_files),
        "machine_result": "not-run",
        "manual_review_required": mode
        in {"llm-reviewable", "hybrid", "expert-review", "unclassified"},
        "local_validity_only": True,
    }
    if not submission_files:
        result["outcome"] = "structural-only"
        print(json.dumps(result, sort_keys=True))
        return 0

    if ci_status == "blocked":
        result["outcome"] = "protocol-incomplete"
        result["machine_result"] = "not-applicable"
        print(json.dumps(result, sort_keys=True))
        return 2

    if mode in {"machine-checkable", "hybrid"}:
        verifier = root / "verifier" / "check.py"
        verifier_text = verifier.read_text(encoding="utf-8") if verifier.exists() else ""
        if not verifier.exists() or "verifier_not_implemented" in verifier_text:
            result["outcome"] = "protocol-incomplete"
            result["machine_result"] = "not-implemented"
            print(json.dumps(result, sort_keys=True))
            return 2
        checked = run([sys.executable, "verifier/check.py", "submission"], root)
        sys.stdout.write(checked.stdout)
        sys.stderr.write(checked.stderr)
        if checked.returncode:
            return checked.returncode
        result["machine_result"] = "pass"

    if result["manual_review_required"]:
        result["outcome"] = "manual-review-required"
    else:
        result["outcome"] = "machine-verified"
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
