from __future__ import annotations

import fcntl
import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from .common import (
    dump_json,
    dump_yaml,
    pool_snapshot_paths,
    problem_manifest_paths,
)
from .pool import (
    dedup_candidates,
    pool_statistics,
    problem_to_record,
    validate_relations,
)
from .validation import validate_problem


class PoolSyncError(RuntimeError):
    """Raised when a pool synchronization cannot complete."""


def sync_pool(
    problem_root: Path,
    out: Path,
    *,
    problem_schema: Path,
    dedup_threshold: float = 0.25,
    preserve_existing: bool = False,
    depublish_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Synchronize a portable pool from structured problem manifests.

    An exclusive flock covers the whole catalog read-modify-write (and the
    derived projections) so concurrent campaigns sharing the pool cannot
    interleave and corrupt the catalog.
    """
    out = out.resolve()
    depublish_ids = set(depublish_ids or set())
    invalid_depublish_ids = sorted(
        problem_id
        for problem_id in depublish_ids
        if not re.fullmatch(r"ORP-[0-9]{4,}", problem_id)
    )
    if invalid_depublish_ids:
        raise PoolSyncError(
            "invalid depublish problem id(s): " + ", ".join(invalid_depublish_ids)
        )
    problems_out = out / "problems"
    problems_out.mkdir(parents=True, exist_ok=True)

    lock_path = out / ".sync.lock"
    with lock_path.open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            sources = problem_manifest_paths(problem_root)
            records_by_id: dict[str, dict[str, object]] = {}
            catalog_path = out / "catalog.jsonl"
            if preserve_existing and catalog_path.is_file():
                for line in catalog_path.read_text(
                    encoding="utf-8"
                ).splitlines():
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    # Records missing these fields would silently sort last
                    # under the ranking defaults (0 significance, clear
                    # verification), so treat them as stale rather than
                    # inheriting those defaults.
                    missing_fields = [
                        field
                        for field in (
                            "verification_difficulty",
                            "scientific_significance_score",
                            "verification_clarity",
                        )
                        if field not in record
                    ]
                    if missing_fields:
                        raise PoolSyncError(
                            f"existing catalog record "
                            f"{record.get('id', '<unknown>')} "
                            f"predates {', '.join(missing_fields)}; re-sync it "
                            "from an up-to-date problem manifest or assign "
                            "audited values"
                        )
                    records_by_id[str(record["id"])] = record

            # Validate every input before touching the pool so a mid-batch
            # failure cannot leave partially copied snapshots behind.
            validated_inputs: list[tuple[Path, dict[str, object], str]] = []
            input_ids = set()
            for source in sources:
                errors = validate_problem(source, problem_schema)
                if errors:
                    raise PoolSyncError(
                        f"{source}:\n"
                        + "\n".join(f"  - {error}" for error in errors)
                    )
                problem = yaml.safe_load(source.read_text(encoding="utf-8"))
                problem_id = str(problem["id"])
                if problem_id in input_ids:
                    raise PoolSyncError(f"duplicate problem id: {problem_id}")
                input_ids.add(problem_id)
                validated_inputs.append((source, problem, problem_id))

            overlap = input_ids & depublish_ids
            if overlap:
                raise PoolSyncError(
                    "cannot sync and depublish the same problem id(s): "
                    + ", ".join(sorted(overlap))
                )

            for source, problem, problem_id in validated_inputs:
                destination = problems_out / f"{problem_id}.yaml"
                shutil.copy2(source, destination)
                records_by_id[problem_id] = problem_to_record(
                    problem, source.parent.name
                )

            depublished_out = out / "depublished"
            for problem_id in sorted(depublish_ids):
                records_by_id.pop(problem_id, None)
                active_snapshot = problems_out / f"{problem_id}.yaml"
                if active_snapshot.is_file():
                    depublished_out.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(active_snapshot, depublished_out / active_snapshot.name)
                    active_snapshot.unlink()

            if not preserve_existing:
                for stale in pool_snapshot_paths(problems_out):
                    if stale.stem not in input_ids:
                        stale.unlink()

            records = sorted(records_by_id.values(), key=lambda row: str(row["id"]))
            problem_ids = set(records_by_id)
            with catalog_path.open("w", encoding="utf-8") as handle:
                for record in records:
                    handle.write(
                        json.dumps(record, ensure_ascii=False, sort_keys=True)
                    )
                    handle.write("\n")

            relations_path = out / "relations.yaml"
            relations = (
                yaml.safe_load(relations_path.read_text(encoding="utf-8"))
                if relations_path.exists()
                else {"schema_version": 1, "relations": []}
            ) or {"schema_version": 1, "relations": []}
            active_relations = []
            depublished_relations = []
            for relation in relations.get("relations") or []:
                if {
                    str(relation.get("source") or ""),
                    str(relation.get("target") or ""),
                } & depublish_ids:
                    depublished_relations.append(relation)
                else:
                    active_relations.append(relation)
            if depublished_relations:
                depublished_out.mkdir(parents=True, exist_ok=True)
                archived_relations_path = depublished_out / "relations.yaml"
                archived = (
                    yaml.safe_load(archived_relations_path.read_text(encoding="utf-8"))
                    if archived_relations_path.is_file()
                    else {"schema_version": 1, "relations": []}
                ) or {"schema_version": 1, "relations": []}
                archived_items = list(archived.get("relations") or [])
                for relation in depublished_relations:
                    if relation not in archived_items:
                        archived_items.append(relation)
                dump_yaml(
                    archived_relations_path,
                    {"schema_version": 1, "relations": archived_items},
                )
                relations = {**relations, "relations": active_relations}
                dump_yaml(relations_path, relations)
            relation_errors = validate_relations(relations, problem_ids)
            if relation_errors:
                raise PoolSyncError("\n".join(relation_errors))

            candidates = dedup_candidates(
                records,
                relations=relations,
                threshold=dedup_threshold,
            )
            dump_json(
                out / "dedup-candidates.json",
                {
                    "schema_version": 1,
                    "threshold": dedup_threshold,
                    "candidates": candidates,
                },
            )
            dump_yaml(out / "stats.yaml", pool_statistics(records))
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    return {
        "synced": len(records),
        "pool": str(out),
        "dedup_candidates": len(candidates),
    }
