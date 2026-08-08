from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .common import load_yaml
from .problem_contract import validate_problem_contract

READY_RESOLUTION_STATUSES = {"still_open", "partially_resolved"}
DIRECT_STATUS_RELATIONS = {
    "closure",
    "refutation",
    "special_case",
    "improved_bound",
    "reformulation",
    "continuing_open",
}


def has_traceable_status_evidence(evidence: Any) -> bool:
    """Return whether an audit cites at least one direct, inspectable status source.

    Adjacent literature can be useful context, but it cannot by itself support a
    claim about the current status of the same research target.  Likewise,
    metadata-only search hits are leads rather than status evidence.
    """

    if not isinstance(evidence, list):
        return False
    for item in evidence:
        if not isinstance(item, dict):
            continue
        traceable = bool(
            str(item.get("title") or "").strip()
            and str(item.get("date") or "").strip()
            and str(item.get("supports") or "").strip()
            and (
                str(item.get("identifier") or "").strip()
                or str(item.get("url") or "").strip()
            )
        )
        if (
            traceable
            and item.get("content_level") != "metadata"
            and item.get("direct_support") is True
            and item.get("relation") in DIRECT_STATUS_RELATIONS
        ):
            return True
    return False


def schema_errors(instance: Any, schema: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.path))
    return [
        f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
        for error in errors
    ]


def validate_problem(problem_path: Path, schema_path: Path) -> list[str]:
    problem = load_yaml(problem_path)
    return validate_problem_contract(problem, schema_path)
