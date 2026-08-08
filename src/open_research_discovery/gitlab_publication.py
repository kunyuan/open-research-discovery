from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from .problem_contract import materialize_problem_contract_repository


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def publish_problem_contract_to_gitlab(
    *,
    contract: dict[str, Any],
    schema_path: Path,
    out_dir: Path,
    gitlab_project: str,
    gitlab_host: str = "",
    visibility: str = "private",
    command_runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    if visibility not in {"private", "internal", "public"}:
        raise ValueError("visibility must be private, internal, or public")
    if not gitlab_project.strip():
        raise ValueError("gitlab_project must not be empty")
    materialize_problem_contract_repository(
        contract=contract, schema_path=schema_path, out_dir=out_dir
    )
    for command in (
        ["git", "init", "-b", "main"],
        ["git", "add", "problem.json", "README.md"],
        [
            "git",
            "-c",
            "user.name=Open Research Discovery",
            "-c",
            "user.email=discovery@localhost",
            "commit",
            "-m",
            f"Initialize {contract['problem_id']}",
        ],
    ):
        command_runner(command, cwd=out_dir, text=True, capture_output=True, check=True)
    environment = os.environ.copy()
    if gitlab_host:
        environment["GITLAB_HOST"] = gitlab_host
    created = command_runner(
        [
            "glab",
            "repo",
            "create",
            gitlab_project,
            f"--{visibility}",
            "--defaultBranch",
            "main",
            "--remoteName",
            "origin",
        ],
        cwd=out_dir,
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    pushed = command_runner(
        ["git", "push", "-u", "origin", "main"],
        cwd=out_dir,
        text=True,
        capture_output=True,
        check=True,
    )
    head = command_runner(
        ["git", "rev-parse", "HEAD"],
        cwd=out_dir,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    return {
        "problem_id": contract["problem_id"],
        "gitlab_project": gitlab_project,
        "visibility": visibility,
        "repository": str(out_dir),
        "commit": head,
        "create_output": created.stdout.strip(),
        "push_output": pushed.stdout.strip(),
    }
