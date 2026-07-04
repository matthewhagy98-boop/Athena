from dataclasses import dataclass

from tenacity import retry, retry_if_result, stop_after_attempt, wait_exponential

from evidence_engine.llm.client import call_forced_tool

from digest.aggregate import TopicChange, TopicDigestData
from evidence_engine.db.models import ChangeEventType

COMPOSE_TOOL = {
    "name": "compose_topic_narrative",
    "description": (
        "Write a short 2-4 sentence narrative summarizing what changed for a research topic, "
        "for a weekly email digest aimed at a professional audience."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"narrative": {"type": "string"}},
        "required": ["narrative"],
    },
}


class ComposeError(Exception):
    pass


@dataclass
class ComposedTopicSection:
    topic_label: str
    narrative: str
    change_count: int


@dataclass
class ComposedDigest:
    sections: list[ComposedTopicSection]


def _describe_change(change: TopicChange) -> str:
    if change.event_type == ChangeEventType.NEW_PAPER:
        tier = change.score.evidence_tier.value if change.score and change.score.evidence_tier else "unknown"
        title = change.paper.title if change.paper else "untitled paper"
        return f"- New paper ({tier} tier): {title}"
    if change.event_type == ChangeEventType.CONSENSUS_UPDATED:
        text = change.consensus.consensus_text if change.consensus else None
        return f"- Consensus updated: {text or 'insufficient evidence'}"
    if change.event_type == ChangeEventType.CONTRADICTION_FLAGGED:
        title = change.paper.title if change.paper else "a new paper"
        return f"- New paper contradicts current consensus: {title}"
    if change.event_type == ChangeEventType.PAPER_RETRACTED:
        title = change.paper.title if change.paper else "a paper"
        return f"- Paper retracted: {title}"
    return f"- {change.event_type.value}"


@retry(
    retry=retry_if_result(lambda r: r is None),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.1, min=0.1, max=0.5),
    retry_error_callback=lambda retry_state: None,
)
def _call_with_retry(prompt: str) -> dict | None:
    return call_forced_tool(prompt, COMPOSE_TOOL, max_tokens=500)


def compose_digest(topic_digests: list[TopicDigestData]) -> ComposedDigest:
    sections = []
    for topic_digest in topic_digests:
        change_lines = "\n".join(_describe_change(c) for c in topic_digest.changes)
        prompt = f"Topic: {topic_digest.topic.canonical_label}\n\nChanges this period:\n{change_lines}"
        result = _call_with_retry(prompt)
        if result is None:
            raise ComposeError(f"Failed to compose narrative for topic '{topic_digest.topic.canonical_label}'")
        sections.append(
            ComposedTopicSection(
                topic_label=topic_digest.topic.canonical_label,
                narrative=result["narrative"],
                change_count=len(topic_digest.changes),
            )
        )
    return ComposedDigest(sections=sections)
