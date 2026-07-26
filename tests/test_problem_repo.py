import subprocess
import sys
from pathlib import Path

from open_research_discovery.common import load_yaml, problem_manifest_paths
from open_research_discovery.problem_repo import create_problem_repo


def test_problem_repo_is_self_contained(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    out = tmp_path / "ORP-0001-example"

    create_problem_repo(
        root / "template",
        out,
        schema_path=root / "schemas" / "problem.schema.json",
        problem_id="ORP-0001",
        title="Example open problem",
        slug="Example Open Problem",
        source_node="gcn_example",
    )

    manifest = load_yaml(out / "problem.yaml")
    assert manifest["id"] == "ORP-0001"
    assert manifest["title"] == "Example open problem"
    assert manifest["source_open_questions"][0]["node_id"] == "gcn_example"
    assert manifest["discovery_contract"]["expected_result"] == ""
    assert manifest["reviewer_contract"]["scope"] == "unclassified"
    assert manifest["ci_contract"]["status"] == "blocked"
    assert manifest["research_triage"]["importance_level"] == "unassessed"
    assert manifest["reviewer_contract"]["scope"] == "unclassified"
    assert manifest["ci_contract"]["status"] == "blocked"
    assert (out / "schema" / "problem.schema.json").exists()
    assert (out / "verifier" / "review.md").exists()
    assert (out / "verifier" / "ci.md").exists()
    assert (out / "tools" / "ci_verify.py").exists()
    assert "{{PROBLEM_ID}}" not in (out / "README.md").read_text()

    completed = subprocess.run(
        [sys.executable, "tools/ci_verify.py"],
        cwd=out,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert '"outcome": "structural-only"' in completed.stdout

    (out / "submission" / "candidate.json").write_text("{}\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "tools/ci_verify.py"],
        cwd=out,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert '"outcome": "manual-review-required"' in completed.stdout


def test_manifest_discovery_supports_current_and_legacy_namespaces(
    tmp_path: Path,
) -> None:
    for repo_name in ("ORP-0002-current", "OMP-0001-legacy", "unrelated"):
        repo = tmp_path / repo_name
        repo.mkdir()
        (repo / "problem.yaml").write_text("id: example\n", encoding="utf-8")

    assert [
        path.parent.name for path in problem_manifest_paths(tmp_path)
    ] == ["OMP-0001-legacy", "ORP-0002-current"]
