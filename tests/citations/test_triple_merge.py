from datetime import datetime, timedelta

from sqlalchemy import select

from citations.models import CitationSnapshot
from citations.provider import CitationObservation
from citations.refresh import refresh_citations
from evidence_engine.db.models import Paper


class FakeClient:
    def __init__(self, responses):
        self.responses = responses

    def fetch_batch(self, ids):
        return {i: self.responses[i] for i in ids if i in self.responses}


def test_three_merges_do_not_accumulate_false_flags(db_session):
    # Guards both directions at once over a >1-year span. Under-flagging brings back
    # phantom velocity; over-flagging freezes velocity on stale data. Each merge's
    # recovery must be judged against its own pre-drop count, and genuine growth
    # between cycles must stay unflagged.
    paper = Paper(title="Three merge cycles", semantic_scholar_id="s2-triple")
    db_session.add(paper)
    db_session.flush()

    base = datetime(2026, 1, 1, 9, 0)
    # Each merge is preceded by only a PARTIAL recovery from the previous one, so a
    # paper's all-time peak stays above the level its later merges drop from. That
    # divergence is the whole point: judging a recovery against the all-time max
    # instead of its own merge's baseline lets the later bounce escape detection.
    # A series that only ever grows before each merge cannot detect that bug.
    series = [
        (0, 1000),
        (30, 700),  # merge 1, dropping from an all-time peak of 1000
        (60, 850),  # partial recovery only -- still below 1000, so not a phantom tail
        (150, 900),  # real growth; merge 1 is now outside the 90d window
        (180, 600),  # merge 2, dropping from 900 while the all-time peak is still 1000
        (200, 900),  # merge-2 bounce back to ITS pre-drop count of 900, not to 1000
    ]

    for day, count in series:
        refresh_citations(
            db_session,
            FakeClient({"s2-triple": CitationObservation("s2-triple", count, None)}),
            now=base + timedelta(days=day),
        )

    snaps = (
        db_session.execute(select(CitationSnapshot).order_by(CitationSnapshot.observed_at))
        .scalars()
        .all()
    )
    flags = {s.observed_at: s.is_anomalous for s in snaps}

    # Every genuine drop is flagged.
    for day in (30, 180):
        assert flags[base + timedelta(days=day)] is True, f"day {day} merge not flagged"

    # The day-200 bounce returns to merge 2's own pre-drop count (900) while staying
    # below the paper's all-time peak (1000). Judged against the all-time max it
    # would slip through unflagged and compute_velocity would read the 600 -> 900
    # jump as real growth. This assertion is what fails if that regresses.
    assert flags[base + timedelta(days=200)] is True, "merge-2 recovery not flagged"

    # A partial recovery that never reaches its own merge's baseline is real growth,
    # and growth after a merge ages out of the window must not stay poisoned.
    for day in (60, 150):
        assert flags[base + timedelta(days=day)] is False, f"day {day} wrongly flagged"
