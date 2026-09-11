import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from citations.models import CitationVelocityCache
from webapp.search import SearchFilters, search_papers

MAX_AGGREGATE_PAPERS = 200
# Below this share of papers having history, a median describes a handful of papers
# while appearing to describe the whole saved search. Report coverage instead.
MIN_COVERAGE_RATIO = 0.25


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _as_uuid(value):
    # Risk: a corrupted/malformed topic_id degrades to "no filter" rather than a
    # clean zero-match, which *broadens* the population to unrelated papers instead
    # of reporting nothing. That is the intended contract (query_params is
    # unvalidated JSONB and may predate any given filter shape), but it is the kind
    # of silent widening a reader would not expect -- hence this note.
    try:
        return uuid.UUID(value) if value else None
    except (ValueError, AttributeError, TypeError):
        return None


def _as_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except (ValueError, AttributeError, TypeError):
        return None


def _week_starts(now: datetime, weeks: int) -> list[datetime]:
    # Monday-anchored week boundaries, oldest first.
    this_week = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return [this_week - timedelta(weeks=offset) for offset in range(weeks - 1, -1, -1)]


def saved_search_velocity(
    session: Session, saved_search, weeks: int, now: datetime | None = None
) -> dict:
    """Median velocity across a saved search's papers, per trailing week boundary.

    Median rather than mean: citation velocities are heavily right-skewed, and one
    landmark paper would otherwise dominate the line. Pure read -- it deliberately
    does NOT update the saved search's last_run_at.
    """
    now = now or datetime.utcnow()
    params = saved_search.query_params or {}
    # query_params is free-form JSONB written by the saved-search creation endpoint,
    # so topic_id/date_from/date_to arrive as strings, not the typed uuid.UUID/date
    # SearchFilters declares. Coerce them, treating a malformed stored value as no
    # filter rather than an error -- query_params is unvalidated and may predate any
    # given filter shape.
    filters = SearchFilters(
        topic_id=_as_uuid(params.get("topic_id")),
        tier=params.get("tier"),
        study_type=params.get("study_type"),
        date_from=_as_date(params.get("date_from")),
        date_to=_as_date(params.get("date_to")),
    )
    page = search_papers(
        session, query=params.get("q"), filters=filters, page=1, page_size=MAX_AGGREGATE_PAPERS
    )
    paper_ids = [row.paper.id for row in page.rows]
    # page.total is the true, unbounded match count; paper_ids is capped at
    # MAX_AGGREGATE_PAPERS. Report both rather than collapsing them, so a search
    # that matches more papers than the cap isn't indistinguishable from one that
    # genuinely matches exactly the cap.
    papers_total = page.total
    papers_examined = len(paper_ids)

    caches = []
    if paper_ids:
        caches = (
            session.execute(
                select(CitationVelocityCache).where(
                    CitationVelocityCache.paper_id.in_(paper_ids),
                    CitationVelocityCache.status == "ready",
                )
            )
            .scalars()
            .all()
        )
    papers_with_history = len(caches)

    computed_at = now.isoformat()
    # Coverage is measured against papers_examined (the ≤ MAX_AGGREGATE_PAPERS
    # papers actually inspected), not papers_total (the true, unbounded match
    # count). Dividing by the true total would systematically under-report
    # coverage for any saved search matching more papers than the cap, so a large
    # search would read "not enough history" indefinitely even when the sampled
    # papers are well covered. Do not "fix" this back to papers_total.
    if papers_examined == 0 or papers_with_history / papers_examined < MIN_COVERAGE_RATIO:
        return {
            "status": "insufficient_coverage",
            "papers_total": papers_total,
            "papers_examined": papers_examined,
            "papers_with_history": papers_with_history,
            "series": [],
            "computed_at": computed_at,
        }

    series = []
    for boundary in _week_starts(now, weeks):
        values = [
            float(c.velocity_per_30d)
            for c in caches
            if c.velocity_per_30d is not None
            and c.window_end_observed_at is not None
            and c.window_end_observed_at <= boundary
        ]
        point = median(values)
        if point is not None:
            series.append(
                {"week_start": boundary.date().isoformat(), "median_velocity_per_30d": point}
            )

    return {
        "status": "ready",
        "papers_total": papers_total,
        "papers_examined": papers_examined,
        "papers_with_history": papers_with_history,
        "series": series,
        "computed_at": computed_at,
    }
