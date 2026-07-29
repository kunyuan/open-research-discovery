from pathlib import Path

from open_research_discovery.common import (
    load_yaml,
    problem_manifest_paths,
    problem_repo_paths,
)
from open_research_discovery.problem_repo import (
    README_SECTIONS,
    create_problem_repo,
    normalize_gitlab_math,
    render_problem_readme,
    validate_problem_readme,
    validate_problem_translation,
)


def test_gitlab_math_normalization_preserves_latex_row_spacing() -> None:
    source = (
        r"\[A=\begin{pmatrix}a&b\\[6pt]c&d\end{pmatrix}\] "
        r"with \(\det A\neq0\)."
    )

    assert normalize_gitlab_math(source) == (
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
    assert "review scope is basically limited to the final result" in text
    assert "need not be mechanical or implemented in CI" in text
    assert "Parse the witness." in text
    assert "2026-07-27" in text
    assert "This question arises in the spectral study" in text
    assert "The effective operator is\n\n$$\nA(x)=xI-H." in text
    assert "Here, $I$ is the identity and $H$" in text
    assert "Equivalently, $$A=xI-H$$." in text
    assert "Against this background, this repository focuses" in text
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
    problem_section = text.split("## The Research Problem", maxsplit=1)[1]
    assert problem_section.index("The model system") < problem_section.index(
        "Determine whether the treatment changes"
    )


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
    readme.write_text(
        readme.read_text(encoding="utf-8") + "\n这段文字不应出现在规范版本中。\n",
        encoding="utf-8",
    )

    assert any(
        "must be entirely English" in error
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
