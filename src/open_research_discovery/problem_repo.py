from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .common import dump_yaml, iter_text_files, load_yaml, slugify, today


def create_problem_repo(
    template_dir: Path,
    out_dir: Path,
    *,
    schema_path: Path,
    problem_id: str,
    title: str,
    slug: str,
    source_node: str | None = None,
    git_init: bool = False,
) -> Path:
    normalized_slug = slugify(slug)
    if out_dir.exists():
        raise FileExistsError(f"output path already exists: {out_dir}")
    shutil.copytree(template_dir, out_dir)
    copied_schema = out_dir / "schema" / "problem.schema.json"
    copied_schema.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(schema_path, copied_schema)

    replacements = {
        "{{PROBLEM_ID}}": problem_id,
        "{{TITLE}}": title,
        "{{SLUG}}": normalized_slug,
        "{{CREATED_DATE}}": today(),
    }
    for path in iter_text_files(out_dir):
        text = path.read_text(encoding="utf-8")
        for old, new in replacements.items():
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")

    manifest_path = out_dir / "problem.yaml"
    manifest = load_yaml(manifest_path)
    if source_node:
        manifest["source_open_questions"] = [
            {
                "node_id": source_node,
                "paper_id": "",
                "local_id": "",
                "exact_text": "",
                "publication_date": "",
            }
        ]
    dump_yaml(manifest_path, manifest)

    if git_init:
        subprocess.run(["git", "init", "-b", "main"], cwd=out_dir, check=True)
    return out_dir
