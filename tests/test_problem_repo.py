from pathlib import Path

from open_research_discovery.common import (
    load_yaml,
    problem_manifest_paths,
    problem_repo_paths,
)
from open_research_discovery.problem_repo import (
    README_SECTIONS,
    create_problem_repo,
    normalize_github_math,
    render_problem_readme,
    validate_problem_readme,
    validate_problem_translation,
)


def test_github_math_normalization_preserves_latex_row_spacing() -> None:
    source = (
        r"\[A=\begin{pmatrix}a&b\\[6pt]c&d\end{pmatrix}\] "
        r"with \(\det A\neq0\)."
    )

    assert normalize_github_math(source) == (
        r"$$A=\begin{pmatrix}a&b\\[6pt]c&d\end{pmatrix}$$ "
        r"with $\det A\neq0$."
    )


def test_problem_repo_template_is_readme_first(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    out = tmp_path / "ORP-0001-example"

    create_problem_repo(
        root / "template",
        out,
        problem_id="ORP-0001",
        title="Example open problem",
        slug="Example Open Problem",
        source_node="gcn_example",
    )

    assert sorted(path.name for path in out.iterdir()) == ["README.md"]
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# Example open problem\n")
    assert "gcn_example" in readme
    for section in README_SECTIONS:
        assert f"## {section}" in readme
    assert not (out / "problem.yaml").exists()
    assert not (out / "schema").exists()


def test_problem_repo_can_include_chinese_translation_scaffold(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    out = tmp_path / "ORP-0002-bilingual"

    create_problem_repo(
        root / "template",
        out,
        problem_id="ORP-0002",
        title="Bilingual open problem",
        slug="Bilingual Open Problem",
        source_node="gcn_bilingual",
        include_zh_translation=True,
    )

    assert sorted(path.name for path in out.iterdir()) == [
        "README.md",
        "README.zh-CN.md",
    ]
    assert validate_problem_translation(out / "README.zh-CN.md") == []
    translation = (out / "README.zh-CN.md").read_text(encoding="utf-8")
    assert "[English canonical version](README.md)" in translation
    assert "如两者出现冲突，以 README.md 为准" in translation


def test_rendered_problem_readme_contains_narrative_contract(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    problem = load_yaml(root / "tests" / "fixtures" / "problem-draft.yaml")
    problem["title"] = "Finite counterexample"
    problem["question"]["canonical_statement"] = "Find a finite counterexample."
    problem["question"]["definitions"] = [
        (
            "This question arises in the spectral study of a finite physical "
            "system whose modes are encoded by an effective operator."
        ),
        "The effective operator is\n\n\\[\nA(x)=xI-H.\n\\]\n\n"
        "Here, \\(I\\) is the identity and \\(H\\) is the declared input matrix. "
        "Equivalently, \\[A=xI-H\\].",
    ]
    problem["importance"]["motivation"] = "It tests a central conjecture."
    problem["importance"]["consequences_of_progress"] = "A witness refutes it."
    problem["discovery_contract"]["expected_result"] = "A finite witness."
    problem["resolution_audit"].update(
        {
            "checked_at": "2026-07-27",
            "status": "still_open",
            "surviving_open_core": "Find a finite counterexample.",
            "conclusion": {
                "label": "confirmed_open",
                "confidence": "high",
                "rationale": "The audited literature leaves the target open.",
                "literature_treatment": "Later work improves searches only.",
            },
        }
    )
    problem["solution_review_contract"].update(
        {
            "verification_difficulty": 0,
            "estimated_review_time": "20 minutes",
            "acceptance_boundary": "Check every hypothesis and the violation.",
        }
    )
    problem["ci_contract"]["status"] = "pseudocode"
    readme = tmp_path / "README.md"
    readme.write_text(
        render_problem_readme(
            problem,
            {
                "solution_review_checklist": [
                    "Check every hypothesis.",
                    "Recompute the violation.",
                ],
                "ci_pseudocode": ["Parse the witness.", "Recompute the claim."],
            },
        ),
        encoding="utf-8",
    )

    assert validate_problem_readme(readme) == []
    text = readme.read_text(encoding="utf-8")
    assert "every load-bearing claim is discharged" in text
    assert "need not be automated or implemented in CI" in text
    assert "Parse the witness." in text
    assert "2026-07-27" in text
    assert "This question arises in the spectral study" in text
    assert "The effective operator is\n\n$$\nA(x)=xI-H." in text
    assert "Here, $I$ is the identity and $H$" in text
    assert "Equivalently, $$A=xI-H$$." in text
    assert "## Background" in text
    assert "## Problem Statement" in text
    assert "does not narrow or redefine the research question" in text
    assert r"\(" not in text
    assert r"\[" not in text


def test_problem_explanation_supports_nonmathematical_academic_prose() -> None:
    root = Path(__file__).resolve().parents[1]
    problem = load_yaml(root / "tests" / "fixtures" / "problem-draft.yaml")
    problem["question"]["canonical_statement"] = (
        "Determine whether the treatment changes the declared biological endpoint."
    )
    problem["question"]["definitions"] = [
        (
            "The model system is used to study a biological response that is "
            "not accessible through the existing observational assay."
        ),
        (
            "Earlier work established an association in untreated samples, "
            "but did not test the intervention or distinguish the two competing "
            "mechanistic interpretations. Here the specialist assay term refers "
            "to the measurement protocol described in this paragraph."
        ),
    ]

    text = render_problem_readme(problem)

    assert "The model system is used to study" in text
    assert "Earlier work established an association" in text
    assert "- The model system is used to study" not in text
    background = text.split("## Background", maxsplit=1)[1].split(
        "## Problem Statement", maxsplit=1
    )[0]
    assert background.index("The model system") < background.index(
        "Earlier work established"
    )
    problem_section = text.split("## Problem Statement", maxsplit=1)[1]
    assert problem_section.index(
        "Determine whether the treatment changes"
    ) >= 0


def test_canonical_readme_rejects_chinese_prose(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    out = tmp_path / "ORP-0003-language-check"
    create_problem_repo(
        root / "template",
        out,
        problem_id="ORP-0003",
        title="Language check",
        slug="language-check",
    )
    readme = out / "README.md"
    text = readme.read_text(encoding="utf-8")
    readme.write_text(
        text.replace("## Problem Statement", "这段文字不应出现在规范版本中。\n\n## Problem Statement"),
        encoding="utf-8",
    )

    assert any(
        "scientific sections must be English" in error
        for error in validate_problem_readme(readme)
    )


def test_repository_and_manifest_discovery_are_separate(tmp_path: Path) -> None:
    for repo_name in ("ORP-0002-current", "OMP-0001-legacy", "unrelated"):
        repo = tmp_path / repo_name
        repo.mkdir()
        (repo / "README.md").write_text(f"# {repo_name}\n", encoding="utf-8")
        (repo / "problem.yaml").write_text("id: example\n", encoding="utf-8")

    assert [
        path.name for path in problem_repo_paths(tmp_path)
    ] == ["OMP-0001-legacy", "ORP-0002-current"]
    assert [
        path.parent.name for path in problem_manifest_paths(tmp_path)
    ] == ["OMP-0001-legacy", "ORP-0002-current"]


def test_readme_without_assessment_omits_pointer_ci_steps() -> None:
    root = Path(__file__).resolve().parents[1]
    problem = load_yaml(root / "tests" / "fixtures" / "problem-draft.yaml")
    problem["ci_contract"]["status"] = "pseudocode"
    problem["ci_contract"]["pseudocode"] = "README.md#possible-ci"

    text = render_problem_readme(problem)

    assert "README.md#possible-ci" not in text
    assert "Scientifically meaningful automated checks may include:" not in text


def test_render_ignores_retired_contract_keys() -> None:
    root = Path(__file__).resolve().parents[1]
    problem = load_yaml(root / "tests" / "fixtures" / "problem-draft.yaml")
    problem["discovery_contract"]["candidate_format"] = "Retired format."
    problem["discovery_contract"]["partial_progress_metrics"] = [
        "Retired metric."
    ]
    problem["ci_contract"]["pseudocode_steps"] = ["Retired step."]
    del problem["solution_review_contract"]
    problem["reviewer_contract"] = {
        "verification_difficulty": 0,
        "rationale": "Retired rationale.",
        "checklist_items": ["Retired check."],
        "estimated_review_time": "1 minute",
        "acceptance_boundary": "Retired boundary.",
    }

    text = render_problem_readme(problem)

    assert "Retired" not in text


def test_readme_with_assessment_keeps_real_ci_steps() -> None:
    root = Path(__file__).resolve().parents[1]
    problem = load_yaml(root / "tests" / "fixtures" / "problem-draft.yaml")
    problem["ci_contract"]["status"] = "pseudocode"

    text = render_problem_readme(
        problem,
        {"ci_pseudocode": ["Parse the witness.", "Recompute the claim."]},
    )

    assert "Scientifically meaningful automated checks may include:" in text
    assert "- Parse the witness." in text
    assert "- Recompute the claim." in text


def test_validate_problem_readme_rejects_non_github_math_delimiters(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    out = tmp_path / "ORP-0003-math"
    create_problem_repo(
        root / "template",
        out,
        problem_id="ORP-0003",
        title="Math delimiters",
        slug="Math Delimiters",
        source_node="gcn_math",
        include_zh_translation=True,
    )
    readme = out / "README.md"
    translation = out / "README.zh-CN.md"
    canonical = readme.read_text(encoding="utf-8")
    translated = translation.read_text(encoding="utf-8")
    assert validate_problem_readme(readme) == []
    assert validate_problem_translation(translation) == []

    # \( ... \) and \[ ... \] are hard errors; GitHub renders $ ... $ and
    # $$ ... $$ instead.
    readme.write_text(
        canonical + "\nInline math \\( x+y \\) is not GitHub-flavored.\n",
        encoding="utf-8",
    )
    assert any(
        "inline math must use $ ... $" in error
        for error in validate_problem_readme(readme)
    )
    readme.write_text(canonical + "\n\\[\nx+y\n\\]\n", encoding="utf-8")
    assert any(
        "display math must use $$ ... $$" in error
        for error in validate_problem_readme(readme)
    )
    # $ ... $ and $$ ... $$ stay legal.
    readme.write_text(
        canonical + "\nInline $x+y$ and display $$x+y$$ are fine.\n",
        encoding="utf-8",
    )
    assert validate_problem_readme(readme) == []

    # README.zh-CN.md is held to the same delimiter contract.
    translation.write_text(
        translated + "\n行内公式 \\( x+y \\) 不合规。\n", encoding="utf-8"
    )
    assert any(
        "inline math must use $ ... $" in error
        for error in validate_problem_translation(translation)
    )
    translation.write_text(translated + "\n\\[\nx+y\n\\]\n", encoding="utf-8")
    assert any(
        "display math must use $$ ... $$" in error
        for error in validate_problem_translation(translation)
    )
    translation.write_text(
        translated + "\n行内 $x+y$ 与展示 $$x+y$$ 均合规。\n", encoding="utf-8"
    )
    assert validate_problem_translation(translation) == []
