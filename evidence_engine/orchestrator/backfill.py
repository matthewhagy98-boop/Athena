from sqlalchemy.orm import Session

from evidence_engine.adapters.base import SourceAdapter
from evidence_engine.db.models import Topic
from evidence_engine.orchestrator.cycle import run_topic_cycle


def run_topic_backfill(
    session: Session,
    topic: Topic,
    model_version: str,
    adapters: list[SourceAdapter] | None = None,
) -> None:
    topic.last_checked_at = None
    run_topic_cycle(session, topic, model_version, adapters=adapters)
