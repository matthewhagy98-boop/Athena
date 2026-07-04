import logging

from sqlalchemy import select

from evidence_engine.db.models import Topic
from evidence_engine.db.session import SessionLocal
from evidence_engine.orchestrator.backfill import run_topic_backfill
from evidence_engine.orchestrator.cycle import run_topic_cycle

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("daily_cycle")

MODEL_VERSION = "v1"


def process_all_topics(session_factory, model_version: str) -> None:
    session = session_factory()
    try:
        topic_ids = [t.id for t in session.execute(select(Topic).where(Topic.status == "active")).scalars().all()]
    finally:
        session.close()

    for topic_id in topic_ids:
        session = session_factory()
        try:
            topic = session.get(Topic, topic_id)
            if topic.last_checked_at is None:
                run_topic_backfill(session, topic, model_version)
            else:
                run_topic_cycle(session, topic, model_version)
            session.commit()
            logger.info("Completed cycle for topic %s", topic.canonical_label)
        except Exception:
            session.rollback()
            logger.exception("Failed cycle for topic %s", topic_id)
        finally:
            session.close()


def main() -> None:
    process_all_topics(SessionLocal, MODEL_VERSION)


if __name__ == "__main__":
    main()
