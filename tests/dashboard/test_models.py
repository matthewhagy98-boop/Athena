import uuid
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from dashboard.models import DashboardJobState, DashboardRateWindow, TopicActivitySnapshot
from evidence_engine.db.models import Topic


def _topic(db_session, label="Atrial fibrillation"):
    topic = Topic(canonical_label=label)
    db_session.add(topic)
    db_session.flush()
    return topic


def _snapshot(topic_id, **overrides):
    defaults = dict(
        generation_id=uuid.uuid4(),
        topic_id=topic_id,
        window_start=datetime(2026, 7, 26),
        window_end=datetime(2026, 8, 2),
        event_count=24,
        rank=1,
    )
    defaults.update(overrides)
    return TopicActivitySnapshot(**defaults)


def test_snapshot_round_trip(db_session):
    topic = _topic(db_session)
    row = _snapshot(topic.id, new_paper_count=19, baseline_mean=7.375, baseline_weeks=8,
                    trend_score=4.173)
    db_session.add(row)
    db_session.flush()

    stored = db_session.get(TopicActivitySnapshot, row.id)
    assert stored.event_count == 24
    assert float(stored.trend_score) == 4.173
    assert stored.is_newly_tracked is False
    assert stored.consensus_updated_count == 0


def test_a_newly_tracked_snapshot_stores_a_null_score(db_session):
    topic = _topic(db_session, "Long COVID sequelae")
    row = _snapshot(topic.id, baseline_weeks=3, baseline_mean=None, trend_score=None,
                    is_newly_tracked=True, rank=4)
    db_session.add(row)
    db_session.flush()

    assert row.trend_score is None
    assert row.baseline_mean is None
    assert row.is_newly_tracked is True


def test_one_topic_appears_once_per_generation(db_session):
    topic = _topic(db_session)
    generation = uuid.uuid4()
    db_session.add(_snapshot(topic.id, generation_id=generation))
    db_session.flush()
    db_session.add(_snapshot(topic.id, generation_id=generation, rank=2))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_the_same_topic_may_appear_in_two_generations(db_session):
    # Generations are independent runs; the unique constraint must not block tomorrow's.
    topic = _topic(db_session)
    db_session.add(_snapshot(topic.id, generation_id=uuid.uuid4()))
    db_session.flush()
    db_session.add(_snapshot(topic.id, generation_id=uuid.uuid4()))
    db_session.flush()  # must not raise


def test_deleting_a_topic_cascades_to_its_snapshots(db_session):
    # Snapshots are derived and disposable, so a deleted topic must not leave orphans
    # or block its own deletion with a FK violation.
    from sqlalchemy import select

    topic = _topic(db_session, "Doomed")
    db_session.add(_snapshot(topic.id))
    db_session.flush()

    db_session.delete(topic)
    db_session.flush()

    remaining = db_session.execute(
        select(TopicActivitySnapshot).where(TopicActivitySnapshot.topic_id == topic.id)
    ).scalars().all()
    assert remaining == []


def test_job_state_round_trip(db_session):
    state = DashboardJobState(job_name="activity_snapshot")
    db_session.add(state)
    db_session.flush()

    assert state.status == "idle"
    assert state.current_generation_id is None
    assert state.topics_processed == 0


def test_job_name_is_unique(db_session):
    db_session.add(DashboardJobState(job_name="activity_snapshot"))
    db_session.flush()
    db_session.add(DashboardJobState(job_name="activity_snapshot"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_rate_window_round_trip(db_session):
    window = DashboardRateWindow(subject="user:abc", window_start=datetime(2026, 8, 2, 9, 0))
    db_session.add(window)
    db_session.flush()

    assert window.request_count == 0


def test_one_counter_per_subject_per_window(db_session):
    start = datetime(2026, 8, 2, 9, 0)
    db_session.add(DashboardRateWindow(subject="user:abc", window_start=start))
    db_session.flush()
    db_session.add(DashboardRateWindow(subject="user:abc", window_start=start))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_the_change_events_detected_at_index_exists(db_session):
    """The one index this sub-project adds to an engine-owned table.

    Alembic will not autogenerate it: `change_events` belongs to evidence_engine and
    `dashboard/models.py` does not declare it, so there is no model diff to detect. It was
    added to the migration by hand, which means regenerating that migration drops it
    silently.

    Every window query in this sub-project filters `change_events` by `detected_at`, and
    the column has no other index. Without this test the failure mode is not a red build
    -- it is a dashboard that gets slower as the event table grows, discovered in
    production. Asserting it here makes the hand-edit survive.
    """
    from sqlalchemy import text

    found = db_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'change_events' AND indexname = 'ix_change_events_detected_at'"
        )
    ).scalar_one_or_none()

    assert found == "ix_change_events_detected_at", (
        "ix_change_events_detected_at is missing. It is hand-added in the dashboard "
        "migration; regenerating that migration drops it."
    )
