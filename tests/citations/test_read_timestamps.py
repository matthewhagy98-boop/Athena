from datetime import datetime
from decimal import Decimal

from citations.models import CitationSnapshot, CitationVelocityCache
from citations.read import get_citation_history, get_paper_velocities
from evidence_engine.db.models import Paper


def _paper(db_session, title):
    paper = Paper(title=title)
    db_session.add(paper)
    db_session.flush()
    return paper


def test_velocity_timestamps_carry_an_explicit_utc_suffix(db_session):
    """Naive timestamps would be parsed as local time by the browser.

    Every timestamp in this package is naive UTC. JavaScript's Date parses an
    offset-less date-time as LOCAL, so without the suffix the frontend shifts each
    value by the viewer's UTC offset -- enough to flip the "as of N days ago" label
    or cross the 3-day aging / 21-day suppression thresholds west of UTC.
    """
    paper = _paper(db_session, "Timestamped paper")
    db_session.add(
        CitationVelocityCache(
            paper_id=paper.id,
            status="ready",
            velocity_per_30d=Decimal("10.00"),
            window_start_observed_at=datetime(2026, 7, 3, 4, 20, 11),
            window_end_observed_at=datetime(2026, 8, 2, 4, 18, 52),
            first_observed_at=datetime(2026, 6, 28, 4, 15, 2),
            computed_at=datetime(2026, 8, 2, 5, 0, 0),
        )
    )
    db_session.flush()

    block = get_paper_velocities(db_session, [paper.id])[paper.id]

    for field in (
        "window_start_observed_at",
        "window_end_observed_at",
        "first_observed_at",
        "computed_at",
    ):
        assert block[field].endswith("Z"), f"{field} lacks a UTC suffix: {block[field]}"
    assert block["computed_at"] == "2026-08-02T05:00:00Z"


def test_null_timestamps_stay_null_rather_than_becoming_the_string_z(db_session):
    paper = _paper(db_session, "Unscored paper")

    block = get_paper_velocities(db_session, [paper.id])[paper.id]

    assert block["computed_at"] is None
    assert block["first_observed_at"] is None


def test_history_first_observed_at_carries_the_suffix(db_session):
    paper = _paper(db_session, "History timestamps")
    moment = datetime(2026, 7, 1, 4, 0)
    db_session.add(
        CitationSnapshot(
            paper_id=paper.id,
            observed_at=moment,
            observed_on=moment.date(),
            citation_count=100,
        )
    )
    db_session.flush()

    result = get_citation_history(db_session, paper.id, days=365)

    assert result["first_observed_at"] == "2026-07-01T04:00:00Z"
    # observed_on is a calendar date, not an instant -- it must NOT gain a suffix.
    assert result["observations"][0]["observed_on"] == "2026-07-01"
