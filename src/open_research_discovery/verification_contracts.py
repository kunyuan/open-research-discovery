from __future__ import annotations

from pathlib import Path
from typing import Any

from .review_policy import RouteContractError, review_scope_for


REVIEW_SCOPES = {
    "result-only",
    "result-and-derivation",
    "expert-intensive",
    "unclassified",
}

REVIEW_TIME = {
    ("machine-checkable", "easy"): "10-30 reviewer-minutes",
    ("machine-checkable", "moderate"): "30-90 reviewer-minutes",
    ("machine-checkable", "hard"): "1-3 reviewer-hours",
    ("llm-reviewable", "easy"): "20-45 reviewer-agent minutes",
    ("llm-reviewable", "moderate"): "45-120 reviewer-agent minutes",
    ("llm-reviewable", "hard"): "2-6 reviewer-hours",
    ("hybrid", "easy"): "30-90 reviewer-minutes",
    ("hybrid", "moderate"): "1-3 reviewer-hours",
    ("hybrid", "hard"): "3-8 reviewer-hours",
    ("expert-review", "easy"): "2-4 expert-hours",
    ("expert-review", "moderate"): "4-12 expert-hours",
    ("expert-review", "hard"): "1-3 expert-days",
    ("unclassified", "hard"): "2-8 hours to define a protocol; solution review unbounded",
    ("unclassified", "unclassified"): "2-8 hours to define a protocol; solution review unbounded",
}

CI_RUNTIME = {
    ("machine-checkable", "easy"): "2-30 minutes for a practical candidate; hard timeout 120 minutes",
    ("machine-checkable", "moderate"): "10-60 minutes; hard timeout 120 minutes",
    ("machine-checkable", "hard"): "30-120 minutes on a self-hosted runner",
    ("llm-reviewable", "easy"): "under 2 minutes structural CI; 20-45 minutes reviewer-agent time",
    ("llm-reviewable", "moderate"): "under 2 minutes structural CI; 45-120 minutes reviewer-agent time",
    ("llm-reviewable", "hard"): "under 2 minutes structural CI; 2-6 hours review outside CI",
    ("hybrid", "easy"): "2-30 minutes machine stage plus 30-90 minutes review",
    ("hybrid", "moderate"): "10-60 minutes machine stage plus 1-3 hours review",
    ("hybrid", "hard"): "30-120 minutes machine stage plus 3-8 hours review",
    ("expert-review", "easy"): "under 2 minutes structural CI; 2-4 expert-hours outside CI",
    ("expert-review", "moderate"): "under 2 minutes structural CI; 4-12 expert-hours outside CI",
    ("expert-review", "hard"): "under 2 minutes structural CI; 1-3 expert-days outside CI",
    ("unclassified", "hard"): "under 2 minutes structural CI; acceptance runtime unknown",
    ("unclassified", "unclassified"): "under 2 minutes structural CI; acceptance runtime unknown",
}

ARTIFACT_CHECKS = {
    "counterexample": [
        "Parse the finite object and reject malformed, duplicate, or out-of-domain data.",
        "Check every hypothesis of the conjectured statement on the submitted object.",
        "Independently recompute the claimed violating quantity or forbidden property.",
        "Confirm that the violation is strict and is not caused by a convention mismatch.",
    ],
    "construction": [
        "Parse the complete constructed object or deterministic generator and its parameters.",
        "Check every local incidence, algebraic, geometric, or combinatorial constraint.",
        "Recompute the target parameters independently from the submitted representation.",
        "For a claimed infinite family, separate checked finite instances from the uniform proof.",
    ],
    "certificate": [
        "Parse the certificate using exact arithmetic or the declared trusted proof kernel.",
        "Recompute the instance data rather than trusting values copied into the certificate.",
        "Replay every certificate equation, inequality, dual constraint, or proof step.",
        "Check that the certificate proves the full claimed optimum or obstruction, not one side only.",
    ],
    "formal-proof": [
        "Pin the declared proof assistant, package lock, trusted kernel, and theorem statement.",
        "Confirm that the source question explicitly requests this machine-checkable proof artifact.",
        "Build the proof without network access or undeclared axioms and inspect the trusted-kernel result.",
        "Check that the compiled theorem has exactly the frozen hypotheses and conclusion.",
    ],
    "algorithm": [
        "Build the submitted implementation in a pinned, network-free environment.",
        "Run reference cases, adversarial edge cases, and differential tests against a slow oracle.",
        "Check the stated correctness invariant and termination argument.",
        "Replay the sealed benchmark and verify the claimed complexity/scale boundary.",
    ],
    "theorem-boundary": [
        "Normalize the theorem statement, hypotheses, quantifiers, and exceptional parameter cases.",
        "Build a dependency table from every claimed lemma to the exact conclusion it supports.",
        "Check each cited or machine-generated lemma against its stated assumptions.",
        "Search specifically for gaps at limiting, degenerate, and equality cases.",
    ],
    "dataset": [
        "Validate the declared schema, provenance, license, checksums, and immutable raw-data boundary.",
        "Recompute every reported summary and quality-control metric from the submitted data.",
        "Check for duplicates, leakage, missingness, unit mismatches, and excluded records.",
        "Confirm that the dataset supports only the population and claim stated in the contract.",
    ],
    "experimental-result": [
        "Reconstruct the protocol, materials, instruments, controls, exclusions, and analysis plan.",
        "Validate raw-data provenance and recompute the reported statistics with declared uncertainty.",
        "Check calibration, negative and positive controls, multiplicity, and sensitivity analyses.",
        "Accept only the measured claim; do not infer untested causality or generality.",
    ],
    "simulation-result": [
        "Build and run the pinned simulation with the declared initial and boundary conditions.",
        "Recompute observables and verify convergence, resolution, seed, and finite-size checks.",
        "Compare against analytic limits, conservation laws, or an independent implementation.",
        "Accept only the simulated regime and uncertainty envelope encoded by the contract.",
    ],
    "model": [
        "Reconstruct the model, data split, preprocessing, parameters, and training or fitting procedure.",
        "Evaluate on held-out or sealed data using the preregistered metrics and baselines.",
        "Check calibration, uncertainty, ablations, leakage, and robustness to declared perturbations.",
        "Reject claims that exceed the validated population, regime, or task.",
    ],
    "protocol": [
        "Check that every material, parameter, step, control, and stopping rule is explicit.",
        "Execute or independently reproduce the protocol in the declared environment.",
        "Apply the preregistered success and failure thresholds without post-hoc weakening.",
        "Record deviations and accept only the reproducibility claim supported by the run.",
    ],
    "other": [
        "Normalize the exact claim and specify a bounded substantive acceptance predicate.",
        "Reject the submission if the claimed artifact cannot be independently reconstructed.",
        "Check every stated assumption and conclusion using independent evidence.",
    ],
}


def verifier_is_implemented(repo: Path) -> bool:
    verifier = repo / "verifier" / "check.py"
    return verifier.is_file() and "verifier_not_implemented" not in verifier.read_text(
        encoding="utf-8"
    )


def _review_scope(problem: dict[str, Any], _mode: str) -> str:
    obligations = list(
        problem.get("discovery_contract", {}).get("acceptance_obligations")
        or []
    )
    obligated_scope = review_scope_for(obligations)
    declared = str(
        (problem.get("reviewer_contract") or {}).get("scope") or ""
    )
    if declared in REVIEW_SCOPES and declared != "unclassified":
        if declared != obligated_scope:
            raise RouteContractError(
                f"declared reviewer scope {declared!r} conflicts with "
                f"acceptance obligations; expected {obligated_scope!r}"
            )
        return declared
    return obligated_scope


def contract_for(problem: dict[str, Any], repo: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = problem["discovery_contract"]["verification_profile"]
    mode = str(profile["mode"])
    ease = str(profile["ease"])
    scope = _review_scope(problem, mode)
    review_time = REVIEW_TIME.get(
        (mode, ease), "review time requires a problem-specific estimate"
    )
    implemented = verifier_is_implemented(repo)
    if mode == "machine-checkable":
        ci_status = "implemented" if implemented else "pseudocode"
    elif mode == "hybrid":
        ci_status = "partial" if implemented else "pseudocode"
    elif mode in {"llm-reviewable", "expert-review"}:
        ci_status = "reviewer-only"
    else:
        ci_status = "blocked"
    timeout = {
        "implemented": 120,
        "partial": 120,
        "pseudocode": 10,
        "reviewer-only": 10,
        "blocked": 5,
    }[ci_status]
    runner = (
        "ubuntu-latest for contract checks; use a pinned self-hosted runner when the candidate exceeds the stated timeout"
        if mode in {"machine-checkable", "hybrid"}
        else "ubuntu-latest for structural checks; substantive review runs outside GitHub Actions"
    )
    success = str(problem["discovery_contract"].get("success_condition") or "")
    reviewer = {
        "scope": scope,
        "difficulty": ease,
        "checklist": "verifier/review.md",
        "estimated_review_time": review_time,
        "acceptance_boundary": success,
    }
    ci = {
        "status": ci_status,
        "workflow": ".github/workflows/verify.yml",
        "driver": "tools/ci_verify.py",
        "pseudocode": "verifier/ci.md",
        "runner": runner,
        "estimated_runtime": CI_RUNTIME.get(
            (mode, ease), "runtime requires a problem-specific estimate"
        ),
        "timeout_minutes": timeout,
    }
    return reviewer, ci


def render_review(problem: dict[str, Any]) -> str:
    question = problem["question"]
    contract = problem["discovery_contract"]
    profile = contract["verification_profile"]
    reviewer = problem["reviewer_contract"]
    audit = problem["resolution_audit"]
    checks = ARTIFACT_CHECKS.get(
        str(contract.get("artifact_type") or "other"), ARTIFACT_CHECKS["other"]
    )
    lines = [
        "# Reviewer-agent acceptance protocol",
        "",
        "This file is normative for local claim validity. Novelty and current",
        "open status remain separate literature-audit decisions.",
        "",
        "## Review boundary",
        "",
        f"- Problem: `{problem['id']}` — {problem['title']}",
        f"- Exact target: {question['canonical_statement']}",
        f"- Candidate artifact: {contract['candidate_format']}",
        f"- Acceptance condition: {contract['success_condition']}",
        f"- Verification mode: `{profile['mode']}`",
        f"- Scope class: `{reviewer['scope']}`",
        f"- Difficulty: `{reviewer['difficulty']}`",
        f"- Estimated review time: {reviewer['estimated_review_time']}",
        f"- Current resolution status: `{audit['status']}` (checked {audit['checked_at']})",
        "",
        "## Load-bearing acceptance obligations",
        "",
    ]
    obligations = list(contract.get("acceptance_obligations") or [])
    if obligations:
        lines.extend(
            (
                f"- `{item['kind']}` — {item['description']} "
                f"(source: `{item['source_key']}`)"
            )
            for item in obligations
        )
    else:
        lines.append("- Not yet classified; substantive acceptance is blocked.")
    lines.extend(
        [
            "",
            "If the resolution status is `uncertain`, `resolved`, or `refuted`, the",
            "reviewer may report local validity but must not report a new solution without",
            "a refreshed current-literature audit.",
            "",
            "## Allowed evidence",
            "",
            "Use only the submitted artifact, `problem.yaml`, `baseline/`, declared",
            "references/evidence, and independently replayed checker output. Search logs,",
            "solver success flags, and the producing agent's confidence are not evidence.",
            "",
            "## Ordered checks",
            "",
            "1. Freeze the claim: copy the exact parameters, quantifiers, conventions,",
            "   and claimed conclusion into the review record.",
            "2. Confirm that the submission matches the declared candidate format and",
            "   contains every datum needed for independent reconstruction.",
        ]
    )
    for index, check in enumerate(checks, start=3):
        lines.append(f"{index}. {check}")
    next_index = len(checks) + 3
    if reviewer["scope"] == "result-only":
        lines.extend(
            [
                f"{next_index}. Run `make check` and the independent verifier. Require a",
                "   zero exit code and inspect its structured output.",
                f"{next_index + 1}. Perturb at least one load-bearing field and confirm",
                "   that the verifier rejects the corrupted candidate.",
                f"{next_index + 2}. Accept only the finite result/certificate actually",
                "   checked; do not infer an unverified family or theorem.",
            ]
        )
    elif reviewer["scope"] == "result-and-derivation":
        lines.extend(
            [
                f"{next_index}. Replay every deterministic subcheck and record the",
                "   checker version, command, runtime, and exact output hash.",
                f"{next_index + 1}. Build a claim-to-lemma table for the remaining",
                "   derivation; verify each lemma against definitions in the repository.",
                f"{next_index + 2}. Reject if the machine result is valid but the",
                "   derivation does not establish the full quantified claim.",
            ]
        )
    elif reviewer["scope"] == "expert-intensive":
        lines.extend(
            [
                f"{next_index}. Require a complete claim-to-evidence dependency graph and",
                "   a second independent expert pass over every load-bearing inference.",
                f"{next_index + 1}. Machine checks may validate examples or arithmetic",
                "   only; they cannot establish conclusions outside the encoded contract.",
                f"{next_index + 2}. Escalate disagreements, implicit regularity",
                "   assumptions, protocol deviations, or unsupported extrapolations.",
            ]
        )
    else:
        lines.extend(
            [
                f"{next_index}. Do not accept a solution under the current contract.",
                "   First replace `unclassified` with a finite checklist or an explicit",
                "   expert-review boundary and regenerate this file.",
            ]
        )
    lines.extend(
        [
            "",
            "## Immediate rejection or escalation",
            "",
            "- The artifact is incomplete, depends on inaccessible state, or cannot be",
            "  reconstructed without the producing solver.",
            "- Floating-point tolerance is used where exactness is load-bearing and no",
            "  certified interval/error argument is supplied.",
            "- Only examples are checked for a universal or asymptotic claim.",
            "- A cited lemma is applied outside its hypotheses or with changed conventions.",
            "- The local result passes but novelty/current openness has not been refreshed.",
            "",
            "## Required verdict",
            "",
            "Return one JSON object:",
            "",
            "```json",
            "{",
            f'  "problem_id": "{problem["id"]}",',
            '  "verdict": "accept-local | reject | needs-expert | needs-status-refresh | protocol-incomplete",',
            f'  "review_scope": "{reviewer["scope"]}",',
            '  "checks_run": ["..."],',
            '  "failed_checks": ["..."],',
            '  "machine_result": "pass | fail | not-applicable",',
            '  "derivation_result": "pass | fail | not-applicable",',
            '  "novelty_checked": false,',
            '  "reviewer_notes": "..."',
            "}",
            "```",
            "",
            "`accept-local` means only that the submitted artifact establishes the local",
            "claim under this contract. It is not a publication or novelty verdict.",
            "",
        ]
    )
    return "\n".join(lines)


def render_ci(problem: dict[str, Any]) -> str:
    contract = problem["discovery_contract"]
    profile = contract["verification_profile"]
    ci = problem["ci_contract"]
    artifact = str(contract.get("artifact_type") or "other")
    artifact_code_by_type = {
        "counterexample": [
            "candidate = parse_submission()",
            "assert check_all_hypotheses(candidate)",
            "assert independently_recompute_violation(candidate)",
        ],
        "construction": [
            "candidate = parse_complete_object_or_generator()",
            "assert check_all_target_constraints(candidate)",
            "assert recompute_parameters(candidate) == claimed_parameters",
            "if candidate.claims_family: require_review_of_uniform_derivation()",
        ],
        "certificate": [
            "instance, certificate = parse_submission()",
            "assert recompute_instance(instance)",
            "assert replay_certificate_exactly(instance, certificate)",
            "assert certificate_proves_full_claim()",
        ],
        "algorithm": [
            "implementation = build_in_pinned_environment()",
            "assert reference_and_adversarial_tests(implementation)",
            "assert differential_fuzzing_against_oracle(implementation)",
            "run_sealed_benchmark_and_record_runtime()",
            "require_review_of_correctness_and_complexity_proof()",
        ],
        "theorem-boundary": [
            "proof = parse_claim_lemma_dependency_graph()",
            "assert all_hypotheses_and_quantifiers_match(problem_statement)",
            "replay_formal_or_computational_lemmas()",
            "require_two_pass_expert_review(proof)",
        ],
        "dataset": [
            "dataset = load_versioned_dataset_and_provenance()",
            "assert schema_checksums_licenses_and_units_match(dataset)",
            "assert recompute_quality_metrics(dataset)",
            "assert no_forbidden_duplicates_or_split_leakage(dataset)",
        ],
        "experimental-result": [
            "raw_data, protocol = load_experiment_submission()",
            "assert provenance_calibration_controls_and_exclusions_match(protocol)",
            "assert recompute_statistics_with_declared_uncertainty(raw_data)",
            "assert preregistered_acceptance_thresholds_hold()",
        ],
        "simulation-result": [
            "simulation = build_pinned_simulation()",
            "assert declared_initial_boundary_and_seed_conditions(simulation)",
            "assert convergence_resolution_and_finite_size_checks(simulation)",
            "assert independently_recompute_observables(simulation)",
        ],
        "model": [
            "model, data = reconstruct_model_and_data_pipeline()",
            "assert held_out_or_sealed_evaluation(model, data)",
            "assert baselines_calibration_uncertainty_and_ablations_pass()",
            "assert claim_stays_within_validated_population_and_regime()",
        ],
        "protocol": [
            "protocol = parse_complete_reproducibility_protocol()",
            "assert all_materials_parameters_controls_and_stopping_rules_present(protocol)",
            "result = independently_execute_protocol(protocol)",
            "assert preregistered_success_thresholds_hold(result)",
        ],
        "other": [
            "artifact = parse_submission()",
            "assert reconstruct_claim_independently(artifact)",
            "require_explicit_problem_specific_acceptance_predicate()",
        ],
    }
    artifact_code = artifact_code_by_type.get(
        artifact, artifact_code_by_type["other"]
    )
    lines = [
        "# CI design and executable boundary",
        "",
        f"- Problem: `{problem['id']}` — {problem['title']}",
        f"- Automation status: `{ci['status']}`",
        f"- Workflow: `{ci['workflow']}`",
        f"- Driver: `{ci['driver']}`",
        f"- Runner: {ci['runner']}",
        f"- Estimated runtime: {ci['estimated_runtime']}",
        f"- Hard workflow timeout: {ci['timeout_minutes']} minutes",
        "",
        "A green structural job is not a substantive acceptance signal when the",
        "automation status is `pseudocode`, `reviewer-only`, or `blocked`.",
        "",
        "## Pseudocode",
        "",
        "```python",
        "problem = load_and_schema_validate('problem.yaml')",
        "submission = enumerate_non_readme_files('submission/')",
        "if not submission:",
        "    return structural_contract_passed",
    ]
    lines.extend(artifact_code)
    if profile["mode"] == "machine-checkable":
        lines.append("assert independent_checker_exit_code() == 0")
    elif profile["mode"] == "hybrid":
        lines.append("assert deterministic_subchecks_pass()")
        if problem["reviewer_contract"]["scope"] == "result-only":
            lines.append("emit('bounded final-artifact review required')")
        else:
            lines.append("emit('manual derivation review required')")
    elif profile["mode"] == "llm-reviewable":
        if problem["reviewer_contract"]["scope"] == "result-only":
            lines.append("emit('bounded final-artifact review required')")
        else:
            lines.append("emit('derivation review required outside CI')")
    elif profile["mode"] == "expert-review":
        lines.append("emit('substantive expert review required outside CI')")
    else:
        lines.append("raise ProtocolIncomplete('verification mode unclassified')")
    lines.extend(
        [
            "emit_structured_local_validity_report()",
            "```",
            "",
            "## GitHub Actions behavior",
            "",
            "The committed workflow always validates `problem.yaml` and runs verifier",
            "unit tests. When a submission exists, `tools/ci_verify.py` runs an",
            "implemented deterministic checker. If only pseudocode exists, it refuses to",
            "present the submission as machine-verified. Hybrid and reviewer-only cases",
            "emit an explicit manual-review requirement.",
            "",
            "## Runtime interpretation",
            "",
            "The estimate covers verification, not candidate discovery. If an artifact",
            "exceeds the timeout, move the same pinned command to a self-hosted runner,",
            "record hardware and wall time, and keep the acceptance predicate unchanged.",
            "",
        ]
    )
    return "\n".join(lines)


def render_workflow(timeout_minutes: int) -> str:
    return f"""name: verify

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  contract:
    runs-on: ubuntu-latest
    timeout-minutes: {timeout_minutes}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv run python tools/ci_verify.py
"""
