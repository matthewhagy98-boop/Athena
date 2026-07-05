from datetime import datetime

from evidence_engine.db.models import ChangeEvent, ChangeEventType, EvidenceTier, Paper, PaperTopic, Score, Topic
from webapp.visualizations import change_timeline, tier_distribution


def test_tier_distribution_counts_papers_by_tier(db_session):
    topic = Topic(canonical_label="Distribution Topic", mesh_id="D000001")
    db_session.add(topic)
    db_session.flush()

    for tier in [EvidenceTier.ESTABLISHED, EvidenceTier.ESTABLISHED, EvidenceTier.EMERGING, EvidenceTier.SPECULATIVE]:
        paper = Paper(title=f"Paper {tier.value} {uuid_suffix(tier)}")
        db_session.add(paper)
        db_session.flush()
        db_session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
        db_session.add(Score(paper_id=paper.id, evidence_tier=tier, final_score=50.0, model_version="v1"))
    db_session.flush()

    distribution = tier_distribution(db_session, topic.id)

    assert distribution.established == 2
    assert distribution.emerging == 1
    assert distribution.speculative == 1


def uuid_suffix(tier):
    import uuid

    return uuid.uuid4().hex[:6]


def test_tier_distribution_returns_zeros_for_topic_with_no_scored_papers(db_session):
    topic = Topic(canonical_label="Empty Topic", mesh_id="D000002")
    db_session.add(topic)
    db_session.flush()

    distribution = tier_distribution(db_session, topic.id)

    assert distribution.established == 0
    assert distribution.emerging == 0
    assert distribution.speculative == 0


def test_change_timeline_buckets_by_day_and_event_type(db_session):
    topic = Topic(canonical_label="Timeline Topic", mesh_id="D000003")
    db_session.add(topic)
    db_session.flush()

    db_session.add_all(
        [
            ChangeEvent(topic_id=topic.id, event_type=ChangeEventType.NEW_PAPER, detected_at=datetime(2026, 6, 1, 9, 0)),
            ChangeEvent(topic_id=topic.id, event_type=ChangeEventType.NEW_PAPER, detected_at=datetime(2026, 6, 1, 15, 0)),
            ChangeEvent(topic_id=topic.id, event_type=ChangeEventType.CONSENSUS_UPDATED, detected_at=datetime(2026, 6, 2, 9, 0)),
        ]
    )
    db_session.flush()

    buckets = change_timeline(
        db_session, topic.id, window_start=datetime(2026, 5, 31), window_end=datetime(2026, 6, 3)
    )

    bucket_map = {(b.bucket_date, b.event_type): b.count for b in buckets}
    assert bucket_map[(datetime(2026, 6, 1).date(), ChangeEventType.NEW_PAPER)] == 2
    assert bucket_map[(datetime(2026, 6, 2).date(), ChangeEventType.CONSENSUS_UPDATED)] == 1


def test_change_timeline_window_start_exclusive_window_end_inclusive(db_session):
    topic = Topic(canonical_label="Boundary Topic", mesh_id="D000004")
    db_session.add(topic)
    db_session.flush()

    db_session.add_all(
        [
            ChangeEvent(topic_id=topic.id, event_type=ChangeEventType.NEW_PAPER, detected_at=datetime(2026, 6, 1, 0, 0, 0)),
            ChangeEvent(topic_id=topic.id, event_type=ChangeEventType.NEW_PAPER, detected_at=datetime(2026, 6, 8, 0, 0, 0)),
        ]
    )
    db_session.flush()

    buckets = change_timeline(
        db_session, topic.id, window_start=datetime(2026, 6, 1, 0, 0, 0), window_end=datetime(2026, 6, 8, 0, 0, 0)
    )

    total_count = sum(b.count for b in buckets)
    assert total_count == 1
