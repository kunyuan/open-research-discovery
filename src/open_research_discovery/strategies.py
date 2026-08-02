from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol


EXPLICIT_OPEN_QUESTIONS = "lkm_explicit_open_questions"
TOPIC_DECOMPOSITION = "lkm_topic_decomposition"


@dataclass(frozen=True)
class CandidateSeed:
    """Strategy-neutral input to the shared canonicalization/refinement path."""

    source_key: str
    strategy_id: str
    strategy_version: int
    origin_class: str
    domain_ids: list[str]
    title: str
    content: str
    source_records: list[dict[str, Any]]
    origin: dict[str, Any]
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DiscoveryStrategy(Protocol):
    strategy_id: str
    version: int

    def discover(
        self, pipeline: Any, config: dict[str, Any]
    ) -> list[CandidateSeed]: ...


class LkmExplicitOpenQuestionsStrategy:
    strategy_id = EXPLICIT_OPEN_QUESTIONS
    version = 1

    def discover(
        self, pipeline: Any, config: dict[str, Any]
    ) -> list[CandidateSeed]:
        del config
        discovered = pipeline._discover()
        questions = pipeline._ingest(discovered)
        return [pipeline._explicit_question_seed(question, self) for question in questions]


class LkmTopicDecompositionStrategy:
    strategy_id = TOPIC_DECOMPOSITION
    version = 1

    def discover(
        self, pipeline: Any, config: dict[str, Any]
    ) -> list[CandidateSeed]:
        return pipeline._discover_topic_decomposition(config, self)


STRATEGY_REGISTRY: dict[str, DiscoveryStrategy] = {
    EXPLICIT_OPEN_QUESTIONS: LkmExplicitOpenQuestionsStrategy(),
    TOPIC_DECOMPOSITION: LkmTopicDecompositionStrategy(),
}


def configured_strategies(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the backward-compatible strategy list for one campaign."""

    configured = config.get("strategies")
    if configured:
        return [dict(item) for item in configured]
    return [{"type": EXPLICIT_OPEN_QUESTIONS}]
