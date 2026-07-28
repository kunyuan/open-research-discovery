from pathlib import Path

from open_research_discovery.common import (
    load_yaml,
    problem_manifest_paths,
    problem_repo_paths,
)
from open_research_discovery.problem_repo import (
    README_SECTIONS,
    create_problem_repo,
    render_problem_readme,
    validate_problem_readme,
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


def test_rendered_problem_readme_contains_narrative_contract(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    problem = load_yaml(root / "tests" / "fixtures" / "problem-draft.yaml")
    problem["title"] = "Finite counterexample"
    problem["question"]["canonical_statement"] = "Find a finite counterexample."
    problem["question"]["definitions"] = [
        "The load-bearing operator is\n\n\\[\nA(x)=xI-H.\n\\]\n\n"
        "Here, \\(I\\) is the identity and \\(H\\) is the declared input matrix."
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
            "scope": "result-only",
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
    assert "不需要复盘解题者的搜索过程或推理过程" in text
    assert "Parse the witness." in text
    assert "2026-07-27" in text
    assert "- The load-bearing operator is\n\n  \\[\n  A(x)=xI-H." in text


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
