from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from evidence_engine.db.models import ChangeEvent, ChangeEventType, ConsensusSnapshot, Paper, Score, Topic

from digest.models import User
from digest.profiles import list_interests


@dataclass
class TopicChange:
    event_type: ChangeEventType
    detected_at: datetime
    paper: Paper | None = None
    score: Score | None = None
    consensus: ConsensusSnapshot | None = None


@dataclass
class TopicDigestData:
    topic: Topic
    changes: list[TopicChange]


def _latest_consensus(session: Session, topic_id) -> ConsensusSnapshot | None:
    return (
        session.execute(
            select(ConsensusSnapshot)
            .where(ConsensusSnapshot.topic_id == topic_id)
            .order_by(ConsensusSnapshot.generated_at.desc())
        )
        .scalars()
        .first()
    )


def aggregate_changes_for_user(
    session: Session, user: User, window_start: datetime, window_end: datetime
) -> list[TopicDigestData]:
    topics = list_interests(session, user)
    results: list[TopicDigestData] = []

    for topic in topics:
        events = (
            session.execute(
                select(ChangeEvent)
                .where(
                    ChangeEvent.topic_id == topic.id,
                    ChangeEvent.detected_at > window_start,
                    ChangeEvent.detected_at <= window_end,
                )
                .order_by(ChangeEvent.detected_at)
            )
            .scalars()
            .all()
        )
        if not events:
            continue

        changes = []
        for event in events:
            paper = session.get(Paper, event.paper_id) if event.paper_id else None
            score = None
            if paper is not None:
                score = session.execute(select(Score).where(Score.paper_id == paper.id)).scalar_one_or_none()
            consensus = None
            if event.event_type == ChangeEventType.CONSENSUS_UPDATED:
                consensus = _latest_consensus(session, topic.id)
            changes.append(
                TopicChange(
                    event_type=event.event_type,
                    detected_at=event.detected_at,
                    paper=paper,
                    score=score,
                    consensus=consensus,
                )
            )
        results.append(TopicDigestData(topic=topic, changes=changes))

    return results
