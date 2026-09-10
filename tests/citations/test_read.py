import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from citations.models import CitationSnapshot, CitationVelocityCache
from citations.read import get_citation_history, get_paper_velocities
from evidence_engine.db.models import Paper


def _paper(db_session, title="Read paper", retracted=False):
    paper = Paper(title=title, is_retracted=retracted)
    db_session.add(paper)
    db_session.flush()
    return paper


def _snap(db_session, paper_id, day_offset, count, anomalous=False):
    moment = datetime(2026, 6, 1) + timedelta(days=day_offset)
    db_session.add(
        CitationSnapshot(
            paper_id=paper_id,
            observed_at=moment,
            observed_on=moment.date(),
            citation_count=count,
            is_anomalous=anomalous,
        )
    )
    db_session.flush()


def test_returns_a_ready_block_from_the_cache(db_session):
    paper = _paper(db_session)
    db_session.add(
        CitationVelocityCache(
            paper_id=paper.id,
            status="ready",
            velocity_per_30d=Decimal("24.00"),
            observation_count=6,
            percentile=88,
            cohort_size=34,
            computed_at=datetime(2026, 8, 2, 5, 0),
        )
    )
    db_session.flush()

    result = get_paper_velocities(db_session, [paper.id])

    block = result[paper.id]
    assert block["status"] == "ready"
    assert block["velocity_per_30d"] == 24.0
    assert block["percentile"] == 88
    assert block["cohort_size"] == 34
    assert block["is_retracted"] is False


def test_velocity_is_a_float_not_a_decimal(db_session):
    # The endpoint serializes to JSON; a Decimal would raise or stringify.
    paper = _paper(db_session, "Float paper")
    db_session.add(
        CitationVelocityCache(paper_id=paper.id, status="ready", velocity_per_30d=Decimal("3.50"))
    )
    db_session.flush()

    block = get_paper_velocities(db_session, [paper.id])[paper.id]

    assert isinstance(block["velocity_per_30d"], float)


def test_paper_with_no_cache_row_reads_as_insufficient_history(db_session):
    paper = _paper(db_session, "Untracked paper")

    block = get_paper_velocities(db_session, [paper.id])[paper.id]

    assert block["status"] == "insufficient_history"
    assert block["velocity_per_30d"] is None
    assert block["observation_count"] == 0
    assert block["first_observed_at"] is None


def test_unknown_paper_id_is_still_present_in_the_map(db_session):
    # The frontend keys off the requested ids; a missing key would look like a bug.
    missing = uuid.uuid4()

    result = get_paper_velocities(db_session, [missing])

    assert result[missing]["status"] == "insufficient_history"


def test_retraction_is_reported_from_the_paper_not_the_cache(db_session):
    paper = _paper(db_session, "Retracted paper", retracted=True)
    db_session.add(CitationVelocityCache(paper_id=paper.id, status="ready", velocity_per_30d=Decimal("5.00")))
    db_session.flush()

    assert get_paper_velocities(db_session, [paper.id])[paper.id]["is_retracted"] is True


def test_history_returns_observations_ascending(db_session):
    paper = _paper(db_session, "History paper")
    for offset, count in ((14, 112), (0, 104), (7, 109)):
        _snap(db_session, paper.id, offset, count)

    result = get_citation_history(db_session, paper.id, days=365)

    assert [o["citation_count"] for o in result["observations"]] == [104, 109, 112]
    assert result["observations"][0]["observed_on"] == date(2026, 6, 1).isoformat()
    assert result["first_observed_at"] is not None
    assert result["source"] == "semantic_scholar"


def test_history_respects_the_days_window(db_session):
    paper = _paper(db_session, "Windowed paper")
    _snap(db_session, paper.id, 0, 100)
    _snap(db_session, paper.id, 400, 200)

    # Anchor the window on the newest observation so the test is not time-dependent.
    result = get_citation_history(db_session, paper.id, days=30)

    assert [o["citation_count"] for o in result["observations"]] == [200]


def test_history_exposes_anomalous_flags(db_session):
    paper = _paper(db_session, "Anomalous history")
    _snap(db_session, paper.id, 0, 240)
    _snap(db_session, paper.id, 20, 190, anomalous=True)

    result = get_citation_history(db_session, paper.id, days=365)

    assert [o["is_anomalous"] for o in result["observations"]] == [False, True]


def test_history_for_a_paper_with_no_snapshots_is_empty_not_an_error(db_session):
    paper = _paper(db_session, "No history")

    result = get_citation_history(db_session, paper.id, days=365)

    assert result["observations"] == []
    assert result["first_observed_at"] is None
