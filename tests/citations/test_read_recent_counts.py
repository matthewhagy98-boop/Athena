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


def _snaps(db_session, paper_id, counts, start=datetime(2026, 6, 1), start_day=0, anomalous=False):
    """start_day is a literal day offset from `start`, so callers can interleave runs."""
    for index, count in enumerate(counts):
        moment = start + timedelta(days=start_day + 7 * index)
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


def test_the_series_query_fetches_a_bounded_number_of_rows(db_session):
    """Bounded in SQL, not sliced in Python.

    test_series_query_is_batched_not_per_paper counts STATEMENTS, so it cannot tell a
    bounded query from one that selects every snapshot ever recorded and throws most of
    them away. That distinction is the whole point: at a daily cadence a 50-row search
    page would fetch tens of thousands of rows after a year or two, on the hottest read
    path, with nothing to notice.
    """
    from sqlalchemy import event

    paper = _paper(db_session, "Deep history")
    _snaps(db_session, paper.id, list(range(1, 201)))  # 200 observations
    _ready_cache(db_session, paper.id)

    fetched: list[int] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "citation_snapshots" in statement:
            fetched.append(statement.lower().count("row_number"))

    event.listen(db_session.get_bind(), "before_cursor_execute", record)
    try:
        blocks = get_paper_velocities(db_session, [paper.id])
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", record)

    # The returned slice being 12 is necessary but not sufficient -- Python slicing gives
    # that too. The query itself must carry the window.
    assert len(blocks[paper.id]["recent_counts"]) == RECENT_COUNTS_LIMIT
    assert fetched and fetched[0] >= 1, "snapshot query does not bound rows in SQL"


def test_the_series_is_truncated_at_a_provider_record_merge(db_session):
    """An anomalous row marks where a provider record merge was detected.

    velocity.py treats that post-merge count as a valid new baseline, which means every
    count before it belongs to a different record and is not comparable with what follows.

    Filtering the flagged row OUT is not enough, and was the first attempt at this fix:
    it removes the marker and leaves the discontinuity, so the series still plunges
    (100, 104, 109, 15, 19) and the sparkline still draws a cliff that is a bookkeeping
    artifact rather than citation history -- beside a figure engineered to exclude that
    very cliff. The series must start at the merge.
    """
    paper = _paper(db_session, "Merged records")
    _snaps(db_session, paper.id, [100, 104, 109])          # days 0, 7, 14
    _snaps(db_session, paper.id, [12], start_day=21, anomalous=True)  # day 21, the merge
    _snaps(db_session, paper.id, [15, 19], start_day=28)    # days 28, 35
    _ready_cache(db_session, paper.id)

    counts = get_paper_velocities(db_session, [paper.id])[paper.id]["recent_counts"]

    # Starts AT the anomalous observation: it is the first count on the new baseline.
    assert counts == [12, 15, 19]
    assert 109 not in counts, "pre-merge counts belong to a different record"


def test_an_empty_block_still_carries_the_history_that_exists(db_session):
    """insufficient_history and no-history-at-all are different facts.

    Every paper takes this branch during cold start, so hardcoding [] here would discard
    the series the query just fetched and make the field mean "no data" in one branch and
    "no velocity" in another.
    """
    paper = _paper(db_session, "Uncached but observed")
    _snaps(db_session, paper.id, [7, 8, 9])
    # deliberately no cache row

    block = get_paper_velocities(db_session, [paper.id])[paper.id]

    assert block["status"] == "insufficient_history"
    assert block["recent_counts"] == [7, 8, 9]


def test_a_paper_with_no_merge_keeps_its_whole_history(db_session):
    """The truncation is an outer join, so a clean paper must be unaffected by it."""
    paper = _paper(db_session, "Never merged")
    _snaps(db_session, paper.id, [10, 11, 12, 13])
    _ready_cache(db_session, paper.id)

    counts = get_paper_velocities(db_session, [paper.id])[paper.id]["recent_counts"]

    assert counts == [10, 11, 12, 13]


def test_the_series_truncates_at_the_most_recent_merge_not_the_first(db_session):
    """Two merges: only history since the latest one shares a baseline.

    Truncating at the earliest anomaly would splice two incompatible records together
    again, which is the defect this rule exists to prevent.
    """
    paper = _paper(db_session, "Merged twice")
    _snaps(db_session, paper.id, [500, 510])                       # days 0, 7
    _snaps(db_session, paper.id, [50], start_day=14, anomalous=True)
    _snaps(db_session, paper.id, [55], start_day=21)
    _snaps(db_session, paper.id, [8], start_day=28, anomalous=True)
    _snaps(db_session, paper.id, [9], start_day=35)
    _ready_cache(db_session, paper.id)

    counts = get_paper_velocities(db_session, [paper.id])[paper.id]["recent_counts"]

    assert counts == [8, 9]
    assert 55 not in counts, "truncated at the first merge instead of the most recent"
