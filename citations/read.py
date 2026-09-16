import uuid
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from citations.models import CitationSnapshot, CitationVelocityCache
from evidence_engine.db.models import Paper

# Trailing observations sent per paper for the badge sparkline. At the job's daily
# cadence this is a few weeks of trend -- enough shape to read, small enough that a
# 50-row search page stays a modest payload.
RECENT_COUNTS_LIMIT = 12


def iso_utc(value) -> str | None:
    """Serialize a UTC timestamp with an explicit Z suffix.

    Every timestamp in this package is naive UTC (the models default to
    datetime.utcnow), and a bare isoformat() emits no offset. JavaScript parses an
    offset-less date-time as LOCAL time, so the frontend would shift each value by
    the viewer's UTC offset -- enough to flip the "as of N days ago" label, or to
    push a computed_at across the 3-day aging or 21-day suppression threshold, for
    anyone west of UTC.
    """
    if value is None:
        return None
    return value.isoformat() + "Z"


def _empty_block(is_retracted: bool, recent_counts: list[int] | None = None) -> dict:
    # A paper the collection job has never reached is indistinguishable, from the
    # reader's point of view, from one with a single observation: neither can
    # produce a velocity. Both read as insufficient_history rather than as an error.
    return {
        "status": "insufficient_history",
        "velocity_per_30d": None,
        "window_start_observed_at": None,
        "window_end_observed_at": None,
        "observation_count": 0,
        "first_observed_at": None,
        "percentile": None,
        "cohort_size": 0,
        "is_retracted": is_retracted,
        "computed_at": None,
        # Carries whatever history exists even though this block means "not enough
        # history to compute a velocity". The two are different questions: a paper can
        # have several observations and still lack a pair the velocity window accepts.
        # The query has already fetched this, so returning [] here would discard data we
        # paid for and make the field mean "no history" in one branch and "no data yet"
        # in another.
        "recent_counts": recent_counts or [],
    }


def _recent_counts_by_paper(session: Session, paper_ids: list[uuid.UUID]) -> dict:
    """Trailing citation counts per paper, oldest first, for the badge sparkline.

    One batched query, not one per paper: the search page asks for up to 50 papers
    at a time, and a per-paper query would turn this endpoint's single round trip
    into 50 -- which is the reason it is batched at all.

    Bounded in SQL, not in Python. Selecting every snapshot and slicing afterwards is
    still one query, but an unbounded one: at a daily cadence a 50-row search page would
    fetch ~18k rows after a year and ~55k after three, to produce 600 integers. The
    row_number() window keeps it to RECENT_COUNTS_LIMIT per paper no matter how long
    collection has been running.

    The series is TRUNCATED at the most recent anomalous snapshot, inclusive, rather than
    having anomalous rows filtered out of it. An anomalous row marks the point where a
    provider record merge was detected, and velocity.py treats that post-merge count as a
    valid new baseline (citations/velocity.py:52-55) -- which means every count before it
    belongs to a different record and is not comparable with what follows.

    Merely dropping the flagged row would remove the marker and leave the discontinuity:
    a series like [100, 104, 109, 15, 19] still plunges, and the sparkline would draw a
    cliff that is a bookkeeping artifact rather than citation history -- beside a figure
    engineered to exclude that very cliff. Truncating yields [15, 19]... starting at the
    anomalous row itself, since that is the first observation on the new baseline.

    A paper with no anomaly keeps its whole (capped) history, via the outer join.

    Ordering is by observed_at within a paper, backed by ix_citation_snapshots_paper_observed.
    Only semantic_scholar writes snapshots today; the unique constraint permits a second
    source per day, which would interleave two series into one line if one is ever added.
    """
    # Per paper, the newest anomalous observation -- the record merge to truncate at.
    last_anomaly = (
        select(
            CitationSnapshot.paper_id.label("pid"),
            func.max(CitationSnapshot.observed_at).label("cutoff"),
        )
        .where(
            CitationSnapshot.paper_id.in_(paper_ids),
            CitationSnapshot.is_anomalous.is_(True),
        )
        .group_by(CitationSnapshot.paper_id)
        .subquery()
    )

    ranked = (
        select(
            CitationSnapshot.paper_id,
            CitationSnapshot.citation_count,
            func.row_number()
            .over(
                partition_by=CitationSnapshot.paper_id,
                order_by=CitationSnapshot.observed_at.desc(),
            )
            .label("rn"),
        )
        .outerjoin(last_anomaly, last_anomaly.c.pid == CitationSnapshot.paper_id)
        .where(
            CitationSnapshot.paper_id.in_(paper_ids),
            or_(
                last_anomaly.c.cutoff.is_(None),
                CitationSnapshot.observed_at >= last_anomaly.c.cutoff,
            ),
        )
        .subquery()
    )

    rows = session.execute(
        select(ranked.c.paper_id, ranked.c.citation_count)
        .where(ranked.c.rn <= RECENT_COUNTS_LIMIT)
        # rn counts backwards from the newest, so descending rn is oldest-first.
        .order_by(ranked.c.paper_id, ranked.c.rn.desc())
    ).all()

    series: dict = {}
    for paper_id, count in rows:
        series.setdefault(paper_id, []).append(count)
    return series


def get_paper_velocities(session: Session, paper_ids: list[uuid.UUID]) -> dict:
    """One block per requested id. Ids with no cache row are included, not omitted --
    the caller keys off what it asked for, and a missing key reads as a bug."""
    if not paper_ids:
        return {}

    retracted = {
        row.id: bool(row.is_retracted)
        for row in session.execute(select(Paper).where(Paper.id.in_(paper_ids))).scalars().all()
    }
    recent_counts = _recent_counts_by_paper(session, paper_ids)
    caches = {
        row.paper_id: row
        for row in session.execute(
            select(CitationVelocityCache).where(CitationVelocityCache.paper_id.in_(paper_ids))
        )
        .scalars()
        .all()
    }

    out: dict = {}
    for paper_id in paper_ids:
        is_retracted = retracted.get(paper_id, False)
        cache = caches.get(paper_id)
        if cache is None:
            out[paper_id] = _empty_block(is_retracted, recent_counts.get(paper_id, []))
            continue
        out[paper_id] = {
            "status": cache.status,
            # float(), not Decimal: this is serialized straight to JSON.
            "velocity_per_30d": float(cache.velocity_per_30d)
            if cache.velocity_per_30d is not None
            else None,
            "window_start_observed_at": iso_utc(cache.window_start_observed_at),
            "window_end_observed_at": iso_utc(cache.window_end_observed_at),
            "observation_count": cache.observation_count,
            "first_observed_at": iso_utc(cache.first_observed_at),
            "percentile": cache.percentile,
            "cohort_size": cache.cohort_size,
            "is_retracted": is_retracted,
            "computed_at": iso_utc(cache.computed_at),
            "recent_counts": recent_counts.get(paper_id, []),
        }
    return out


def get_citation_history(session: Session, paper_id: uuid.UUID, days: int) -> dict:
    """Observations ascending by date, which is what a chart consumes directly."""
    snapshots = (
        session.execute(
            select(CitationSnapshot)
            .where(CitationSnapshot.paper_id == paper_id)
            .order_by(CitationSnapshot.observed_at)
        )
        .scalars()
        .all()
    )

    windowed = snapshots
    if snapshots:
        # Anchor on the newest observation rather than on wall-clock now, so a paper
        # whose tracking stopped still renders the history it has instead of an
        # empty chart.
        cutoff = snapshots[-1].observed_at - timedelta(days=days)
        windowed = [s for s in snapshots if s.observed_at >= cutoff]

    return {
        "paper_id": str(paper_id),
        "observations": [
            {
                "observed_on": s.observed_on.isoformat(),
                "citation_count": s.citation_count,
                "is_anomalous": s.is_anomalous,
            }
            for s in windowed
        ],
        "first_observed_at": iso_utc(snapshots[0].observed_at) if snapshots else None,
        "source": snapshots[0].source if snapshots else "semantic_scholar",
    }
