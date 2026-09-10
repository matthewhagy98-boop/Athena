from datetime import date, datetime

from citations.models import CitationSnapshot
from citations.read import get_citation_history
from evidence_engine.db.models import Paper


def test_history_window_anchors_on_newest_observation_not_wall_clock(db_session):
    """A paper whose tracking stopped long ago still renders the history it has.

    This distinguishes the two possible anchorings, which most fixtures cannot:
    both observations are far in the PAST, so a wall-clock anchor (now - days)
    would exclude everything and yield an empty chart, while anchoring on the
    newest observation yields the tail of the series. Fixtures dated in the
    future make the two strategies coincide and prove nothing.
    """
    paper = Paper(title="Tracking stopped years ago")
    db_session.add(paper)
    db_session.flush()

    for moment, count in (
        (datetime(2024, 1, 1, 4, 0), 100),  # outside a 30-day window either way
        (datetime(2024, 2, 1, 4, 0), 150),  # newest: inside a newest-anchored window
    ):
        db_session.add(
            CitationSnapshot(
                paper_id=paper.id,
                observed_at=moment,
                observed_on=moment.date(),
                citation_count=count,
            )
        )
    db_session.flush()

    result = get_citation_history(db_session, paper.id, days=30)

    # Wall-clock anchoring would return [] here. Newest-observation anchoring
    # returns the final point, which is the behavior the design calls for.
    assert [o["citation_count"] for o in result["observations"]] == [150]
    # first_observed_at always reports the true start of tracking, even when the
    # requested window excludes it -- that is what "Tracking since {date}" renders.
    # The Z suffix is required: the browser would otherwise read it as local time.
    assert result["first_observed_at"] == "2024-01-01T04:00:00Z"


def test_history_window_includes_everything_when_days_span_the_series(db_session):
    paper = Paper(title="Full span")
    db_session.add(paper)
    db_session.flush()

    for moment, count in (
        (datetime(2024, 1, 1, 4, 0), 100),
        (datetime(2024, 2, 1, 4, 0), 150),
    ):
        db_session.add(
            CitationSnapshot(
                paper_id=paper.id,
                observed_at=moment,
                observed_on=moment.date(),
                citation_count=count,
            )
        )
    db_session.flush()

    result = get_citation_history(db_session, paper.id, days=365)

    assert [o["citation_count"] for o in result["observations"]] == [100, 150]
    assert result["observations"][0]["observed_on"] == date(2024, 1, 1).isoformat()
