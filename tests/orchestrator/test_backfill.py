from datetime import datetime
from unittest.mock import patch

from evidence_engine.db.models import Topic
from evidence_engine.orchestrator.backfill import run_topic_backfill


def test_run_topic_backfill_forces_full_history_fetch(db_session):
    topic = Topic(
        canonical_label="Myocardial Infarction",
        mesh_id="68009203",
        last_checked_at=datetime(2026, 1, 1),
    )
    db_session.add(topic)
    db_session.flush()

    with patch("evidence_engine.orchestrator.backfill.run_topic_cycle") as mock_cycle:
        run_topic_backfill(db_session, topic, model_version="v1")

    assert topic.last_checked_at is None
    mock_cycle.assert_called_once()
    called_topic = mock_cycle.call_args[0][1]
    assert called_topic.last_checked_at is None
