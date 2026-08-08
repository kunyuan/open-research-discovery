#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from open_research_discovery.common import load_yaml
from open_research_discovery.validation import schema_errors, validate_problem


def check_schemas(root: Path) -> list[str]:
    """Every JSON schema under schemas/ must itself be a valid schema."""
    errors: list[str] = []
    for schema_path in sorted(root.glob("schemas/**/*.json")):
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
        except Exception as error:
            errors.append(f"{schema_path.relative_to(root)}: {error}")
    return errors


def check_example_configs(root: Path) -> list[str]:
    """Example campaign configs under config/ must pass the campaign schema."""
    schema = json.loads(
        (root / "schemas" / "campaign.schema.json").read_text(encoding="utf-8")
    )
    errors: list[str] = []
    for config_path in sorted(root.glob("config/*.yaml")):
        for error in schema_errors(load_yaml(config_path), schema):
            errors.append(f"{config_path.relative_to(root)}: {error}")
    return errors


def check_fixtures(root: Path) -> list[str]:
    """Checked-in fixtures must pass the schema they claim to follow."""
    errors: list[str] = []
    fixture = root / "tests" / "fixtures" / "problem-contract.json"
    for error in validate_problem(fixture, root / "schemas" / "problem.schema.json"):
        errors.append(f"{fixture.relative_to(root)}: {error}")
    return errors


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    errors = [
        *check_schemas(root),
        *check_example_configs(root),
        *check_fixtures(root),
    ]
    if errors:
        raise SystemExit("\n".join(errors))
    print("discovery validation passed")


if __name__ == "__main__":
    main()
