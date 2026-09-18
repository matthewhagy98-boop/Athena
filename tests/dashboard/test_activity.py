import pytest
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select

from dashboard.activity import JOB_NAME, read_current_activity, refresh_activity_snapshots
from dashboard.models import DashboardJobState, TopicActivitySnapshot
from evidence_engine.db.models import ChangeEvent, ChangeEventType, Topic

AS_OF = datetime(2026, 8, 2, 4, 10)


def _topic(db_session, label):
    topic = Topic(canonical_label=label)
    db_session.add(topic)
    db_session.flush()
    return topic


def _events(db_session, topic_id, count, days_before_end, event_type=ChangeEventType.NEW_PAPER):
    """`days_before_end` is measured back from the current window's end (midnight of AS_OF)."""
    moment = datetime(2026, 8, 2) - timedelta(days=days_before_end)
    for _ in range(count):
        db_session.add(
            ChangeEvent(topic_id=topic_id, event_type=event_type, detected_at=moment)
        )
    db_session.flush()


def test_a_topic_below_the_floor_is_not_ranked(db_session):
    topic = _topic(db_session, "Quiet topic")
    _events(db_session, topic.id, 4, days_before_end=1)

    refresh_activity_snapshots(db_session, as_of=AS_OF)
    payload = read_current_activity(db_session, limit=10)

    assert payload["topics"] == []


def test_a_topic_at_the_floor_is_ranked(db_session):
    topic = _topic(db_session, "Busy enough")
    _events(db_session, topic.id, 5, days_before_end=1)

    refresh_activity_snapshots(db_session, as_of=AS_OF)
    payload = read_current_activity(db_session, limit=10)

    assert [t["topic"]["canonical_label"] for t in payload["topics"]] == ["Busy enough"]
    assert payload["topics"][0]["event_count"] == 5
    assert payload["topics"][0]["rank"] == 1


def test_the_breakdown_by_event_type_is_recorded(db_session):
    topic = _topic(db_session, "Mixed")
    _events(db_session, topic.id, 4, 1, ChangeEventType.NEW_PAPER)
    _events(db_session, topic.id, 2, 2, ChangeEventType.CONSENSUS_UPDATED)
    _events(db_session, topic.id, 1, 3, ChangeEventType.PAPER_RETRACTED)

    refresh_activity_snapshots(db_session, as_of=AS_OF)
    row = read_current_activity(db_session, limit=10)["topics"][0]

    assert row["event_count"] == 7
    assert row["breakdown"] == {
        "new_paper": 4,
        "consensus_updated": 2,
        "contradiction_flagged": 0,
        "paper_retracted": 1,
    }


def test_an_event_on_the_window_start_boundary_is_excluded(db_session):
    # Half-open: window_start < detected_at <= window_end. An event at exactly
    # window_start belongs to the previous window and must not inflate this one.
    topic = _topic(db_session, "Boundary")
    _events(db_session, topic.id, 5, days_before_end=1)
    _events(db_session, topic.id, 3, days_before_end=7)  # exactly window_start

    refresh_activity_snapshots(db_session, as_of=AS_OF)
    row = read_current_activity(db_session, limit=10)["topics"][0]

    assert row["event_count"] == 5


def test_a_topic_without_eight_weeks_of_history_is_newly_tracked(db_session):
    topic = _topic(db_session, "Young")
    _events(db_session, topic.id, 9, days_before_end=1)
    _events(db_session, topic.id, 2, days_before_end=10)

    refresh_activity_snapshots(db_session, as_of=AS_OF)
    row = read_current_activity(db_session, limit=10)["topics"][0]

    assert row["is_newly_tracked"] is True
    assert row["trend_score"] is None
    assert row["baseline_mean"] is None


def test_a_topic_with_full_history_gets_a_score(db_session):
    topic = _topic(db_session, "Established")
    _events(db_session, topic.id, 24, days_before_end=1)
    # One event in each of the 8 prior weeks, plus one older than all of them so the
    # topic's first event predates the earliest baseline window.
    for week in range(1, 9):
        _events(db_session, topic.id, 1, days_before_end=7 * week + 1)
    _events(db_session, topic.id, 1, days_before_end=70)

    refresh_activity_snapshots(db_session, as_of=AS_OF)
    row = read_current_activity(db_session, limit=10)["topics"][0]

    assert row["is_newly_tracked"] is False
    assert row["baseline_weeks"] == 8
    assert row["trend_score"] is not None


def test_readers_never_see_a_partially_written_generation(db_session):
    # FR-C-010. The job writes rows first and advances the watermark last, so a run that
    # dies mid-write leaves the previous generation serving.
    topic = _topic(db_session, "First")
    _events(db_session, topic.id, 6, days_before_end=1)
    refresh_activity_snapshots(db_session, as_of=AS_OF)
    first = read_current_activity(db_session, limit=10)

    # Simulate a half-written later run: rows exist under a new generation id, but the
    # watermark has not been advanced to it.
    orphan_generation = uuid.uuid4()
    db_session.add(
        TopicActivitySnapshot(
            generation_id=orphan_generation,
            topic_id=topic.id,
            window_start=datetime(2026, 7, 26),
            window_end=datetime(2026, 8, 2),
            event_count=999,
            rank=1,
        )
    )
    db_session.flush()

    assert read_current_activity(db_session, limit=10)["topics"] == first["topics"]
    assert read_current_activity(db_session, limit=10)["topics"][0]["event_count"] != 999


def test_a_second_run_replaces_what_readers_see(db_session):
    topic = _topic(db_session, "Changing")
    _events(db_session, topic.id, 6, days_before_end=1)
    refresh_activity_snapshots(db_session, as_of=AS_OF)

    _events(db_session, topic.id, 5, days_before_end=2)
    refresh_activity_snapshots(db_session, as_of=AS_OF)

    assert read_current_activity(db_session, limit=10)["topics"][0]["event_count"] == 11


def test_the_job_records_its_outcome(db_session):
    topic = _topic(db_session, "Recorded")
    _events(db_session, topic.id, 6, days_before_end=1)

    generation = refresh_activity_snapshots(db_session, as_of=AS_OF)

    state = db_session.execute(
        select(DashboardJobState).where(DashboardJobState.job_name == JOB_NAME)
    ).scalar_one()
    assert state.current_generation_id == generation
    assert state.status == "idle"
    assert state.completed_at is not None
    assert state.topics_processed == 1
    assert state.running_generation_id is None


def test_cold_start_returns_nulls_not_an_error(db_session):
    # No job has ever run. The endpoint must still answer.
    payload = read_current_activity(db_session, limit=10)

    assert payload == {
        "computed_at": None,
        "window_start": None,
        "window_end": None,
        "topics": [],
    }


def test_limit_truncates_the_ranking(db_session):
    for index in range(4):
        topic = _topic(db_session, f"Topic {index}")
        _events(db_session, topic.id, 5 + index, days_before_end=1)

    refresh_activity_snapshots(db_session, as_of=AS_OF)
    payload = read_current_activity(db_session, limit=2)

    assert len(payload["topics"]) == 2
    assert [t["rank"] for t in payload["topics"]] == [1, 2]


def test_old_generations_are_pruned_but_the_current_one_is_never(db_session):
    from dashboard.activity import RETENTION_DAYS

    topic = _topic(db_session, "Retained")
    _events(db_session, topic.id, 6, days_before_end=1)

    stale_generation = uuid.uuid4()
    db_session.add(
        TopicActivitySnapshot(
            generation_id=stale_generation,
            topic_id=topic.id,
            window_start=datetime(2025, 1, 1),
            window_end=datetime(2025, 1, 8),
            event_count=1,
            rank=1,
            computed_at=datetime(2026, 8, 2) - timedelta(days=RETENTION_DAYS + 1),
        )
    )
    db_session.flush()

    current = refresh_activity_snapshots(db_session, as_of=AS_OF)

    remaining = db_session.execute(
        select(TopicActivitySnapshot.generation_id).distinct()
    ).scalars().all()
    assert stale_generation not in remaining
    assert current in remaining


def test_a_run_that_dies_before_publishing_leaves_the_previous_one_serving(db_session, monkeypatch):
    """FR-C-010, tested by actually interrupting the job.

    test_readers_never_see_a_partially_written_generation plants an orphan generation by
    hand. That proves the reader filters on the watermark, but it cannot distinguish
    write-then-publish from publish-then-write, because no run ever fails in it. This one
    fails a real run between ranking and publishing.

    With the correct ordering the watermark still points at the previous generation, so
    readers keep seeing it. With the ordering reversed -- watermark advanced before the
    rows are written -- the watermark would point at a generation containing no rows and
    the dashboard would go blank on every failed run.
    """
    import dashboard.activity as activity_module

    topic = _topic(db_session, "Survivor")
    _events(db_session, topic.id, 6, days_before_end=1)
    refresh_activity_snapshots(db_session, as_of=AS_OF)
    before = read_current_activity(db_session, limit=10)
    assert before["topics"][0]["event_count"] == 6

    def explode(*args, **kwargs):
        raise RuntimeError("died mid-run")

    monkeypatch.setattr(activity_module, "rank_topics", explode)

    with pytest.raises(RuntimeError):
        refresh_activity_snapshots(db_session, as_of=AS_OF)

    after = read_current_activity(db_session, limit=10)
    assert after["topics"] == before["topics"], "a failed run changed what readers see"
    assert after["topics"], "the dashboard went blank after a failed run"


def test_pruning_is_by_age_not_by_everything_except_the_current(db_session):
    """Two different rules, only one correct, and the original test could not tell them apart.

    It planted a single stale generation, so "delete rows older than the horizon" and
    "delete every generation except the current one" produced identical results. The
    second rule would throw away yesterday's generation on every run, which is the only
    history available for diagnosing a bad ranking.
    """
    from dashboard.activity import RETENTION_DAYS

    topic = _topic(db_session, "Retention")
    _events(db_session, topic.id, 6, days_before_end=1)

    stale = uuid.uuid4()
    recent = uuid.uuid4()
    for generation, age_days in ((stale, RETENTION_DAYS + 1), (recent, 3)):
        db_session.add(
            TopicActivitySnapshot(
                generation_id=generation,
                topic_id=topic.id,
                window_start=datetime(2025, 1, 1),
                window_end=datetime(2025, 1, 8),
                event_count=1,
                rank=1,
                computed_at=datetime(2026, 8, 2) - timedelta(days=age_days),
            )
        )
    db_session.flush()

    current = refresh_activity_snapshots(db_session, as_of=AS_OF)

    remaining = set(
        db_session.execute(select(TopicActivitySnapshot.generation_id).distinct()).scalars().all()
    )
    assert stale not in remaining, "a generation past the retention horizon survived"
    assert recent in remaining, "pruning deleted a non-current generation that was still young"
    assert current in remaining


def test_newly_tracked_topics_are_ranked_against_the_median_baseline(db_session):
    """The median must actually be computed, not stubbed to zero.

    The trend-level tests pass provisional_baseline explicitly, so they cannot tell
    whether this module derives it. It matters: with the real median the newly-tracked
    topic's key is 0.909 and the scored topic wins; with 0.0 it is 10.0 and the
    newly-tracked topic wins. Those are opposite orderings of the same two rows, and the
    widget shows raw counts, so the wrong one renders "9 changes" above "30 changes".
    """
    established = _topic(db_session, "Established")
    _events(db_session, established.id, 30, days_before_end=1)
    for week in range(1, 9):
        _events(db_session, established.id, 10, days_before_end=7 * week + 1)
    # One event older than every baseline window, so the topic counts as fully tracked
    # without contributing to any prior window's count.
    _events(db_session, established.id, 1, days_before_end=70)

    newcomer = _topic(db_session, "Newcomer")
    _events(db_session, newcomer.id, 9, days_before_end=1)

    refresh_activity_snapshots(db_session, as_of=AS_OF)
    rows = read_current_activity(db_session, limit=10)["topics"]

    labels = [r["topic"]["canonical_label"] for r in rows]
    assert labels[0] == "Established", (
        f"ranked {labels} -- a newly-tracked topic with 9 events outranked a scored "
        f"topic with 30, which is what a zero provisional baseline produces"
    )
    # And the newly-tracked topic still carries no score of its own (FR-C-003).
    newcomer_row = next(r for r in rows if r["topic"]["canonical_label"] == "Newcomer")
    assert newcomer_row["trend_score"] is None
    assert newcomer_row["is_newly_tracked"] is True
