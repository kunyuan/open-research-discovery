from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from jsonschema import Draft202012Validator

from .contract_agents import review_problem_contract
from .problem_contract import (
    require_valid_problem_contract,
    write_problem_contract_repository,
)


CommandRunner = Callable[..., subprocess.CompletedProcess[Any]]


@dataclass(frozen=True)
class DraftSubmission:
    """Immutable coordinates for one contract revision in a Draft MR."""

    problem_id: str
    gitlab_project: str
    merge_request_iid: int
    merge_request_url: str
    source_branch: str
    target_branch: str
    commit_sha: str
    problem_path: str
    problem_sha256: str
    author_identity: str
    evidence_path: str | None = None
    evidence_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewRecord:
    """A review decision bound to exact Git and contract content."""

    problem_id: str
    gitlab_project: str
    merge_request_iid: int
    merge_request_url: str
    source_branch: str
    commit_sha: str
    problem_path: str
    problem_sha256: str
    author_identity: str
    reviewer_identity: str
    verdict: str
    concerns: tuple[str, ...]
    rationale: str
    rewrite_prompt: str
    evidence_path: str | None = None
    evidence_sha256: str | None = None
    review_prompt_sha256: str = ""
    review_schema_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["concerns"] = list(self.concerns)
        return value


def _normalized_identity(value: str) -> str:
    identity = value.strip()
    if not identity:
        raise ValueError("agent identity must not be empty")
    return identity.casefold()


def _require_independent_identities(author: str, reviewer: str) -> None:
    if _normalized_identity(author) == _normalized_identity(reviewer):
        raise ValueError("the topic main agent cannot review its own submission")


def _safe_problem_id(problem_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", problem_id):
        raise ValueError(
            "problem_id must be safe as one problems/<problem_id> path component"
        )
    return problem_id


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _evidence_bytes(
    evidence_dossier: dict[str, Any] | bytes | Path | None,
) -> tuple[bytes | None, dict[str, Any] | None]:
    if evidence_dossier is None:
        return None, None
    if isinstance(evidence_dossier, Path):
        raw = evidence_dossier.read_bytes()
    elif isinstance(evidence_dossier, bytes):
        raw = evidence_dossier
    elif isinstance(evidence_dossier, dict):
        raw = (
            json.dumps(evidence_dossier, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
    else:
        raise TypeError("evidence_dossier must be a dictionary, bytes, Path, or None")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("evidence dossier must be valid UTF-8 JSON") from error
    if not isinstance(parsed, dict):
        raise ValueError("evidence dossier must be a JSON object")
    return raw, parsed


_TOPIC_INDEX_START = "<!-- problem-contract-index:start -->"
_TOPIC_INDEX_END = "<!-- problem-contract-index:end -->"


def write_topic_readme(
    *,
    repository_dir: Path,
    schema_path: Path,
    topic_title: str = "",
) -> Path:
    """Deterministically refresh the generated problem index in root README."""

    rows: list[tuple[str, str, str]] = []
    for problem_path in sorted((repository_dir / "problems").glob("*/problem.json")):
        try:
            value = json.loads(problem_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid problem contract: {problem_path}") from error
        if not isinstance(value, dict):
            raise ValueError(f"problem contract is not an object: {problem_path}")
        require_valid_problem_contract(value, schema_path)
        problem_id = str(value["problem_id"])
        if problem_path.parent.name != problem_id:
            raise ValueError(
                f"problem directory does not match problem_id: {problem_path}"
            )
        title = str(value["title"]).replace("|", "\\|").replace("\n", " ")
        link = f"problems/{problem_id}/README.md"
        rows.append((problem_id, title, link))

    block = [
        _TOPIC_INDEX_START,
        "## Problems",
        "",
        (
            "Each problem is submitted in its own Draft MR. Merge these MRs "
            "serially so concurrent root-index updates do not overwrite one another."
        ),
        "",
        "| Problem ID | Title |",
        "|---|---|",
    ]
    block.extend(
        f"| [`{problem_id}`]({link}) | {title} |"
        for problem_id, title, link in rows
    )
    if not rows:
        block.append("| — | No problems submitted. |")
    block.append(_TOPIC_INDEX_END)
    rendered_block = "\n".join(block)

    readme_path = repository_dir / "README.md"
    existing = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""
    has_start = _TOPIC_INDEX_START in existing
    has_end = _TOPIC_INDEX_END in existing
    if has_start != has_end:
        raise ValueError("root README has an incomplete generated problem index")
    if has_start:
        prefix, remainder = existing.split(_TOPIC_INDEX_START, 1)
        _, suffix = remainder.split(_TOPIC_INDEX_END, 1)
        rendered = prefix.rstrip() + "\n\n" + rendered_block + suffix.rstrip() + "\n"
    else:
        fallback = repository_dir.name.replace("-", " ").strip().title()
        prefix = existing.rstrip() or f"# {topic_title.strip() or fallback or 'Research Topic'}"
        rendered = prefix + "\n\n" + rendered_block + "\n"
    readme_path.write_text(rendered, encoding="utf-8")
    return readme_path


def _environment(gitlab_host: str) -> dict[str, str]:
    environment = os.environ.copy()
    if gitlab_host:
        environment["GITLAB_HOST"] = gitlab_host
    return environment


def _run_text(
    command_runner: CommandRunner,
    command: list[str],
    *,
    cwd: Path,
    gitlab_host: str = "",
) -> str:
    completed = command_runner(
        command,
        cwd=cwd,
        env=_environment(gitlab_host),
        text=True,
        capture_output=True,
        check=True,
    )
    return str(completed.stdout or "").strip()


def _gitlab_api_path(gitlab_project: str, suffix: str) -> str:
    if not gitlab_project.strip():
        raise ValueError("gitlab_project must not be empty")
    return f"projects/{quote(gitlab_project.strip(), safe='')}/{suffix.lstrip('/')}"


def _merge_request_head_sha(
    *,
    gitlab_project: str,
    merge_request_iid: int,
    repository_dir: Path,
    gitlab_host: str,
    command_runner: CommandRunner,
) -> str:
    output = _run_text(
        command_runner,
        [
            "glab",
            "api",
            _gitlab_api_path(
                gitlab_project, f"merge_requests/{merge_request_iid}"
            ),
        ],
        cwd=repository_dir,
        gitlab_host=gitlab_host,
    )
    try:
        value = json.loads(output)
        sha = str(value["sha"]).strip()
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError("GitLab MR response does not contain an exact head SHA") from error
    if not sha:
        raise ValueError("GitLab MR head SHA is empty")
    return sha


def submit_problem_contract_draft(
    *,
    contract: dict[str, Any],
    schema_path: Path,
    repository_dir: Path,
    gitlab_project: str,
    author_identity: str,
    target_branch: str = "main",
    source_branch: str = "",
    topic_title: str = "",
    evidence_dossier: dict[str, Any] | bytes | Path | None = None,
    gitlab_host: str = "",
    command_runner: CommandRunner = subprocess.run,
) -> DraftSubmission:
    """Commit a new problem to an existing topic repo and open a Draft MR.

    The workflow coordinates live outside ``problem.json``. The topic main
    agent is the author; no review or approval is performed here.
    """

    require_valid_problem_contract(contract, schema_path)
    problem_id = _safe_problem_id(str(contract["problem_id"]))
    author = author_identity.strip()
    _normalized_identity(author)
    if not repository_dir.is_dir() or not (repository_dir / ".git").exists():
        raise FileNotFoundError("repository_dir must be an existing Git worktree")
    if not target_branch.strip():
        raise ValueError("target_branch must not be empty")
    branch = source_branch.strip() or f"problem/{problem_id.lower()}"
    if not branch or branch.startswith("-"):
        raise ValueError("source_branch is invalid")

    status = _run_text(
        command_runner,
        ["git", "status", "--porcelain"],
        cwd=repository_dir,
    )
    if status:
        raise RuntimeError("topic repository must be clean before draft submission")

    _run_text(
        command_runner,
        ["git", "switch", target_branch],
        cwd=repository_dir,
    )
    _run_text(
        command_runner,
        ["git", "switch", "-c", branch],
        cwd=repository_dir,
    )

    problem_dir = repository_dir / "problems" / problem_id
    if problem_dir.exists():
        raise FileExistsError(f"problem already exists in topic repo: {problem_dir}")
    problem_dir.mkdir(parents=True)
    write_problem_contract_repository(
        contract=contract,
        schema_path=schema_path,
        out_dir=problem_dir,
    )
    problem_path = (Path("problems") / problem_id / "problem.json").as_posix()
    readme_path = (Path("problems") / problem_id / "README.md").as_posix()
    problem_sha256 = _sha256_file(repository_dir / problem_path)

    dossier_bytes, _ = _evidence_bytes(evidence_dossier)
    evidence_path: str | None = None
    evidence_sha256: str | None = None
    if dossier_bytes is not None:
        evidence_path = (Path("evidence") / f"{problem_id}.json").as_posix()
        evidence_file = repository_dir / evidence_path
        evidence_file.parent.mkdir(parents=True, exist_ok=True)
        evidence_file.write_bytes(dossier_bytes)
        evidence_sha256 = _sha256_bytes(dossier_bytes)
    write_topic_readme(
        repository_dir=repository_dir,
        schema_path=schema_path,
        topic_title=topic_title,
    )

    staged_paths = [problem_path, readme_path, "README.md"]
    if evidence_path is not None:
        staged_paths.append(evidence_path)
    _run_text(
        command_runner,
        ["git", "add", *staged_paths],
        cwd=repository_dir,
    )
    _run_text(
        command_runner,
        [
            "git",
            "-c",
            "user.name=Open Research Discovery",
            "-c",
            "user.email=discovery@localhost",
            "commit",
            "-m",
            f"Submit {problem_id} for review",
        ],
        cwd=repository_dir,
    )
    commit_sha = _run_text(
        command_runner,
        ["git", "rev-parse", "HEAD"],
        cwd=repository_dir,
    )
    if not commit_sha:
        raise RuntimeError("git did not return the submitted commit SHA")
    _run_text(
        command_runner,
        ["git", "push", "-u", "origin", branch],
        cwd=repository_dir,
    )

    description = (
        f"Problem Contract: `{problem_path}`\n\n"
        f"Submitted commit: `{commit_sha}`\n\n"
        f"problem.json SHA-256: `{problem_sha256}`\n\n"
        + (
            f"Evidence dossier: `{evidence_path}`\n\n"
            f"Evidence SHA-256: `{evidence_sha256}`\n\n"
            if evidence_path is not None
            else "Evidence dossier: not supplied.\n\n"
        )
        + "This Draft MR requires an independent, commit-anchored review."
        " Problem MRs should be merged serially because each refreshes the root index."
    )
    mr_output = _run_text(
        command_runner,
        [
            "glab",
            "api",
            "--method",
            "POST",
            _gitlab_api_path(gitlab_project, "merge_requests"),
            "--raw-field",
            f"source_branch={branch}",
            "--raw-field",
            f"target_branch={target_branch}",
            "--raw-field",
            f"title=Draft: {contract['title']}",
            "--raw-field",
            f"description={description}",
        ],
        cwd=repository_dir,
        gitlab_host=gitlab_host,
    )
    try:
        mr = json.loads(mr_output)
        iid = int(mr["iid"])
        url = str(mr["web_url"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ValueError("GitLab did not return a valid Draft MR") from error
    return DraftSubmission(
        problem_id=problem_id,
        gitlab_project=gitlab_project,
        merge_request_iid=iid,
        merge_request_url=url,
        source_branch=branch,
        target_branch=target_branch,
        commit_sha=commit_sha,
        problem_path=problem_path,
        problem_sha256=problem_sha256,
        author_identity=author,
        evidence_path=evidence_path,
        evidence_sha256=evidence_sha256,
    )


def review_draft_submission(
    *,
    submission: DraftSubmission,
    reviewer_identity: str,
    topic_repository_dir: Path,
    pipeline_repository_root: Path,
    runner: Any,
    output_path: Path,
    events_path: Path,
    gitlab_host: str = "",
    command_runner: CommandRunner = subprocess.run,
) -> ReviewRecord:
    """Review the contract blob at the submitted commit without checking it out.

    This function performs no GitLab write, push, merge, or approval. A
    ``CodexRunner`` supplied here must use its read-only sandbox.
    """

    _require_independent_identities(
        submission.author_identity, reviewer_identity
    )
    configured_sandbox = getattr(runner, "sandbox", None)
    if configured_sandbox is not None and configured_sandbox != "read-only":
        raise ValueError("independent reviewer runner must use a read-only sandbox")
    if getattr(runner, "network_access", False):
        raise ValueError("independent reviewer runner must not have network access")
    if hasattr(runner, "ignore_rules") and not runner.ignore_rules:
        raise ValueError("independent reviewer runner must ignore repository rules")
    if (
        hasattr(runner, "isolate_review_credentials")
        and not runner.isolate_review_credentials
    ):
        raise ValueError("independent reviewer runner must isolate Git credentials")
    topic_root = topic_repository_dir.resolve()
    for artifact in (output_path, events_path):
        if artifact.resolve().is_relative_to(topic_root):
            raise ValueError(
                "review output and events must be stored outside the topic repository"
            )

    current_sha = _merge_request_head_sha(
        gitlab_project=submission.gitlab_project,
        merge_request_iid=submission.merge_request_iid,
        repository_dir=topic_repository_dir,
        gitlab_host=gitlab_host,
        command_runner=command_runner,
    )
    if current_sha != submission.commit_sha:
        raise RuntimeError(
            "submission is stale: the Draft MR head changed before review"
        )

    completed = command_runner(
        [
            "git",
            "show",
            f"{submission.commit_sha}:{submission.problem_path}",
        ],
        cwd=topic_repository_dir,
        env=os.environ.copy(),
        text=False,
        capture_output=True,
        check=True,
    )
    raw = completed.stdout
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if not isinstance(raw, bytes):
        raise TypeError("git show must return bytes for exact contract hashing")
    actual_hash = _sha256_bytes(raw)
    if actual_hash != submission.problem_sha256:
        raise ValueError(
            "submitted problem.json hash does not match the exact Git blob"
        )
    try:
        contract = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("submitted problem.json is not valid UTF-8 JSON") from error
    if not isinstance(contract, dict):
        raise ValueError("submitted problem.json must be an object")
    schema_path = pipeline_repository_root / "schemas" / "problem-contract.schema.json"
    require_valid_problem_contract(contract, schema_path)
    if contract["problem_id"] != submission.problem_id:
        raise ValueError("submitted contract problem_id does not match the MR anchor")

    evidence_dossier: dict[str, Any] | None = None
    if (submission.evidence_path is None) != (submission.evidence_sha256 is None):
        raise ValueError("evidence path and SHA-256 anchor must be supplied together")
    if submission.evidence_path is not None:
        expected_evidence_path = f"evidence/{submission.problem_id}.json"
        if submission.evidence_path != expected_evidence_path:
            raise ValueError("evidence dossier must use evidence/<problem_id>.json")
        evidence_completed = command_runner(
            [
                "git",
                "show",
                f"{submission.commit_sha}:{submission.evidence_path}",
            ],
            cwd=topic_repository_dir,
            env=os.environ.copy(),
            text=False,
            capture_output=True,
            check=True,
        )
        evidence_raw = evidence_completed.stdout
        if isinstance(evidence_raw, str):
            evidence_raw = evidence_raw.encode("utf-8")
        if not isinstance(evidence_raw, bytes):
            raise TypeError("git show must return bytes for exact dossier hashing")
        if _sha256_bytes(evidence_raw) != submission.evidence_sha256:
            raise ValueError("evidence dossier hash does not match the exact Git blob")
        _, evidence_dossier = _evidence_bytes(evidence_raw)

    review_metadata: dict[str, Any] = {}
    review = review_problem_contract(
        contract=contract,
        repository_root=pipeline_repository_root,
        runner=runner,
        output_path=output_path,
        events_path=events_path,
        evidence_dossier=evidence_dossier,
        metadata_out=review_metadata,
    )
    review_schema = json.loads(
        (
            pipeline_repository_root
            / "schemas"
            / "stages"
            / "problem-contract-review.schema.json"
        ).read_text(encoding="utf-8")
    )
    errors = list(Draft202012Validator(review_schema).iter_errors(review))
    if errors:
        raise ValueError(f"review output is invalid: {errors[0].message}")

    return ReviewRecord(
        problem_id=submission.problem_id,
        gitlab_project=submission.gitlab_project,
        merge_request_iid=submission.merge_request_iid,
        merge_request_url=submission.merge_request_url,
        source_branch=submission.source_branch,
        commit_sha=submission.commit_sha,
        problem_path=submission.problem_path,
        problem_sha256=submission.problem_sha256,
        author_identity=submission.author_identity,
        reviewer_identity=reviewer_identity.strip(),
        verdict=str(review["verdict"]),
        concerns=tuple(str(item) for item in review["concerns"]),
        rationale=str(review["rationale"]),
        rewrite_prompt=str(review["rewrite_prompt"]),
        evidence_path=submission.evidence_path,
        evidence_sha256=submission.evidence_sha256,
        review_prompt_sha256=str(review_metadata["prompt_sha256"]),
        review_schema_sha256=str(review_metadata["schema_sha256"]),
    )


def post_review_comment(
    *,
    review: ReviewRecord,
    repository_dir: Path,
    gitlab_host: str = "",
    command_runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    """Post an anchored review note if the MR still points at that commit.

    The deterministic controller posts the note. The reviewer agent receives
    no GitLab write credentials and this function never approves or merges.
    """

    _require_independent_identities(
        review.author_identity, review.reviewer_identity
    )
    current_sha = _merge_request_head_sha(
        gitlab_project=review.gitlab_project,
        merge_request_iid=review.merge_request_iid,
        repository_dir=repository_dir,
        gitlab_host=gitlab_host,
        command_runner=command_runner,
    )
    if current_sha != review.commit_sha:
        raise RuntimeError(
            "review is stale: the Draft MR head changed after independent review"
        )

    heading = {
        "accept": "ACCEPT",
        "rewrite": "REWRITE REQUESTED",
        "reject": "REJECT",
    }[review.verdict]
    body = (
        f"## Problem Contract Review: {heading}\n\n"
        f"Reviewer: `{review.reviewer_identity}`\n\n"
        f"Commit: `{review.commit_sha}`\n\n"
        f"problem.json SHA-256: `{review.problem_sha256}`\n\n"
        "```json\n"
        f"{json.dumps(review.to_dict(), ensure_ascii=False, indent=2)}\n"
        "```"
    )
    commit_state = "success" if review.verdict == "accept" else "failed"
    status_output = _run_text(
        command_runner,
        [
            "glab",
            "api",
            "--method",
            "POST",
            _gitlab_api_path(
                review.gitlab_project, f"statuses/{review.commit_sha}"
            ),
            "--raw-field",
            f"state={commit_state}",
            "--raw-field",
            "name=problem-contract-review",
            "--raw-field",
            f"ref={review.source_branch}",
            "--raw-field",
            f"target_url={review.merge_request_url}",
            "--raw-field",
            f"description=Independent contract review: {review.verdict}",
        ],
        cwd=repository_dir,
        gitlab_host=gitlab_host,
    )
    output = _run_text(
        command_runner,
        [
            "glab",
            "api",
            "--method",
            "POST",
            _gitlab_api_path(
                review.gitlab_project,
                f"merge_requests/{review.merge_request_iid}/notes",
            ),
            "--raw-field",
            f"body={body}",
        ],
        cwd=repository_dir,
        gitlab_host=gitlab_host,
    )
    try:
        response = json.loads(output)
    except json.JSONDecodeError:
        response = {"output": output}
    try:
        status_response = json.loads(status_output)
    except json.JSONDecodeError:
        status_response = {"output": status_output}
    return {
        "verdict": review.verdict,
        "commit_sha": review.commit_sha,
        "problem_sha256": review.problem_sha256,
        "commit_status": status_response,
        "comment": response,
    }


def revision_instruction(review: ReviewRecord) -> str:
    """Return feedback that can be sent back to the original topic session."""

    if review.verdict != "rewrite":
        raise ValueError("only a rewrite review has a revision instruction")
    concerns = "\n".join(f"- {item}" for item in review.concerns) or "- None listed."
    return (
        f"Revise {review.problem_id} from reviewed commit {review.commit_sha}.\n"
        f"The reviewed problem.json SHA-256 was {review.problem_sha256}.\n\n"
        f"Reviewer concerns:\n{concerns}\n\n"
        f"Reviewer rationale:\n{review.rationale}\n\n"
        f"Rewrite instruction:\n{review.rewrite_prompt}"
    )


def revise_problem_contract_draft(
    *,
    submission: DraftSubmission,
    review: ReviewRecord,
    contract: dict[str, Any],
    schema_path: Path,
    repository_dir: Path,
    author_identity: str,
    gitlab_host: str = "",
    command_runner: CommandRunner = subprocess.run,
) -> DraftSubmission:
    """Apply requested revisions only while the reviewed MR head is unchanged."""

    if review.verdict != "rewrite":
        raise ValueError("a new revision requires a rewrite review")
    if _normalized_identity(author_identity) != _normalized_identity(
        submission.author_identity
    ):
        raise ValueError("only the original topic main agent may revise this draft")
    _require_independent_identities(author_identity, review.reviewer_identity)
    if (
        review.commit_sha != submission.commit_sha
        or review.problem_sha256 != submission.problem_sha256
        or review.merge_request_iid != submission.merge_request_iid
        or review.evidence_path != submission.evidence_path
        or review.evidence_sha256 != submission.evidence_sha256
    ):
        raise ValueError("review anchors do not match the submitted revision")
    require_valid_problem_contract(contract, schema_path)
    if contract["problem_id"] != submission.problem_id:
        raise ValueError("revision cannot change problem_id")
    current_sha = _merge_request_head_sha(
        gitlab_project=submission.gitlab_project,
        merge_request_iid=submission.merge_request_iid,
        repository_dir=repository_dir,
        gitlab_host=gitlab_host,
        command_runner=command_runner,
    )
    if current_sha != submission.commit_sha:
        raise RuntimeError("cannot revise: Draft MR head changed after review")

    _run_text(
        command_runner,
        ["git", "switch", submission.source_branch],
        cwd=repository_dir,
    )
    local_sha = _run_text(
        command_runner,
        ["git", "rev-parse", "HEAD"],
        cwd=repository_dir,
    )
    if local_sha != submission.commit_sha:
        raise RuntimeError("local topic branch is not at the reviewed commit")
    problem_file = repository_dir / submission.problem_path
    if _sha256_file(problem_file) != submission.problem_sha256:
        raise RuntimeError("local problem.json is not the reviewed contract")

    write_problem_contract_repository(
        contract=contract,
        schema_path=schema_path,
        out_dir=problem_file.parent,
    )
    write_topic_readme(
        repository_dir=repository_dir,
        schema_path=schema_path,
    )
    readme_path = (Path(submission.problem_path).parent / "README.md").as_posix()
    _run_text(
        command_runner,
        ["git", "add", submission.problem_path, readme_path, "README.md"],
        cwd=repository_dir,
    )
    _run_text(
        command_runner,
        [
            "git",
            "-c",
            "user.name=Open Research Discovery",
            "-c",
            "user.email=discovery@localhost",
            "commit",
            "-m",
            f"Revise {submission.problem_id} after independent review",
        ],
        cwd=repository_dir,
    )
    commit_sha = _run_text(
        command_runner,
        ["git", "rev-parse", "HEAD"],
        cwd=repository_dir,
    )
    _run_text(
        command_runner,
        ["git", "push", "origin", f"HEAD:{submission.source_branch}"],
        cwd=repository_dir,
    )
    return DraftSubmission(
        problem_id=submission.problem_id,
        gitlab_project=submission.gitlab_project,
        merge_request_iid=submission.merge_request_iid,
        merge_request_url=submission.merge_request_url,
        source_branch=submission.source_branch,
        target_branch=submission.target_branch,
        commit_sha=commit_sha,
        problem_path=submission.problem_path,
        problem_sha256=_sha256_file(problem_file),
        author_identity=submission.author_identity,
        evidence_path=submission.evidence_path,
        evidence_sha256=submission.evidence_sha256,
    )
