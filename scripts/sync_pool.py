#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import re
import shutil
from pathlib import Path

import yaml

from open_research_discovery.common import (
    dump_json,
    dump_yaml,
    pool_snapshot_paths,
    problem_manifest_paths,
)
from open_research_discovery.pool import (
    dedup_candidates,
    pool_statistics,
    problem_to_record,
    render_views,
    validate_relations,
)
from open_research_discovery.validation import validate_problem


def sync_pool(
    problem_root: Path,
    out: Path,
    *,
    dedup_threshold: float = 0.25,
    preserve_existing: bool = False,
    depublish_ids: set[str] | None = None,
) -> None:
    discovery_root = Path(__file__).resolve().parents[1]
    out = out.resolve()
    depublish_ids = set(depublish_ids or set())
    invalid_depublish_ids = sorted(
        problem_id
        for problem_id in depublish_ids
        if not re.fullmatch(r"(?:ORP|OMP)-[0-9]{4,}", problem_id)
    )
    if invalid_depublish_ids:
        raise SystemExit(
            "invalid depublish problem id(s): " + ", ".join(invalid_depublish_ids)
        )
    problems_out = out / "problems"
    views_out = out / "views"
    problems_out.mkdir(parents=True, exist_ok=True)
    views_out.mkdir(parents=True, exist_ok=True)

    # An exclusive flock covers the whole catalog read-modify-write (and the
    # derived projections) so concurrent campaigns or script invocations
    # sharing the pool cannot interleave and corrupt the catalog.
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
                    if "verification_difficulty" not in record:
                        raise SystemExit(
                            f"existing catalog record "
                            f"{record.get('id', '<unknown>')} "
                            "predates verification_difficulty; re-sync it from a "
                            "schema-v2 problem manifest or assign an audited 0-10 score"
                        )
                    records_by_id[str(record["id"])] = record

            input_ids = set()
            for source in sources:
                errors = validate_problem(
                    source, discovery_root / "schemas" / "problem.schema.json"
                )
                if errors:
                    raise SystemExit(
                        f"{source}:\n"
                        + "\n".join(f"  - {error}" for error in errors)
                    )
                problem = yaml.safe_load(source.read_text(encoding="utf-8"))
                problem_id = str(problem["id"])
                if problem_id in input_ids:
                    raise SystemExit(f"duplicate problem id: {problem_id}")
                input_ids.add(problem_id)
                destination = problems_out / f"{problem_id}.yaml"
                shutil.copy2(source, destination)
                records_by_id[problem_id] = problem_to_record(
                    problem, source.parent.name
                )

            overlap = input_ids & depublish_ids
            if overlap:
                raise SystemExit(
                    "cannot sync and depublish the same problem id(s): "
                    + ", ".join(sorted(overlap))
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
                raise SystemExit("\n".join(relation_errors))

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

            for view_file, content in render_views(records).items():
                (views_out / view_file).write_text(content, encoding="utf-8")
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    print(
        f"synced={len(records)} pool={out} "
        f"dedup_candidates={len(candidates)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Synchronize a portable pool from internal structured problem records. "
            "README-first research repositories are a separate projection."
        )
    )
    parser.add_argument("problem_root", type=Path)
    parser.add_argument("--out", type=Path, default=Path("pool"))
    parser.add_argument("--dedup-threshold", type=float, default=0.25)
    parser.add_argument(
        "--preserve-existing",
        action="store_true",
        help=(
            "merge validated input records into the existing catalog without "
            "deleting legacy snapshots"
        ),
    )
    parser.add_argument(
        "--depublish-id",
        action="append",
        default=[],
        help=(
            "remove an ORP/OMP id from active catalog projections while archiving "
            "its generated pool snapshot; the independent solution repo is untouched"
        ),
    )
    args = parser.parse_args()
    sync_pool(
        args.problem_root,
        args.out,
        dedup_threshold=args.dedup_threshold,
        preserve_existing=args.preserve_existing,
        depublish_ids=set(args.depublish_id),
    )


if __name__ == "__main__":
    main()
