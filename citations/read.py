import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from citations.models import CitationSnapshot, CitationVelocityCache
from evidence_engine.db.models import Paper


def _iso(value) -> str | None:
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


def _empty_block(is_retracted: bool) -> dict:
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
    }


def get_paper_velocities(session: Session, paper_ids: list[uuid.UUID]) -> dict:
    """One block per requested id. Ids with no cache row are included, not omitted --
    the caller keys off what it asked for, and a missing key reads as a bug."""
    if not paper_ids:
        return {}

    retracted = {
        row.id: bool(row.is_retracted)
        for row in session.execute(select(Paper).where(Paper.id.in_(paper_ids))).scalars().all()
    }
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
            out[paper_id] = _empty_block(is_retracted)
            continue
        out[paper_id] = {
            "status": cache.status,
            # float(), not Decimal: this is serialized straight to JSON.
            "velocity_per_30d": float(cache.velocity_per_30d)
            if cache.velocity_per_30d is not None
            else None,
            "window_start_observed_at": _iso(cache.window_start_observed_at),
            "window_end_observed_at": _iso(cache.window_end_observed_at),
            "observation_count": cache.observation_count,
            "first_observed_at": _iso(cache.first_observed_at),
            "percentile": cache.percentile,
            "cohort_size": cache.cohort_size,
            "is_retracted": is_retracted,
            "computed_at": _iso(cache.computed_at),
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
        "first_observed_at": _iso(snapshots[0].observed_at) if snapshots else None,
        "source": snapshots[0].source if snapshots else "semantic_scholar",
    }
