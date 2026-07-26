from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .common import dump_json, run_checked, utc_now

PAPER_GRAPH_URL = "https://open.bohrium.com/openapi/v1/lkm/papers/graph"
PAPER_IDENTIFIERS = ("paper_id", "doi", "title")
OPEN_QUESTION_SOURCE_PATH = "data.papers[].open_questions"


class LKMResponseError(RuntimeError):
    """The LKM API returned a failed or structurally invalid response."""


def paper_identifier(
    *,
    paper_id: str | None = None,
    doi: str | None = None,
    title: str | None = None,
) -> dict[str, str]:
    supplied = {
        key: value.strip()
        for key, value in {
            "paper_id": paper_id,
            "doi": doi,
            "title": title,
        }.items()
        if value and value.strip()
    }
    if len(supplied) != 1:
        raise ValueError("provide exactly one of paper_id, doi, or title")
    return supplied


def build_paper_graph_request(
    identifier: dict[str, str],
    *,
    access_key: str,
) -> Request:
    if set(identifier) - set(PAPER_IDENTIFIERS) or len(identifier) != 1:
        raise ValueError("identifier must contain exactly one of paper_id, doi, or title")
    if not access_key:
        raise ValueError("access_key is required")
    return Request(
        PAPER_GRAPH_URL,
        data=json.dumps(identifier, ensure_ascii=False).encode("utf-8"),
        headers={
            "accessKey": access_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )


def request_paper_graph(
    identifier: dict[str, str],
    *,
    access_key: str | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    key = access_key or os.environ.get("LKM_ACCESS_KEY", "")
    if not key:
        raise ValueError("LKM_ACCESS_KEY is not set")
    request = build_paper_graph_request(identifier, access_key=key)
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise LKMResponseError("LKM response must be a JSON object")
    return payload


def _paper_title(paper: dict[str, Any]) -> str:
    for field in ("en_title", "title", "zh_title"):
        value = paper.get(field)
        if value:
            return str(value)
    return ""


def extract_paper_open_questions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract only the dedicated paper-level open_questions entries.

    Ordinary question, problem, addressed_problems, subproblem, motivation, or
    graph nodes are deliberately invisible to this function.
    """

    code = payload.get("code")
    if code != 0:
        raise LKMResponseError(
            f"LKM papers/graph failed: code={code!r} msg={payload.get('msg', '')!r}"
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise LKMResponseError("successful LKM response is missing data")
    papers = data.get("papers")
    if not isinstance(papers, list):
        raise LKMResponseError("successful LKM response is missing data.papers[]")

    extracted: list[dict[str, Any]] = []
    for paper_record in papers:
        if not isinstance(paper_record, dict):
            raise LKMResponseError("data.papers[] entries must be objects")
        paper = paper_record.get("paper") or {}
        if not isinstance(paper, dict):
            raise LKMResponseError("data.papers[].paper must be an object")
        open_questions = paper_record.get("open_questions", [])
        if open_questions is None:
            open_questions = []
        if not isinstance(open_questions, list):
            raise LKMResponseError(
                "data.papers[].open_questions must be an array when present"
            )
        for question in open_questions:
            if not isinstance(question, dict):
                raise LKMResponseError(
                    "data.papers[].open_questions[] entries must be objects"
                )
            extracted.append(
                {
                    "content": question.get("content"),
                    "id": question.get("id"),
                    "global_id": question.get("global_id"),
                    "paper_id": paper.get("id"),
                    "paper_title": _paper_title(paper),
                    "paper_doi": paper.get("doi") or "",
                    "source_path": OPEN_QUESTION_SOURCE_PATH,
                }
            )
    return extracted


def collect_paper_open_questions(
    *,
    paper_id: str | None = None,
    doi: str | None = None,
    title: str | None = None,
    access_key: str | None = None,
    raw_out: Path | None = None,
    out: Path | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    identifier = paper_identifier(paper_id=paper_id, doi=doi, title=title)
    payload = request_paper_graph(
        identifier,
        access_key=access_key,
        timeout=timeout,
    )
    if raw_out is not None:
        dump_json(raw_out, payload)
    questions = extract_paper_open_questions(payload)
    result = {
        "schema_version": 1,
        "executed_at": utc_now(),
        "endpoint": PAPER_GRAPH_URL,
        "identifier": identifier,
        "trace_id": payload.get("trace_id"),
        "count": len(questions),
        "open_questions": questions,
    }
    if out is not None:
        dump_json(out, result)
    return result


def run_gaia_knowledge(
    query: str,
    out_path: Path,
    *,
    scopes: tuple[str, ...] = ("claim", "question"),
    sort_by: str = "comprehensive",
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Search later literature; never use these hits as source open questions."""

    command = ["gaia", "search", "lkm", "knowledge", query]
    for scope in scopes:
        command.extend(["--scopes", scope])
    command.extend(
        [
            "--sort-by",
            sort_by,
            "--offset",
            str(offset),
            "--limit",
            str(limit),
            "--include-paper-enrich",
            "--no-hint",
            "--out",
            str(out_path),
        ]
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run_checked(command)
    with out_path.open(encoding="utf-8") as handle:
        return json.load(handle)
