import uuid
from datetime import date, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from citations.models import CitationRefreshState, CitationSnapshot, CitationVelocityCache
from evidence_engine.db.models import Paper


def _paper(db_session, title="Citation paper"):
    paper = Paper(title=title)
    db_session.add(paper)
    db_session.flush()
    return paper


def test_snapshot_round_trip(db_session):
    paper = _paper(db_session)
    snap = CitationSnapshot(
        paper_id=paper.id,
        observed_at=datetime(2026, 8, 2, 12, 0),
        observed_on=date(2026, 8, 2),
        citation_count=132,
        influential_citation_count=9,
    )
    db_session.add(snap)
    db_session.flush()

    stored = db_session.get(CitationSnapshot, snap.id)
    assert stored.citation_count == 132
    assert stored.source == "semantic_scholar"
    assert stored.is_anomalous is False


def test_snapshot_is_unique_per_paper_day_and_source(db_session):
    paper = _paper(db_session, "Dedupe paper")
    for _ in range(2):
        db_session.add(
            CitationSnapshot(
                paper_id=paper.id,
                observed_at=datetime(2026, 8, 2, 12, 0),
                observed_on=date(2026, 8, 2),
                citation_count=10,
            )
        )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_velocity_cache_defaults_to_insufficient_history(db_session):
    paper = _paper(db_session, "Cache paper")
    row = CitationVelocityCache(paper_id=paper.id)
    db_session.add(row)
    db_session.flush()

    assert row.status == "insufficient_history"
    assert row.velocity_per_30d is None
    assert row.observation_count == 0
    assert row.refresh_status == "active"


def test_refresh_state_round_trip(db_session):
    state = CitationRefreshState(job_name="citation_refresh")
    db_session.add(state)
    db_session.flush()

    assert state.status == "idle"
    assert state.papers_refreshed == 0
