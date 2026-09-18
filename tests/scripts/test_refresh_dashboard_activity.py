from datetime import datetime, timedelta

from sqlalchemy import select

from dashboard.activity import JOB_NAME
from dashboard.models import DashboardJobState
from evidence_engine.db.models import ChangeEvent, ChangeEventType, Topic


def test_a_failed_run_is_recorded_rather_than_silent(db_session, monkeypatch):
    # An operator must be able to tell a stale dashboard from an empty one.
    import scripts.refresh_dashboard_activity as job

    monkeypatch.setattr(job, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "commit", db_session.flush)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(
        job, "refresh_activity_snapshots", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    assert job.main() == 1

    state = db_session.execute(
        select(DashboardJobState).where(DashboardJobState.job_name == JOB_NAME)
    ).scalar_one_or_none()
    assert state is not None
    assert state.status == "failed"
    assert "boom" in state.last_error


def test_a_successful_run_returns_zero(db_session, monkeypatch):
    import scripts.refresh_dashboard_activity as job

    topic = Topic(canonical_label="Job topic")
    db_session.add(topic)
    db_session.flush()
    for _ in range(6):
        db_session.add(
            ChangeEvent(
                topic_id=topic.id,
                event_type=ChangeEventType.NEW_PAPER,
                detected_at=datetime.utcnow() - timedelta(days=1),
            )
        )
    db_session.flush()

    monkeypatch.setattr(job, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "commit", db_session.flush)
    monkeypatch.setattr(db_session, "close", lambda: None)

    assert job.main() == 0
