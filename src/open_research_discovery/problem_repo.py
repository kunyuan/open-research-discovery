from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .common import iter_text_files, slugify, today


README_SECTIONS = (
    "The Research Problem",
    "Why It Matters",
    "Expected Results",
    "Difficulty",
    "Verification Difficulty",
    "Possible CI",
    "Current Research Status",
    "LKM and References",
)

README_ZH_SECTIONS = (
    "研究问题",
    "为什么重要",
    "期望成果",
    "难度判断",
    "验证难度",
    "可考虑的 CI",
    "当前研究状态",
    "LKM 与参考文献",
)


def _text(value: object, fallback: str = "To be completed.") -> str:
    rendered = str(value or "").strip()
    return rendered or fallback


def _public_text(value: object, fallback: str = "To be completed.") -> str:
    rendered = _text(value, "")
    replacements = {
        (
            "This repository tracks the primary canonical target. "
            "Related source-paper questions are preserved in OPEN_QUESTIONS.md."
        ): (
            "This repository tracks only the canonical target stated above; "
            "neighboring questions in the source LKM record are outside its scope."
        ),
        "submission/candidate.json": "`candidate.json`",
        "submission/solution.md": "`solution.md`",
        "under submission/": "included in the final submission",
    }
    for old, new in replacements.items():
        rendered = rendered.replace(old, new)
    return rendered or fallback


def _bullet_lines(values: list[object], fallback: str = "To be completed.") -> list[str]:
    rendered = [_text(value, "") for value in values]
    rendered = [value for value in rendered if value]
    if not rendered:
        return [f"- {fallback}"]

    lines: list[str] = []
    for value in rendered:
        first, *continuation = value.splitlines()
        lines.append(f"- {first}")
        lines.extend(f"  {line}" if line else "" for line in continuation)
    return lines


def _prose_blocks(values: list[object]) -> list[str]:
    rendered = [_text(value, "") for value in values]
    rendered = [value for value in rendered if value]
    lines: list[str] = []
    for value in rendered:
        lines.extend(value.splitlines())
        lines.append("")
    if lines:
        lines.pop()
    return lines


def _review_intro(difficulty: int) -> str:
    if difficulty == 0:
        return (
            "Verification difficulty is `0/10`: every load-bearing claim is "
            "discharged by mechanical checks, replay, or certificates, with "
            "trivial specification fidelity. No derivation review or holistic "
            "judgment remains. The check need not "
            "be automated or implemented in CI."
        )
    if difficulty == 10:
        return (
            "Verification difficulty is `10/10`: the essential claim cannot be "
            "decomposed into independently checkable units, so correctness "
            "depends on holistic review of the argument as a whole."
        )
    return (
        f"Verification difficulty is `{difficulty}/10`: after the delegable "
        "checks, the reviewer must still perform some local reasoning about "
        "the derivation or specification fidelity supporting the result. "
        "Higher scores indicate more numerous, deeper, or more dependent "
        "load-bearing arguments."
    )


def _render_sources(
    problem: dict[str, Any],
    annotated_references: str = "",
) -> list[str]:
    lines = ["### LKM", ""]
    sources = problem.get("source_open_questions") or []
    if not sources:
        lines.append("- No LKM open-question source has been registered.")
    for source in sources:
        paper_id = _text(source.get("paper_id"), "unknown-paper")
        node_id = _text(source.get("node_id"), "unknown-open-question")
        title = _text(source.get("paper_title"), "Unregistered paper title")
        doi = _text(source.get("paper_doi"), "")
        identifier = f"LKM paper `{paper_id}` / open question `{node_id}`"
        if doi:
            identifier += f" / DOI `{doi}`"
        lines.append(
            f"- {identifier} — {title}. This is the source `open_questions` "
            "node that posed or preserved the problem; the problem was not "
            "inferred from an ordinary question or surrounding prose."
        )

    lines.extend(["", "### References", ""])
    if annotated_references.strip():
        lines.extend(_clean_annotated_references(annotated_references))
        return lines
    seen: set[tuple[str, str]] = set()
    citations: list[tuple[str, str, str]] = []
    audit = problem.get("resolution_audit") or {}
    for item in audit.get("evidence") or []:
        title = _text(item.get("citation") or item.get("title"), "")
        url = _text(item.get("url"), "")
        relation = _text(item.get("finding") or item.get("supports"), "")
        if not title or (title, url) in seen:
            continue
        seen.add((title, url))
        citations.append((title, url, relation))
    if not citations:
        for source in sources:
            title = _text(source.get("paper_title"), "")
            doi = _text(source.get("paper_doi"), "")
            if not title:
                continue
            url = f"https://doi.org/{doi}" if doi else ""
            if (title, url) not in seen:
                seen.add((title, url))
                citations.append(
                    (title, url, "Contains the source open question for this repository.")
                )
    if not citations:
        lines.append("1. Verified primary references remain to be added.")
    else:
        for index, (title, url, relation) in enumerate(citations, start=1):
            linked = f"[{title}]({url})" if url else title
            suffix = f" — {relation}" if relation else ""
            lines.append(f"{index}. {linked}{suffix}")
    return lines


def _clean_annotated_references(text: str) -> list[str]:
    """Keep bibliography prose while removing duplicated audit/template material."""

    lines = text.strip().splitlines()
    last_title = max(
        (
            index
            for index, line in enumerate(lines)
            if line.strip() in {"# Annotated references", "# Annotated bibliography"}
        ),
        default=-1,
    )
    if last_title >= 0:
        lines = lines[last_title + 1 :]

    cleaned: list[str] = []
    for line in lines:
        if line.startswith("## ") and (
            "deep status audit" in line.lower()
            or "later resolution evidence" in line.lower()
        ):
            break
        if line.startswith("### "):
            cleaned.append("##### " + line[4:])
        elif line.startswith("## "):
            cleaned.append("#### " + line[3:])
        elif line.startswith("# "):
            cleaned.append("#### " + line[2:])
        else:
            cleaned.append(line)

    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    return cleaned or ["1. Verified primary references remain to be added."]


def normalize_gitlab_math(text: str) -> str:
    """Normalize common LaTeX delimiters to GitLab Flavored Markdown."""

    text = re.sub(r"(?<!\\)\\\[", "$$", text)
    text = re.sub(r"(?<!\\)\\\]", "$$", text)
    text = re.sub(r"(?<!\\)\\\(", "$", text)
    return re.sub(r"(?<!\\)\\\)", "$", text)


def render_problem_readme(
    problem: dict[str, Any],
    assessment: dict[str, Any] | None = None,
    annotated_references: str = "",
) -> str:
    """Render the human-facing projection of an internal problem record."""

    question = problem.get("question") or {}
    importance = problem.get("importance") or {}
    audit = problem.get("resolution_audit") or {}
    conclusion = audit.get("conclusion") or {}
    discovery = problem.get("discovery_contract") or {}
    review = problem.get("solution_review_contract") or {}
    ci = problem.get("ci_contract") or {}
    compute = problem.get("compute") or {}
    progress = audit.get("progress_assessment") or {}

    assessment = assessment or {}
    expected_result = (
        assessment.get("expected_result")
        or discovery.get("expected_result")
        or "Submit a complete research result that directly answers the problem."
    )
    review_checks = assessment.get("solution_review_checklist") or []
    if not review_checks and review.get("acceptance_boundary"):
        review_checks = [review["acceptance_boundary"]]
    ci_steps = assessment.get("ci_pseudocode") or ci.get("pseudocode") or []
    if isinstance(ci_steps, str):
        ci_steps = [ci_steps]
    # Pointer strings such as "README.md#possible-ci" refer back to this
    # document instead of describing a check; without an assessment they are
    # the only ci_contract.pseudocode the manifest ever records, so drop
    # them instead of rendering a meaningless bullet list.
    ci_steps = [
        step
        for step in ci_steps
        if not re.fullmatch(r"[^\s]+\.(md|txt)(#.*)?", str(step).strip())
    ]

    definitions = question.get("definitions") or []
    problem_lines: list[str] = []
    if definitions:
        problem_lines.extend(_prose_blocks(definitions))
        problem_lines.append("")
    problem_lines.extend(
        [
            "Against this background, this repository focuses on the following problem:",
            "",
            _public_text(question.get("canonical_statement")),
            "",
        ]
    )
    if question.get("scope"):
        problem_lines.extend(
            [
                "The specific scope of this repository is:",
                "",
                _public_text(question.get("scope")),
                "",
            ]
        )

    difficulty_parts = [
        (
            "Solving difficulty is not part of the discovery ranking. This assessment "
            "only helps a research agent estimate the knowledge, tools, and compute "
            "that may be required."
        ),
        (
            "On the literature checked through the audit date, this remains a "
            "frontier open problem with substantial uncertainty about a complete "
            "solution path."
        ),
        _public_text(importance.get("current_best_result"), ""),
        _public_text(compute.get("notes"), ""),
    ]
    resource_lines = [
        value
        for value in (
            _public_text(compute.get("expected_scale"), ""),
            _public_text(compute.get("cpu"), ""),
            _public_text(compute.get("gpu"), ""),
        )
        if value and "No solver campaign is authorized" not in value
    ]

    status_lines = [
        f"- Audit date: `{_text(audit.get('checked_at') or audit.get('checked_through'))}`",
        f"- Current judgment: `{_text(conclusion.get('label') or audit.get('status'))}`",
        f"- Confidence: `{_text(conclusion.get('confidence'), 'Not stated')}`",
        f"- Surviving open core: {_text(audit.get('surviving_open_core'))}",
        f"- Research judgment: {_text(conclusion.get('rationale'))}",
    ]
    if progress.get("major_progress_found"):
        status_lines.append(
            f"- Major progress and its effect: {_text(progress.get('effect'))}"
        )
    if conclusion.get("literature_treatment"):
        status_lines.append(
            "- Treatment in later literature: "
            f"{_text(conclusion.get('literature_treatment'))}"
        )

    lines = [
        f"# {_text(problem.get('title'), 'Open Research Problem')}",
        "",
        _public_text(question.get("canonical_statement")),
        "",
        "## The Research Problem",
        "",
        *problem_lines,
        "## Why It Matters",
        "",
        _public_text(importance.get("motivation")),
        "",
        _public_text(importance.get("consequences_of_progress")),
        "",
        "## Expected Results",
        "",
        _public_text(expected_result),
        "",
    ]
    lines.extend(
        [
            "## Difficulty",
            "",
            *[part for part in difficulty_parts if part],
            "",
        ]
    )
    if resource_lines:
        lines.extend(
            ["Potentially required resources include:", "", *_bullet_lines(resource_lines), ""]
        )
    lines.extend(
        [
            "## Verification Difficulty",
            "",
            _review_intro(int(review.get("verification_difficulty", 10))),
            "",
            _public_text(review.get("rationale"), ""),
            "",
            f"Estimated review time: {_text(review.get('estimated_review_time'))}",
            "",
            "At minimum, the reviewer should confirm:",
            "",
            *_bullet_lines(review_checks),
            "",
            "The review should also determine whether the submission truly answers "
            "the original problem, whether an equivalent or stronger result already "
            "exists, and whether a partial result constitutes substantive progress.",
            "",
            "## Possible CI",
            "",
        ]
    )
    if ci.get("status") in {"blocked", "solution-reviewer-only"}:
        lines.extend(
            [
                "No automated criterion currently captures the scientific conclusion "
                "well enough; evaluation should primarily rely on reviewer judgment.",
                "",
            ]
        )
    else:
        ci_intro = (
            "The repository provides `.gitlab-ci.yml` and an independent verifier "
            "that can run against a submitted result."
            if ci.get("status") == "implemented"
            else "A scientifically meaningful automated criterion is known, but "
            "a reusable CI implementation has not yet been supplied."
        )
        lines.extend(
            [
                ci_intro,
                "",
                f"Suggested runner: {_text(ci.get('runner'))}",
                "",
                f"Estimated runtime: {_text(ci.get('estimated_runtime'))}",
                "",
            ]
        )
        if ci_steps:
            lines.extend(
                [
                    "Scientifically meaningful automated checks may include:",
                    "",
                    *_bullet_lines(ci_steps),
                    "",
                ]
            )
    lines.extend(
        [
            "Automated checks establish only the criteria they encode. They cannot "
            "by themselves establish novelty, scientific interpretation, or claims "
            "outside the scope of this problem.",
            "",
            "## Current Research Status",
            "",
            *status_lines,
            "",
            "Future changes in status should update this section through commits and "
            "merge requests so that the evolution of the research judgment remains "
            "visible in Git history.",
            "",
            "## LKM and References",
            "",
            *_render_sources(problem, annotated_references),
            "",
        ]
    )
    return normalize_gitlab_math("\n".join(lines).rstrip() + "\n")


def validate_problem_readme(path: Path) -> list[str]:
    if not path.is_file():
        return ["missing README.md"]
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    if not text.startswith("# "):
        errors.append("README.md must start with a problem title")
    if re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", text):
        errors.append(
            "README.md must be entirely English; put Chinese text in README.zh-CN.md"
        )
    positions = []
    for section in README_SECTIONS:
        marker = f"## {section}"
        position = text.find(marker)
        if position < 0:
            errors.append(f"README.md is missing section: {section}")
        positions.append(position)
    present = [position for position in positions if position >= 0]
    if present != sorted(present):
        errors.append("README.md sections are out of order")
    for section in README_ZH_SECTIONS:
        if f"## {section}" in text:
            errors.append(
                f"README.md uses a Chinese translation heading: {section}; "
                "put Chinese content in README.zh-CN.md"
            )
    if re.search(r"(?<!\\)\\\(|(?<!\\)\\\)", text):
        errors.append(
            r"README.md uses \( ... \); GitLab inline math must use $ ... $"
        )
    if re.search(r"(?<!\\)\\\[|(?<!\\)\\\]", text):
        errors.append(
            r"README.md uses \[ ... \]; GitLab display math must use $$ ... $$"
        )
    unresolved = (
        "{{TITLE}}",
        "{{PROBLEM_ID}}",
        "{{SLUG}}",
        "{{CREATED_DATE}}",
        "<!-- LKM_ENTRIES -->",
    )
    if any(marker in text for marker in unresolved):
        errors.append("README.md contains unresolved template placeholders")
    retired_contract_files = (
        "problem.yaml",
        "OPEN_QUESTIONS.md",
        "baseline/known-results.yaml",
        "verifier/review.md",
        ".github/workflows/verify.yml",
    )
    for retired in retired_contract_files:
        if retired in text:
            errors.append(
                f"README.md refers to retired repository contract file: {retired}"
            )
    return errors


def validate_problem_translation(path: Path) -> list[str]:
    """Validate an optional faithful Chinese translation of the canonical README."""

    if not path.is_file():
        return ["missing README.zh-CN.md"]
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    if not text.startswith("# "):
        errors.append("README.zh-CN.md must start with a problem title")
    if "(README.md)" not in text:
        errors.append("README.zh-CN.md must link to the canonical README.md")
    positions = []
    for section in README_ZH_SECTIONS:
        marker = f"## {section}"
        position = text.find(marker)
        if position < 0:
            errors.append(f"README.zh-CN.md is missing section: {section}")
        positions.append(position)
    present = [position for position in positions if position >= 0]
    if present != sorted(present):
        errors.append("README.zh-CN.md sections are out of order")
    unresolved = (
        "{{TITLE}}",
        "{{PROBLEM_ID}}",
        "{{SLUG}}",
        "{{CREATED_DATE}}",
        "<!-- LKM_ENTRIES_ZH -->",
    )
    if any(marker in text for marker in unresolved):
        errors.append("README.zh-CN.md contains unresolved template placeholders")
    if re.search(r"(?<!\\)\\\(|(?<!\\)\\\)", text):
        errors.append(
            r"README.zh-CN.md uses \( ... \); GitLab inline math must use $ ... $"
        )
    if re.search(r"(?<!\\)\\\[|(?<!\\)\\\]", text):
        errors.append(
            r"README.zh-CN.md uses \[ ... \]; GitLab display math must use $$ ... $$"
        )
    return errors


def create_problem_repo(
    template_dir: Path,
    out_dir: Path,
    *,
    schema_path: Path | None = None,
    problem_id: str,
    title: str,
    slug: str,
    source_node: str | None = None,
    include_zh_translation: bool = False,
    git_init: bool = False,
) -> Path:
    normalized_slug = slugify(slug)
    if out_dir.exists():
        raise FileExistsError(f"output path already exists: {out_dir}")
    out_dir.mkdir(parents=True)
    shutil.copy2(template_dir / "README.md", out_dir / "README.md")
    if include_zh_translation:
        shutil.copy2(
            template_dir / "README.zh-CN.md",
            out_dir / "README.zh-CN.md",
        )

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
    readme = out_dir / "README.md"
    text = readme.read_text(encoding="utf-8")
    lkm_entry = (
        f"- LKM open question `{source_node}` — explain its relationship to this problem."
        if source_node
        else "- Add the LKM open-question source and explain its relationship to this problem."
    )
    readme.write_text(
        text.replace("<!-- LKM_ENTRIES -->", lkm_entry),
        encoding="utf-8",
    )
    translation = out_dir / "README.zh-CN.md"
    if translation.is_file():
        translated_text = translation.read_text(encoding="utf-8")
        translated_lkm_entry = (
            f"- LKM open question `{source_node}` — 待补充它与本问题的关系。"
            if source_node
            else "- 待补充 LKM open-question 来源及其与本问题的关系。"
        )
        translation.write_text(
            translated_text.replace(
                "<!-- LKM_ENTRIES_ZH -->",
                translated_lkm_entry,
            ),
            encoding="utf-8",
        )

    if git_init:
        subprocess.run(["git", "init", "-b", "main"], cwd=out_dir, check=True)
    return out_dir
