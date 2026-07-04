from sqlalchemy.orm import Session

from evidence_engine.db.models import ChangeEvent, ChangeEventType, Paper, Topic


def record_change_event(
    session: Session,
    topic: Topic,
    event_type: ChangeEventType,
    paper: Paper | None = None,
) -> ChangeEvent:
    event = ChangeEvent(
        topic_id=topic.id,
        paper_id=paper.id if paper else None,
        event_type=event_type,
    )
    session.add(event)
    session.flush()
    return event
