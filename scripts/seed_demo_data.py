"""Seed a demo topic with papers for local dev and the e2e smoke test."""

from datetime import date, datetime

from sqlalchemy import select

from evidence_engine.db.models import (
    ChangeEvent,
    ChangeEventType,
    EvidenceTier,
    Paper,
    PaperTopic,
    Score,
    StudyType,
    Topic,
)
from evidence_engine.db.session import SessionLocal
from webapp.search_index import sync_search_index

DEMO_TOPIC = "Demo: AI and Cognitive Mapping"

PAPERS = [
    ("Longitudinal analysis of neural plasticity under AI assistance", EvidenceTier.ESTABLISHED, StudyType.META_ANALYSIS, 88.0),
    ("Cognitive offloading and digital tool interaction: a systematic review", EvidenceTier.ESTABLISHED, StudyType.SYSTEMATIC_REVIEW, 76.0),
    ("Cross-cultural variance in generative AI adaptation", EvidenceTier.EMERGING, StudyType.RCT, 44.0),
    ("Attention residue in multi-agent workflows: a hypothesis", EvidenceTier.SPECULATIVE, StudyType.OPINION_EDITORIAL, 12.0),
]


def main() -> None:
    """Converge the database on the demo state.

    Re-running is safe and is sometimes necessary: the test suite's
    `reset_leaked_state` fixture truncates `paper_search_index`, so a seeded
    topic can outlive its search-index rows. Existence of the topic therefore
    can't stand in for "fully seeded" — the index is rebuilt on every run.
    """
    session = SessionLocal()
    try:
        topic = session.execute(select(Topic).where(Topic.canonical_label == DEMO_TOPIC)).scalar_one_or_none()
        if topic is not None:
            sync_search_index(session)
            session.commit()
            print(f"Demo topic {topic.id} already present; search index rebuilt.")
            return

        topic = Topic(canonical_label=DEMO_TOPIC, mesh_id="D_DEMO_01")
        session.add(topic)
        session.flush()

        for i, (title, tier, study_type, score) in enumerate(PAPERS):
            paper = Paper(
                title=title,
                abstract=f"Demo abstract for: {title}.",
                pub_date=date(2026, 1 + i, 15),
            )
            session.add(paper)
            session.flush()
            session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
            session.add(
                Score(paper_id=paper.id, evidence_tier=tier, study_type=study_type, final_score=score, model_version="demo")
            )
            session.add(
                ChangeEvent(
                    topic_id=topic.id,
                    paper_id=paper.id,
                    event_type=ChangeEventType.NEW_PAPER,
                    detected_at=datetime(2026, 1 + i, 16),
                )
            )
        session.flush()
        sync_search_index(session)
        session.commit()
        print(f"Seeded demo topic {topic.id} with {len(PAPERS)} papers.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
