from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from citations.models import CitationRefreshState, CitationSnapshot, CitationVelocityCache
from citations.provider import CitationObservation
from citations.runner import run_citation_refresh
from evidence_engine.db.models import Paper
from evidence_engine.db.session import engine


class FakeClient:
    def __init__(self):
        self.calls = []

    def fetch_batch(self, ids):
        self.calls.append(list(ids))
        return {i: CitationObservation(i, 42, None) for i in ids}


def test_runner_does_nothing_when_flag_is_disabled(db_session, monkeypatch):
    monkeypatch.setattr("citations.runner._tracking_enabled", lambda: False)
    paper = Paper(title="Flagged off", semantic_scholar_id="s2-off")
    db_session.add(paper)
    db_session.flush()
    client = FakeClient()

    assert run_citation_refresh(db_session, client=client) is None
    assert db_session.execute(select(CitationSnapshot)).scalars().all() == []
    # The provider must not be contacted at all when disabled.
    assert client.calls == []


def test_runner_collects_and_computes_when_enabled(db_session, monkeypatch):
    monkeypatch.setattr("citations.runner._tracking_enabled", lambda: True)
    paper = Paper(title="Flagged on", semantic_scholar_id="s2-on")
    db_session.add(paper)
    db_session.flush()

    state = run_citation_refresh(db_session, client=FakeClient(), now=datetime(2026, 8, 2, 9, 0))

    assert state is not None
    assert state.papers_refreshed == 1
    snaps = db_session.execute(select(CitationSnapshot)).scalars().all()
    assert len(snaps) == 1 and snaps[0].citation_count == 42


def test_runner_also_recomputes_velocity(db_session, monkeypatch):
    # Two runs 30 days apart should leave a ready velocity behind, proving the
    # runner invokes the compute pass and not just collection.
    monkeypatch.setattr("citations.runner._tracking_enabled", lambda: True)
    paper = Paper(title="Two observations", semantic_scholar_id="s2-two")
    db_session.add(paper)
    db_session.flush()

    class Rising:
        def __init__(self, count):
            self.count = count

        def fetch_batch(self, ids):
            return {i: CitationObservation(i, self.count, None) for i in ids}

    start = datetime(2026, 7, 1, 9, 0)
    run_citation_refresh(db_session, client=Rising(100), now=start)
    run_citation_refresh(db_session, client=Rising(130), now=start + timedelta(days=30))

    cache = db_session.execute(
        select(CitationVelocityCache).where(CitationVelocityCache.paper_id == paper.id)
    ).scalar_one()
    assert cache.status == "ready"
    assert cache.observation_count == 2


def test_snapshots_survive_a_recompute_failure(monkeypatch):
    """A crashed recompute must not roll back the day's snapshots.

    `db_session` (used by every other test here) wraps the test in a transaction
    that is rolled back at teardown; `session.commit()` inside it only joins that
    outer transaction rather than making a real, durable commit (verified: a row
    inserted and `session.commit()`-ed through `db_session`, then the outer
    transaction rolled back, is gone). That fixture therefore cannot prove
    anything about commit durability across a failure. This test instead drives a
    session bound to its own, un-nested connection so its commits are real, and
    cleans up explicitly afterward since nothing will roll them back for it.
    """
    monkeypatch.setattr("citations.runner._tracking_enabled", lambda: True)

    class FakeClient:
        def fetch_batch(self, ids):
            return {i: CitationObservation(i, 42, None) for i in ids}

    def boom(*args, **kwargs):
        raise RuntimeError("boom in recompute_all")

    monkeypatch.setattr("citations.runner.recompute_all", boom)

    connection = engine.connect()
    session = Session(bind=connection)
    pre_existing_state_id = session.execute(
        select(CitationRefreshState.id).where(CitationRefreshState.job_name == "citation_refresh")
    ).scalar_one_or_none()

    paper_id = None
    try:
        paper = Paper(title="Durable snapshot paper", semantic_scholar_id="s2-durable-test")
        session.add(paper)
        session.commit()
        paper_id = paper.id

        # Must not raise: a failed recompute is caught and logged, never propagated.
        run_citation_refresh(session, client=FakeClient(), now=datetime(2026, 8, 2, 9, 0))

        # Read from a second, independent connection to prove the snapshot is
        # really durable, not merely visible within the same open transaction.
        with engine.connect() as verify_conn:
            verify_session = Session(bind=verify_conn)
            snaps = (
                verify_session.execute(
                    select(CitationSnapshot).where(CitationSnapshot.paper_id == paper_id)
                )
                .scalars()
                .all()
            )
            verify_session.close()

        assert len(snaps) == 1
        assert snaps[0].citation_count == 42
    finally:
        session.rollback()
        session.close()
        connection.close()
        # Real commits happened above; nothing rolls them back automatically.
        with engine.begin() as cleanup_conn:
            if paper_id is not None:
                cleanup_conn.execute(
                    text("DELETE FROM citation_velocity_cache WHERE paper_id = :pid"),
                    {"pid": paper_id},
                )
                cleanup_conn.execute(
                    text("DELETE FROM citation_snapshots WHERE paper_id = :pid"),
                    {"pid": paper_id},
                )
                cleanup_conn.execute(text("DELETE FROM papers WHERE id = :pid"), {"pid": paper_id})
            if pre_existing_state_id is None:
                cleanup_conn.execute(
                    text("DELETE FROM citation_refresh_state WHERE job_name = 'citation_refresh'")
                )
