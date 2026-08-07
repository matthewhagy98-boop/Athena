from datetime import datetime, timedelta

from sqlalchemy import select

from citations.models import CitationSnapshot, CitationVelocityCache
from citations.provider import CitationObservation
from citations.runner import run_citation_refresh
from evidence_engine.db.models import Paper


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
