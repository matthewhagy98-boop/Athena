import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from evidence_engine.db.models import ConsensusSnapshot, Paper, Score, Topic


@dataclass
class PaperComparisonRow:
    paper: Paper
    score: Score | None


@dataclass
class PaperComparisonResult:
    rows: list[PaperComparisonRow] = field(default_factory=list)
    unresolved_ids: list[uuid.UUID] = field(default_factory=list)


@dataclass
class TopicComparisonRow:
    topic: Topic
    consensus: ConsensusSnapshot | None


@dataclass
class TopicComparisonResult:
    rows: list[TopicComparisonRow] = field(default_factory=list)
    unresolved_ids: list[uuid.UUID] = field(default_factory=list)


def compare_papers(session: Session, paper_ids: list[uuid.UUID]) -> PaperComparisonResult:
    rows = []
    unresolved = []
    for paper_id in paper_ids:
        paper = session.get(Paper, paper_id)
        if paper is None:
            unresolved.append(paper_id)
            continue
        score = session.execute(select(Score).where(Score.paper_id == paper_id)).scalar_one_or_none()
        rows.append(PaperComparisonRow(paper=paper, score=score))
    return PaperComparisonResult(rows=rows, unresolved_ids=unresolved)


def _latest_consensus(session: Session, topic_id: uuid.UUID) -> ConsensusSnapshot | None:
    return (
        session.execute(
            select(ConsensusSnapshot)
            .where(ConsensusSnapshot.topic_id == topic_id)
            .order_by(ConsensusSnapshot.generated_at.desc())
        )
        .scalars()
        .first()
    )


def compare_topics(session: Session, topic_ids: list[uuid.UUID]) -> TopicComparisonResult:
    rows = []
    unresolved = []
    for topic_id in topic_ids:
        topic = session.get(Topic, topic_id)
        if topic is None:
            unresolved.append(topic_id)
            continue
        consensus = _latest_consensus(session, topic_id)
        rows.append(TopicComparisonRow(topic=topic, consensus=consensus))
    return TopicComparisonResult(rows=rows, unresolved_ids=unresolved)
