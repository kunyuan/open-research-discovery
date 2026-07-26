from __future__ import annotations

from typing import Any, Iterable


OBLIGATION_KINDS = {
    "direct-artifact",
    "source-requested-formal-proof",
    "derivation",
    "expert-judgment",
}


class RouteContractError(ValueError):
    """A proposed review scope is inconsistent with its acceptance obligations."""


def review_scope_for(obligations: Iterable[dict[str, Any]]) -> str:
    """Return the least permissive scope required by all load-bearing obligations."""

    items = list(obligations)
    if not items:
        return "unclassified"
    kinds = {str(item.get("kind") or "") for item in items}
    if not kinds.issubset(OBLIGATION_KINDS):
        return "unclassified"
    if "expert-judgment" in kinds:
        return "expert-intensive"
    if "derivation" in kinds:
        return "result-and-derivation"
    return "result-only"


def route_contract_errors(
    candidate: dict[str, Any], decision: dict[str, Any]
) -> list[str]:
    """Check source provenance and scope consistency for one proposed route."""

    errors = decision_contract_errors(decision)
    obligations = decision.get("acceptance_obligations")
    if not isinstance(obligations, list) or not obligations:
        return errors

    support = {
        str(item.get("source_key") or ""): item
        for item in candidate.get("source_support") or []
        if isinstance(item, dict)
    }
    for index, obligation in enumerate(obligations):
        if not isinstance(obligation, dict):
            continue
        kind = str(obligation.get("kind") or "")
        source_key = str(obligation.get("source_key") or "")
        excerpt = str(obligation.get("exact_excerpt") or "")
        if source_key not in support:
            errors.append(
                f"acceptance_obligations[{index}].source_key is not in source_support"
            )
        elif excerpt != str(support[source_key].get("exact_excerpt") or ""):
            errors.append(
                f"acceptance_obligations[{index}].exact_excerpt must exactly match "
                "source_support"
            )
        if (
            kind == "source-requested-formal-proof"
            and source_key in support
            and support[source_key].get("formal_proof_requested") is not True
        ):
            errors.append(
                f"acceptance_obligations[{index}] claims a formal-proof "
                "delivery contract that the source does not request"
            )
    return errors


def decision_contract_errors(decision: dict[str, Any]) -> list[str]:
    """Check obligation, scope, and final-deliverable coherence without sources."""

    errors: list[str] = []
    obligations = decision.get("acceptance_obligations")
    if not isinstance(obligations, list) or not obligations:
        return ["acceptance_obligations must contain every load-bearing check"]
    for index, obligation in enumerate(obligations):
        if not isinstance(obligation, dict):
            errors.append(f"acceptance_obligations[{index}] must be an object")
            continue
        kind = str(obligation.get("kind") or "")
        if kind not in OBLIGATION_KINDS:
            errors.append(
                f"acceptance_obligations[{index}].kind is not recognized"
            )
        if obligation.get("required") is not True:
            errors.append(
                f"acceptance_obligations[{index}].required must be true"
            )
    expected_scope = review_scope_for(
        item for item in obligations if isinstance(item, dict)
    )
    declared_scope = str(
        decision.get("review_scope") or decision.get("scope") or ""
    )
    if declared_scope != expected_scope:
        errors.append(
            f"review scope {declared_scope!r} conflicts with load-bearing "
            f"obligations; expected {expected_scope!r}"
        )
    uses_proof_assistant = decision.get("uses_proof_assistant") is True
    artifact_type = str(decision.get("artifact_type") or "")
    has_source_requested_formal_proof = any(
        isinstance(item, dict)
        and item.get("kind") == "source-requested-formal-proof"
        for item in obligations
    )
    if artifact_type == "formal-proof" and not uses_proof_assistant:
        errors.append(
            "artifact_type='formal-proof' requires uses_proof_assistant=true"
        )
    if uses_proof_assistant and artifact_type != "formal-proof":
        errors.append(
            "uses_proof_assistant=true requires artifact_type='formal-proof'"
        )
    if uses_proof_assistant and not has_source_requested_formal_proof:
        errors.append(
            "a proof-assistant deliverable requires a "
            "source-requested-formal-proof obligation"
        )
    return errors


def validate_route_contract(
    candidate: dict[str, Any], decision: dict[str, Any]
) -> None:
    errors = route_contract_errors(candidate, decision)
    if errors:
        raise RouteContractError("; ".join(errors))
