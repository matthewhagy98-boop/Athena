from datetime import datetime, timedelta
from decimal import Decimal

from citations.models import CitationSnapshot, CitationVelocityCache
from citations.read import RECENT_COUNTS_LIMIT, get_paper_velocities
from evidence_engine.db.models import Paper


def _paper(db_session, title):
    paper = Paper(title=title)
    db_session.add(paper)
    db_session.flush()
    return paper


def _snaps(db_session, paper_id, counts, start=datetime(2026, 6, 1)):
    for index, count in enumerate(counts):
        moment = start + timedelta(days=7 * index)
        db_session.add(
            CitationSnapshot(
                paper_id=paper_id,
                observed_at=moment,
                observed_on=moment.date(),
                citation_count=count,
            )
        )
    db_session.flush()


def _ready_cache(db_session, paper_id):
    db_session.add(
        CitationVelocityCache(
            paper_id=paper_id, status="ready", velocity_per_30d=Decimal("10.00")
        )
    )
    db_session.flush()


def test_recent_counts_are_returned_oldest_first(db_session):
    paper = _paper(db_session, "Series paper")
    _snaps(db_session, paper.id, [100, 104, 109, 112])
    _ready_cache(db_session, paper.id)

    block = get_paper_velocities(db_session, [paper.id])[paper.id]

    # Ascending by observation date: a sparkline consumes left-to-right.
    assert block["recent_counts"] == [100, 104, 109, 112]


def test_recent_counts_are_capped_and_keep_the_newest(db_session):
    paper = _paper(db_session, "Long series paper")
    counts = list(range(1, RECENT_COUNTS_LIMIT + 6))  # more than the cap
    _snaps(db_session, paper.id, counts)
    _ready_cache(db_session, paper.id)

    block = get_paper_velocities(db_session, [paper.id])[paper.id]

    assert len(block["recent_counts"]) == RECENT_COUNTS_LIMIT
    # The cap must drop the OLDEST points, not the newest -- a sparkline showing a
    # stale window would misrepresent the current trend.
    assert block["recent_counts"][-1] == counts[-1]
    assert block["recent_counts"] == counts[-RECENT_COUNTS_LIMIT:]


def test_paper_without_snapshots_has_an_empty_series(db_session):
    paper = _paper(db_session, "No snapshots")
    _ready_cache(db_session, paper.id)

    block = get_paper_velocities(db_session, [paper.id])[paper.id]

    assert block["recent_counts"] == []


def test_empty_block_carries_an_empty_series(db_session):
    # A paper with no cache row at all -- currently every paper.
    paper = _paper(db_session, "No cache row")

    block = get_paper_velocities(db_session, [paper.id])[paper.id]

    assert block["recent_counts"] == []


def test_series_are_not_cross_contaminated_between_papers(db_session):
    first = _paper(db_session, "First paper")
    second = _paper(db_session, "Second paper")
    _snaps(db_session, first.id, [1, 2, 3])
    _snaps(db_session, second.id, [50, 60, 70])
    _ready_cache(db_session, first.id)
    _ready_cache(db_session, second.id)

    result = get_paper_velocities(db_session, [first.id, second.id])

    assert result[first.id]["recent_counts"] == [1, 2, 3]
    assert result[second.id]["recent_counts"] == [50, 60, 70]


def test_series_query_is_batched_not_per_paper(db_session):
    """One query for all papers' snapshots, not one per paper.

    The search page requests up to 50 papers at once; a per-paper query here would
    turn one batched endpoint into 50 round trips, which is the whole reason the
    velocity endpoint is batched in the first place.
    """
    from sqlalchemy import event

    papers = [_paper(db_session, f"Batch paper {i}") for i in range(5)]
    for paper in papers:
        _snaps(db_session, paper.id, [1, 2, 3])
        _ready_cache(db_session, paper.id)

    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "citation_snapshots" in statement:
            statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", record)
    try:
        get_paper_velocities(db_session, [p.id for p in papers])
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", record)

    assert len(statements) == 1, f"expected 1 snapshot query, got {len(statements)}"
