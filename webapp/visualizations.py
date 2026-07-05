import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from evidence_engine.db.models import ChangeEvent, ChangeEventType, EvidenceTier, Paper, PaperTopic, Score


@dataclass
class TierDistribution:
    established: int = 0
    emerging: int = 0
    speculative: int = 0


def tier_distribution(session: Session, topic_id: uuid.UUID) -> TierDistribution:
    rows = session.execute(
        select(Score.evidence_tier, func.count())
        .join(PaperTopic, PaperTopic.paper_id == Score.paper_id)
        .where(PaperTopic.topic_id == topic_id)
        .group_by(Score.evidence_tier)
    ).all()

    distribution = TierDistribution()
    for tier, count in rows:
        if tier == EvidenceTier.ESTABLISHED:
            distribution.established = count
        elif tier == EvidenceTier.EMERGING:
            distribution.emerging = count
        elif tier == EvidenceTier.SPECULATIVE:
            distribution.speculative = count
    return distribution


@dataclass
class TimelineBucket:
    bucket_date: "datetime.date"
    event_type: ChangeEventType
    count: int


def change_timeline(
    session: Session, topic_id: uuid.UUID, window_start: datetime, window_end: datetime
) -> list[TimelineBucket]:
    day = func.date(ChangeEvent.detected_at)
    rows = session.execute(
        select(day, ChangeEvent.event_type, func.count())
        .where(
            ChangeEvent.topic_id == topic_id,
            ChangeEvent.detected_at > window_start,
            ChangeEvent.detected_at <= window_end,
        )
        .group_by(day, ChangeEvent.event_type)
        .order_by(day)
    ).all()

    return [TimelineBucket(bucket_date=bucket_date, event_type=event_type, count=count) for bucket_date, event_type, count in rows]
