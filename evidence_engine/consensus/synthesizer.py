from sqlalchemy import select
from sqlalchemy.orm import Session

from evidence_engine.config import get_settings
from evidence_engine.db.models import ConsensusSnapshot, Paper, PaperTopic, Score, StudyType, Topic
from evidence_engine.llm.client import get_anthropic_client

TOP_TIER_TYPES = {StudyType.META_ANALYSIS, StudyType.SYSTEMATIC_REVIEW}
MIN_TOP_TIER_PAPERS = 2

SYNTHESIZE_TOOL = {
    "name": "synthesize_consensus",
    "description": "Write a consensus paragraph for a biomedical topic grounded only in the provided top-tier papers.",
    "input_schema": {
        "type": "object",
        "properties": {
            "consensus_text": {"type": "string"},
            "supporting_indices": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["consensus_text", "supporting_indices"],
    },
}


def _is_top_tier(score: Score) -> bool:
    return score.study_type in TOP_TIER_TYPES or (score.study_type == StudyType.RCT and score.final_score >= 70.0)


def get_top_tier_scores(session: Session, topic: Topic) -> list[Score]:
    rows = (
        session.execute(
            select(Score)
            .join(Paper, Score.paper_id == Paper.id)
            .join(PaperTopic, PaperTopic.paper_id == Paper.id)
            .where(PaperTopic.topic_id == topic.id, Paper.is_retracted.is_(False))
        )
        .scalars()
        .all()
    )
    return [s for s in rows if _is_top_tier(s)]


def synthesize_consensus(session: Session, topic: Topic, model_version: str) -> ConsensusSnapshot:
    top_tier = get_top_tier_scores(session, topic)

    if len(top_tier) < MIN_TOP_TIER_PAPERS:
        snapshot = ConsensusSnapshot(
            topic_id=topic.id,
            consensus_text=None,
            is_insufficient_evidence=True,
            supporting_paper_ids=[],
            model_version=model_version,
        )
        session.add(snapshot)
        session.flush()
        return snapshot

    listing = "\n\n".join(
        f"[{i}] {s.paper.title}\nAbstract: {s.paper.abstract}" for i, s in enumerate(top_tier)
    )
    client = get_anthropic_client()
    response = client.messages.create(
        model=get_settings().anthropic_model,
        max_tokens=1000,
        tools=[SYNTHESIZE_TOOL],
        tool_choice={"type": "tool", "name": "synthesize_consensus"},
        messages=[
            {"role": "user", "content": f"Topic: {topic.canonical_label}\n\nPapers:\n{listing}"}
        ],
    )

    consensus_text = None
    supporting_ids = []
    for block in response.content:
        if block.type == "tool_use":
            consensus_text = block.input.get("consensus_text")
            indices = block.input.get("supporting_indices", [])
            supporting_ids = [top_tier[i].paper_id for i in indices if 0 <= i < len(top_tier)]

    snapshot = ConsensusSnapshot(
        topic_id=topic.id,
        consensus_text=consensus_text,
        is_insufficient_evidence=False,
        supporting_paper_ids=supporting_ids,
        model_version=model_version,
    )
    session.add(snapshot)
    session.flush()
    return snapshot
