from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from open_research_discovery.agent import AgentRun
from open_research_discovery.contract_agents import (
    review_problem_contract,
    rewrite_problem_contract,
)
from open_research_discovery.cli import main as cli_main
from open_research_discovery.gitlab_publication import (
    publish_problem_contract_to_gitlab,
)
from open_research_discovery.problem_contract import (
    ProblemContractError,
    materialize_problem_contract_repository,
    render_problem_contract_readme,
    validate_problem_contract,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPOSITORY_ROOT / "schemas" / "problem-contract.schema.json"


def problem_contract() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "problem_id": "ORP-TEST-0001",
        "parent_problem_id": None,
        "subproblem_ids": [],
        "title": "A finite counterexample to the example bound",
        "abstract": "Determine whether the example bound admits a finite counterexample.",
        "background": "Objects satisfying A and B are conjectured to obey C.",
        "references": ["Example et al. (2025), The example bound."],
        "previous_progress": ["The bound is proved for objects of size at most ten."],
        "problem_statement": (
            "Find a finite object of size greater than ten satisfying A and B "
            "while strictly violating C."
        ),
        "scientific_significance": {
            "finite combinatorics": {
                "level": "high",
                "description": (
                    "A counterexample would invalidate a bound used by later "
                    "finite constructions."
                ),
            }
        },
        "solution_difficulty": [
            "The search must preserve A and B beyond the proven size regime."
        ],
        "verification_contract": {
            "counterexample": {
                "contract": (
                    "Submit a finite object of size greater than ten; it is "
                    "accepted exactly when A and B hold and exact evaluation "
                    "strictly violates C."
                ),
                "ci_contract": (
                    "Parse the object, check its size and predicates A and B, "
                    "and evaluate C with exact integer arithmetic."
                ),
            }
        },
        "verification_difficulty": {
            "score": 0,
            "rationale": (
                "All acceptance conditions are exact mechanical checks, so no "
                "residual Agent or human judgment remains."
            ),
        },
    }


def test_contract_validates_renders_and_materializes(tmp_path: Path) -> None:
    contract = problem_contract()
    assert validate_problem_contract(contract, SCHEMA_PATH) == []
    readme = render_problem_contract_readme(contract)
    assert "## Verification Contracts" in readme
    assert "### counterexample" in readme

    out = tmp_path / "problem-repo"
    materialize_problem_contract_repository(
        contract=contract,
        schema_path=SCHEMA_PATH,
        out_dir=out,
    )
    assert json.loads((out / "problem.json").read_text(encoding="utf-8")) == contract
    assert (out / "README.md").read_text(encoding="utf-8") == readme


def test_contract_cli_validates_and_renders(tmp_path: Path) -> None:
    problem = tmp_path / "problem.json"
    problem.write_text(json.dumps(problem_contract()), encoding="utf-8")
    readme = tmp_path / "README.md"

    assert cli_main(["contract", "validate", str(problem)]) == 0
    assert (
        cli_main(
            ["contract", "render", str(problem), "--out", str(readme)]
        )
        == 0
    )
    assert "## Problem Statement" in readme.read_text(encoding="utf-8")


def test_parent_can_delegate_verification_to_subproblems() -> None:
    contract = problem_contract()
    contract["subproblem_ids"] = ["ORP-TEST-0002"]
    contract["solution_difficulty"] = []
    contract["verification_contract"] = None
    contract["verification_difficulty"] = None
    assert validate_problem_contract(contract, SCHEMA_PATH) == []

    contract["subproblem_ids"] = []
    errors = validate_problem_contract(contract, SCHEMA_PATH)
    assert "a problem without subproblems requires verification_contract" in errors


class FakeContractRunner:
    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output
        self.role = ""
        self.prompt = ""

    def run(self, **kwargs: Any) -> AgentRun:
        self.role = kwargs["role"]
        self.prompt = kwargs["prompt"]
        kwargs["output_path"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["output_path"].write_text(
            json.dumps(self.output, ensure_ascii=False), encoding="utf-8"
        )
        kwargs["events_path"].write_text("{}\n", encoding="utf-8")
        return AgentRun(output=self.output, metadata={"fake": True})


def test_contract_review_uses_schema_as_review_boundary(tmp_path: Path) -> None:
    output = {
        "problem_id": "ORP-TEST-0001",
        "verdict": "accept",
        "concerns": [],
        "rationale": "The acceptance boundary is exact and complete.",
        "rewrite_prompt": "",
    }
    runner = FakeContractRunner(output)
    review = review_problem_contract(
        contract=problem_contract(),
        repository_root=REPOSITORY_ROOT,
        runner=runner,
        output_path=tmp_path / "review.json",
        events_path=tmp_path / "review.events.jsonl",
    )
    assert review == output
    assert runner.role == "problem-contract-reviewer"
    assert "Do not solve the research problem" in runner.prompt


def test_contract_rewrite_preserves_problem_id_and_revalidates(tmp_path: Path) -> None:
    contract = problem_contract()
    agent_content = {
        "parent_problem_id": "",
        "subproblem_ids": [],
        "title": contract["title"],
        "abstract": "A more precise short overview.",
        "background": contract["background"],
        "references": contract["references"],
        "previous_progress": contract["previous_progress"],
        "problem_statement": contract["problem_statement"],
        "scientific_significance": [
            {
                "field": "finite combinatorics",
                "level": "high",
                "description": contract["scientific_significance"]
                ["finite combinatorics"]["description"],
            }
        ],
        "solution_difficulty": contract["solution_difficulty"],
        "verification_contracts": [
            {
                "answer_type": "counterexample",
                **contract["verification_contract"]["counterexample"],
            }
        ],
        "verification_difficulty_score": 0,
        "verification_difficulty_rationale": contract[
            "verification_difficulty"
        ]["rationale"],
    }
    runner = FakeContractRunner(agent_content)
    output_path = tmp_path / "rewritten.json"
    rewritten = rewrite_problem_contract(
        contract=contract,
        instruction="Clarify only the abstract.",
        repository_root=REPOSITORY_ROOT,
        runner=runner,
        agent_output_path=tmp_path / "agent.json",
        events_path=tmp_path / "events.jsonl",
        output_path=output_path,
    )
    assert rewritten["problem_id"] == contract["problem_id"]
    assert rewritten["abstract"] == "A more precise short overview."
    assert validate_problem_contract(rewritten, SCHEMA_PATH) == []
    assert json.loads(output_path.read_text(encoding="utf-8")) == rewritten


def test_contract_rewrite_rejects_empty_instruction(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        rewrite_problem_contract(
            contract=problem_contract(),
            instruction=" ",
            repository_root=REPOSITORY_ROOT,
            runner=FakeContractRunner({}),
            agent_output_path=tmp_path / "agent.json",
            events_path=tmp_path / "events.jsonl",
            output_path=tmp_path / "rewritten.json",
        )


def test_gitlab_publication_materializes_and_runs_explicit_commands(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def command_runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        stdout = "abc123\n" if command == ["git", "rev-parse", "HEAD"] else "ok\n"
        return subprocess.CompletedProcess(command, 0, stdout, "")

    out = tmp_path / "published"
    result = publish_problem_contract_to_gitlab(
        contract=problem_contract(),
        schema_path=SCHEMA_PATH,
        out_dir=out,
        gitlab_project="example/problems/orp-test-0001",
        visibility="private",
        command_runner=command_runner,
    )
    assert result["commit"] == "abc123"
    assert ["git", "add", "problem.json", "README.md"] in calls
    assert calls[-2] == ["git", "push", "-u", "origin", "main"]
    assert (out / "problem.json").is_file()
