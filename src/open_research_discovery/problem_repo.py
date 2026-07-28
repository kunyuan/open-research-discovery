from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .common import iter_text_files, slugify, today


README_SECTIONS = (
    "问题是什么",
    "为什么重要",
    "期望的答案类型",
    "难度判断",
    "Review Scope",
    "可以考虑的 CI",
    "当前研究状态",
    "LKM 与引用文献",
)


def _text(value: object, fallback: str = "尚待补充。") -> str:
    rendered = str(value or "").strip()
    return rendered or fallback


def _public_text(value: object, fallback: str = "尚待补充。") -> str:
    rendered = _text(value, "")
    replacements = {
        (
            "This repository tracks the primary canonical target. "
            "Related source-paper questions are preserved in OPEN_QUESTIONS.md."
        ): (
            "当前仓库只讨论上述单一目标；原始 LKM 记录中的其他相邻问题"
            "不在本仓库范围内。"
        ),
        "submission/candidate.json": "`candidate.json`",
        "submission/solution.md": "`solution.md`",
        "under submission/": "included in the final submission",
    }
    for old, new in replacements.items():
        rendered = rendered.replace(old, new)
    return rendered or fallback


def _bullet_lines(values: list[object], fallback: str = "尚待补充。") -> list[str]:
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


def _review_intro(scope: str) -> str:
    return {
        "result-only": (
            "Reviewer 应主要依据提交的最终结果判断它是否回答了问题，"
            "通常不需要复盘解题者的搜索过程或推理过程。"
        ),
        "result-and-derivation": (
            "Reviewer 除了检查最终结论，还需要审查支撑结论的核心推导、"
            "证明或科学论证。"
        ),
        "expert-intensive": (
            "该问题需要相关领域专家审查最终结果及其科学解释，"
            "不能只依靠一个局部自动检查作出结论。"
        ),
    }.get(scope, "Reviewer 应根据最终提交物判断需要审查的内容。")


def _render_sources(
    problem: dict[str, Any],
    annotated_references: str = "",
) -> list[str]:
    lines = ["### LKM", ""]
    sources = problem.get("source_open_questions") or []
    if not sources:
        lines.append("- 尚未登记 LKM open-question 来源。")
    for source in sources:
        paper_id = _text(source.get("paper_id"), "unknown-paper")
        node_id = _text(source.get("node_id"), "unknown-open-question")
        title = _text(source.get("paper_title"), "未登记论文标题")
        doi = _text(source.get("paper_doi"), "")
        identifier = f"LKM paper `{paper_id}` / open question `{node_id}`"
        if doi:
            identifier += f" / DOI `{doi}`"
        lines.append(
            f"- {identifier} — {title}。这是提出或保留本题的原始 "
            "`open_questions` 节点；问题不是从普通 question 或正文措辞中推断的。"
        )

    lines.extend(["", "### 引用文献", ""])
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
                    (title, url, "包含本仓库所依据的原始开放问题。")
                )
    if not citations:
        lines.append("1. 尚待补充经核查的原始文献。")
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
    return cleaned or ["1. 尚待补充经核查的原始文献。"]


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
    review = (
        problem.get("solution_review_contract")
        or problem.get("reviewer_contract")
        or {}
    )
    ci = problem.get("ci_contract") or {}
    compute = problem.get("compute") or {}
    progress = audit.get("progress_assessment") or {}

    assessment = assessment or {}
    expected_result = (
        assessment.get("expected_result")
        or discovery.get("expected_result")
        or discovery.get("candidate_format")
        or "提交一个能够直接回答上述问题的完整研究结果。"
    )
    review_checks = (
        assessment.get("solution_review_checklist")
        or review.get("checklist_items")
        or []
    )
    if not review_checks and review.get("acceptance_boundary"):
        review_checks = [review["acceptance_boundary"]]
    ci_steps = (
        assessment.get("ci_pseudocode")
        or ci.get("pseudocode_steps")
        or ci.get("pseudocode")
        or []
    )
    if isinstance(ci_steps, str):
        ci_steps = [ci_steps]
    if ci_steps and all(
        str(step).endswith((".md", ".txt")) for step in ci_steps
    ):
        ci_steps = [
            discovery.get("success_condition")
            or review.get("acceptance_boundary")
            or "根据最终提交物直接重算问题中的关键判据。"
        ]

    definitions = question.get("definitions") or []
    problem_lines = [
        _public_text(question.get("canonical_statement")),
        "",
    ]
    if definitions:
        problem_lines.extend(["理解这个问题需要以下约定：", ""])
        problem_lines.extend(_bullet_lines(definitions))
        problem_lines.append("")
    if question.get("scope"):
        problem_lines.extend(
            [
                "当前仓库所讨论的范围是：",
                "",
                _public_text(question.get("scope")),
                "",
            ]
        )

    difficulty_parts = [
        (
            "这个问题的求解难度不参与筛选排序；这里的判断只用于帮助"
            "研究 Agent 估计所需知识、工具和计算资源。"
        ),
        (
            "从截至核查日期的文献看，它仍属于前沿开放问题，"
            "完整解决路径具有较高不确定性。"
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
        f"- 核查日期：`{_text(audit.get('checked_at') or audit.get('checked_through'))}`",
        f"- 当前判断：`{_text(conclusion.get('label') or audit.get('status'))}`",
        f"- 置信度：`{_text(conclusion.get('confidence'), '未标注')}`",
        f"- 仍然存活的核心问题：{_text(audit.get('surviving_open_core'))}",
        f"- 研究判断：{_text(conclusion.get('rationale'))}",
    ]
    if progress.get("major_progress_found"):
        status_lines.append(
            f"- 重大进展及其影响：{_text(progress.get('effect'))}"
        )
    if conclusion.get("literature_treatment"):
        status_lines.append(
            f"- 后续文献如何处理该问题：{_text(conclusion.get('literature_treatment'))}"
        )

    lines = [
        f"# {_text(problem.get('title'), '开放研究问题')}",
        "",
        _public_text(question.get("canonical_statement")),
        "",
        "## 问题是什么",
        "",
        *problem_lines,
        "## 为什么重要",
        "",
        _public_text(importance.get("motivation")),
        "",
        _public_text(importance.get("consequences_of_progress")),
        "",
        "## 期望的答案类型",
        "",
        _public_text(expected_result),
        "",
    ]
    if discovery.get("partial_progress_metrics"):
        lines.extend(
            [
                "以下部分结果也可能构成实质性推进：",
                "",
                *_bullet_lines(discovery["partial_progress_metrics"]),
                "",
            ]
        )
    lines.extend(
        [
            "## 难度判断",
            "",
            *[part for part in difficulty_parts if part],
            "",
        ]
    )
    if resource_lines:
        lines.extend(["可能需要的资源包括：", "", *_bullet_lines(resource_lines), ""])
    lines.extend(
        [
            "## Review Scope",
            "",
            _review_intro(_text(review.get("scope"), "")),
            "",
            _public_text(review.get("rationale"), ""),
            "",
            f"预计审查时间：{_text(review.get('estimated_review_time'))}",
            "",
            "Reviewer 至少需要确认：",
            "",
            *_bullet_lines(review_checks),
            "",
            "还应检查提交是否真正回答原问题、是否存在等价或更强的已有结果，"
            "以及部分结果是否足以构成实质性推进。",
            "",
            "## 可以考虑的 CI",
            "",
        ]
    )
    if ci.get("status") in {"blocked", "solution-reviewer-only", "reviewer-only"}:
        lines.extend(
            [
                "目前没有足以代表科学结论的自动判据，主要依靠 Reviewer 判断。",
                "",
            ]
        )
    else:
        ci_intro = (
            "仓库已提供 `.gitlab-ci.yml` 和独立 verifier；提交候选结果后可直接运行。"
            if ci.get("status") == "implemented"
            else "目前已经明确可自动验证的科学判据，但尚未实现通用 CI。"
        )
        lines.extend(
            [
                ci_intro,
                "",
                f"建议运行环境：{_text(ci.get('runner'))}",
                "",
                f"预计运行时间：{_text(ci.get('estimated_runtime'))}",
                "",
                "有科学意义的自动检查可以包括：",
                "",
                *_bullet_lines(ci_steps),
                "",
            ]
        )
    lines.extend(
        [
            "自动检查只能证明其实际编码的判据；它不能单独证明新颖性、"
            "科学解释或超出当前问题范围的主张。",
            "",
            "## 当前研究状态",
            "",
            *status_lines,
            "",
            "后续状态变化应直接通过 commit 和 Merge Request 更新本节，"
            "让问题认识的演化保留在 Git 历史中。",
            "",
            "## LKM 与引用文献",
            "",
            *_render_sources(problem, annotated_references),
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def validate_problem_readme(path: Path) -> list[str]:
    if not path.is_file():
        return ["missing README.md"]
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    if not text.startswith("# "):
        errors.append("README.md must start with a problem title")
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


def create_problem_repo(
    template_dir: Path,
    out_dir: Path,
    *,
    schema_path: Path | None = None,
    problem_id: str,
    title: str,
    slug: str,
    source_node: str | None = None,
    git_init: bool = False,
) -> Path:
    normalized_slug = slugify(slug)
    if out_dir.exists():
        raise FileExistsError(f"output path already exists: {out_dir}")
    out_dir.mkdir(parents=True)
    shutil.copy2(template_dir / "README.md", out_dir / "README.md")

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
        f"- LKM open question `{source_node}` — 待补充它与本问题的关系。"
        if source_node
        else "- 尚待补充 LKM open-question 来源及其与本问题的关系。"
    )
    readme.write_text(
        text.replace("<!-- LKM_ENTRIES -->", lkm_entry),
        encoding="utf-8",
    )

    if git_init:
        subprocess.run(["git", "init", "-b", "main"], cwd=out_dir, check=True)
    return out_dir
