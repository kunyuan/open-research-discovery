#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml


def run(command: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=root, text=True, capture_output=True, check=False
    )


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    checked_contract = run([sys.executable, "tools/check_problem.py"], root)
    if checked_contract.returncode:
        sys.stdout.write(checked_contract.stdout)
        sys.stderr.write(checked_contract.stderr)
        return checked_contract.returncode

    problem = yaml.safe_load((root / "problem.yaml").read_text(encoding="utf-8"))
    ci_status = problem["ci_contract"]["status"]
    solution_review_scope = problem["solution_review_contract"]["scope"]
    submission_files = [
        path
        for path in (root / "submission").rglob("*")
        if path.is_file() and path.name != "README.md"
    ]
    result = {
        "problem_id": problem["id"],
        "contract_valid": True,
        "ci_status": ci_status,
        "solution_review_scope": solution_review_scope,
        "submission_present": bool(submission_files),
        "machine_result": "not-run",
        "local_validity_only": True,
    }
    if not submission_files:
        result["outcome"] = "structural-only"
        print(json.dumps(result, sort_keys=True))
        return 0

    if ci_status not in {"implemented", "partial"}:
        result["outcome"] = "solution-review-required"
        print(json.dumps(result, sort_keys=True))
        return 0

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
    result["outcome"] = (
        "machine-verified"
        if ci_status == "implemented"
        else "machine-checks-pass-solution-review-required"
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
