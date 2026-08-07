from datetime import date, datetime

from sqlalchemy import select

from citations.models import CitationRefreshState, CitationSnapshot, CitationVelocityCache
from citations.provider import CitationObservation, CitationProviderError
from citations.refresh import refresh_citations
from evidence_engine.db.models import Paper


class FakeClient:
    def __init__(self, responses, error=None):
        self.responses = responses
        self.error = error
        self.calls = []

    def fetch_batch(self, ids):
        self.calls.append(list(ids))
        if self.error:
            raise self.error
        return {i: self.responses[i] for i in ids if i in self.responses}


def _paper(db_session, s2_id, title):
    paper = Paper(title=title, semantic_scholar_id=s2_id)
    db_session.add(paper)
    db_session.flush()
    return paper


def test_refresh_writes_one_snapshot_per_paper(db_session):
    paper = _paper(db_session, "s2-1", "Tracked paper")
    client = FakeClient({"s2-1": CitationObservation("s2-1", 100, 7)})

    state = refresh_citations(db_session, client, now=datetime(2026, 8, 2, 9, 0))

    snaps = db_session.execute(select(CitationSnapshot)).scalars().all()
    assert len(snaps) == 1
    assert snaps[0].paper_id == paper.id
    assert snaps[0].citation_count == 100
    assert snaps[0].observed_on == date(2026, 8, 2)
    assert state.papers_refreshed == 1
    assert state.status == "idle"


def test_refresh_is_idempotent_within_a_day(db_session):
    _paper(db_session, "s2-2", "Twice paper")

    refresh_citations(
        db_session,
        FakeClient({"s2-2": CitationObservation("s2-2", 100, None)}),
        now=datetime(2026, 8, 2, 9, 0),
    )
    # A different count on the second run of the same day: if the job wrongly updated
    # in place, the stored count would become 555. Append-only means it stays 100.
    state = refresh_citations(
        db_session,
        FakeClient({"s2-2": CitationObservation("s2-2", 555, None)}),
        now=datetime(2026, 8, 2, 21, 0),
    )

    snaps = db_session.execute(select(CitationSnapshot)).scalars().all()
    assert len(snaps) == 1
    assert snaps[0].citation_count == 100
    assert state.papers_refreshed == 0


def test_refresh_flags_a_decrease_as_anomalous_without_clamping(db_session):
    _paper(db_session, "s2-3", "Merged paper")

    refresh_citations(
        db_session,
        FakeClient({"s2-3": CitationObservation("s2-3", 240, None)}),
        now=datetime(2026, 8, 1, 9, 0),
    )
    state = refresh_citations(
        db_session,
        FakeClient({"s2-3": CitationObservation("s2-3", 190, None)}),
        now=datetime(2026, 8, 2, 9, 0),
    )

    snaps = (
        db_session.execute(select(CitationSnapshot).order_by(CitationSnapshot.observed_at))
        .scalars()
        .all()
    )
    # Stored at its real value, not clamped up to the previous 240.
    assert [s.citation_count for s in snaps] == [240, 190]
    assert snaps[1].is_anomalous is True
    assert snaps[0].is_anomalous is False
    assert state.anomalies_detected == 1


def test_refresh_marks_papers_without_provider_id_as_unrefreshable(db_session):
    paper = Paper(title="No provider id")
    db_session.add(paper)
    db_session.flush()
    client = FakeClient({})

    refresh_citations(db_session, client, now=datetime(2026, 8, 2, 9, 0))

    cache = db_session.execute(
        select(CitationVelocityCache).where(CitationVelocityCache.paper_id == paper.id)
    ).scalar_one()
    assert cache.refresh_status == "no_provider_id"
    assert db_session.execute(select(CitationSnapshot)).scalars().all() == []
    # Never sent to the provider at all.
    assert client.calls == []


def test_refresh_marks_papers_the_provider_dropped_as_gone(db_session):
    paper = _paper(db_session, "s2-gone", "Withdrawn from provider")

    refresh_citations(db_session, FakeClient({}), now=datetime(2026, 8, 2, 9, 0))

    cache = db_session.execute(
        select(CitationVelocityCache).where(CitationVelocityCache.paper_id == paper.id)
    ).scalar_one()
    assert cache.refresh_status == "gone"


def test_refresh_records_rate_limit_and_marks_run_partial(db_session):
    _paper(db_session, "s2-4", "Rate limited paper")
    client = FakeClient({}, error=CitationProviderError("429", status_code=429))

    state = refresh_citations(db_session, client, now=datetime(2026, 8, 2, 9, 0))

    assert state.rate_limit_events == 1
    assert state.status == "partial"
    assert state.papers_failed == 1
    assert db_session.execute(select(CitationSnapshot)).scalars().all() == []


def test_one_failing_batch_does_not_abort_the_rest_of_the_run(db_session):
    for i in range(4):
        _paper(db_session, f"s2-f{i}", f"Paper {i}")

    class FailFirstBatch:
        def __init__(self):
            self.calls = []

        def fetch_batch(self, ids):
            self.calls.append(list(ids))
            if len(self.calls) == 1:
                raise CitationProviderError("boom", status_code=500)
            return {i: CitationObservation(i, 5, None) for i in ids}

    client = FailFirstBatch()
    state = refresh_citations(db_session, client, now=datetime(2026, 8, 2, 9, 0), batch_size=2)

    # First batch of 2 failed; second batch of 2 still collected.
    assert len(client.calls) == 2
    assert state.papers_failed == 2
    assert state.papers_refreshed == 2
    assert state.status == "partial"


def test_refresh_batches_requests(db_session):
    for i in range(5):
        _paper(db_session, f"s2-b{i}", f"Batch paper {i}")
    client = FakeClient({f"s2-b{i}": CitationObservation(f"s2-b{i}", i, None) for i in range(5)})

    refresh_citations(db_session, client, now=datetime(2026, 8, 2, 9, 0), batch_size=2)

    assert [len(c) for c in client.calls] == [2, 2, 1]


def test_refresh_reuses_the_single_state_row(db_session):
    _paper(db_session, "s2-5", "State paper")
    client = FakeClient({"s2-5": CitationObservation("s2-5", 1, None)})

    refresh_citations(db_session, client, now=datetime(2026, 8, 1, 9, 0))
    refresh_citations(db_session, client, now=datetime(2026, 8, 2, 9, 0))

    states = db_session.execute(select(CitationRefreshState)).scalars().all()
    assert len(states) == 1
