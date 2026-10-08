from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import delete, select

import dashboard.activity as dashboard_activity
from dashboard.activity import JOB_NAME
from dashboard.models import DashboardJobState, TopicActivitySnapshot
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


def test_the_running_marker_is_visible_to_another_connection_while_the_job_runs():
    """`running` is the operator's only in-band signal, and it could not be read.

    docs/dashboard-metrics.md tells an operator that a persistent `running` means the
    process died without reaching the failure handler. That state was unobservable: it
    was written and cleared inside a single uncommitted transaction, so no other
    connection ever saw it, and a SIGKILL aborted the transaction and reverted it to
    `idle` with a stale completed_at -- the exact signature of a quiet week, which is the
    one thing the status exists to distinguish it from.

    This drives the real thing on a real connection and observes from a second one, since
    the defect was entirely about transaction visibility and any test sharing the job's
    session would have passed against the broken version.
    """
    from sqlalchemy import select

    from dashboard.activity import JOB_NAME, refresh_activity_snapshots
    from dashboard.models import DashboardJobState
    from evidence_engine.db.session import SessionLocal

    def observed_status():
        watcher = SessionLocal()
        try:
            row = watcher.execute(
                select(DashboardJobState.status).where(DashboardJobState.job_name == JOB_NAME)
            ).scalar_one_or_none()
            return row
        finally:
            watcher.close()

    seen_during_run = {}
    worker = SessionLocal()
    try:
        real_rank = dashboard_activity.rank_topics

        def peek_then_rank(*args, **kwargs):
            # Mid-run, from a different connection: this is the moment the doc describes.
            seen_during_run["status"] = observed_status()
            return real_rank(*args, **kwargs)

        with patch.object(dashboard_activity, "rank_topics", side_effect=peek_then_rank):
            refresh_activity_snapshots(worker)
        worker.commit()

        assert seen_during_run["status"] == "running", (
            f"another connection saw {seen_during_run['status']!r} mid-run; the marker is "
            "not committed, so the documented diagnostic cannot be observed"
        )
        assert observed_status() == "idle", "the marker must clear on success"
    finally:
        cleanup = SessionLocal()
        cleanup.execute(delete(DashboardJobState).where(DashboardJobState.job_name == JOB_NAME))
        cleanup.execute(delete(TopicActivitySnapshot))
        cleanup.commit()
        cleanup.close()
        worker.close()
