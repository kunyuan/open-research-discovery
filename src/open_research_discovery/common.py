from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import yaml


PROBLEM_ID_PREFIXES = ("ORP-", "OMP-")
PROBLEM_ID_PATTERN = r"^(?:ORP|OMP)-[0-9]{4,}$"


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def today() -> str:
    return datetime.now(UTC).date().isoformat()


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data or {}


def dump_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            data,
            handle,
            allow_unicode=True,
            sort_keys=False,
            width=100,
        )


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def dump_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def run_checked(command: list[str], cwd: Path | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout


def gaia_version() -> str:
    return run_checked(["gaia", "--version"]).strip()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise ValueError("slug is empty after normalization")
    return slug


def iter_text_files(root: Path) -> Iterable[Path]:
    text_suffixes = {
        "",
        ".bib",
        ".json",
        ".md",
        ".py",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in text_suffixes:
            yield path


def problem_manifest_paths(root: Path) -> list[Path]:
    """Return current and legacy problem manifests in stable ID order."""

    return sorted(
        {
            path
            for prefix in PROBLEM_ID_PREFIXES
            for path in root.glob(f"{prefix}*/problem.yaml")
        },
        key=lambda path: path.parent.name,
    )


def problem_repo_paths(root: Path) -> list[Path]:
    return [path.parent for path in problem_manifest_paths(root)]


def pool_snapshot_paths(root: Path) -> list[Path]:
    return sorted(
        {
            path
            for prefix in PROBLEM_ID_PREFIXES
            for path in root.glob(f"{prefix}*.yaml")
        },
        key=lambda path: path.name,
    )
