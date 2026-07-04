from datetime import datetime
from unittest.mock import patch

from evidence_engine.db.models import Topic
from scripts.run_daily_cycle import process_all_topics


def test_process_all_topics_dispatches_backfill_for_new_topic_and_isolates_failures(db_session):
    db_session.commit = lambda: None
    db_session.rollback = lambda: None
    db_session.close = lambda: None

    new_topic = Topic(canonical_label="New Topic", mesh_id="D000001", status="active", last_checked_at=None)
    failing_topic = Topic(
        canonical_label="Failing Topic", mesh_id="D000003", status="active", last_checked_at=datetime(2026, 1, 1)
    )
    existing_topic = Topic(
        canonical_label="Existing Topic", mesh_id="D000002", status="active", last_checked_at=datetime(2026, 1, 1)
    )
    db_session.add_all([new_topic, failing_topic, existing_topic])
    db_session.flush()

    def fake_cycle(session, topic, model_version):
        if topic.canonical_label == "Failing Topic":
            raise RuntimeError("boom")

    with (
        patch("scripts.run_daily_cycle.run_topic_backfill") as mock_backfill,
        patch("scripts.run_daily_cycle.run_topic_cycle", side_effect=fake_cycle) as mock_cycle,
    ):
        process_all_topics(lambda: db_session, model_version="v1")

    mock_backfill.assert_called_once()
    assert mock_backfill.call_args[0][1].canonical_label == "New Topic"
    # Failing topic should raise, but existing_topic (after it) should still be processed
    assert mock_cycle.call_count == 2
    # Verify that existing_topic was indeed called despite the failure in failing_topic
    cycle_call_topics = [call[0][1].canonical_label for call in mock_cycle.call_args_list]
    assert "Failing Topic" in cycle_call_topics
    assert "Existing Topic" in cycle_call_topics
