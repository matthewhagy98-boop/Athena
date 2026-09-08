from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from citations.models import CitationSnapshot, CitationVelocityCache
from evidence_engine.db.models import Paper, PaperTopic

MIN_SPAN_DAYS = 14
MAX_LOOKBACK_DAYS = 90
MIN_COHORT_SIZE = 10
BAND_WIDTH_YEARS = 4


@dataclass(frozen=True)
class VelocityResult:
    status: str
    velocity_per_30d: Decimal | None
    window_start_observed_at: datetime | None
    window_end_observed_at: datetime | None
    observation_count: int
    first_observed_at: datetime | None
    anomaly_count: int


def _insufficient(ordered: list[CitationSnapshot]) -> VelocityResult:
    return VelocityResult(
        status="insufficient_history",
        velocity_per_30d=None,
        window_start_observed_at=None,
        window_end_observed_at=None,
        observation_count=len(ordered),
        first_observed_at=ordered[0].observed_at if ordered else None,
        anomaly_count=sum(1 for s in ordered if s.is_anomalous),
    )


def compute_velocity(snapshots: list[CitationSnapshot]) -> VelocityResult:
    """Derive citations-per-30-days from one paper's snapshots. Pure; no DB access.

    Requires two observations at least MIN_SPAN_DAYS apart with no provider merge
    between them. Below that threshold no number is produced -- an unsupported
    velocity is worse than none.
    """
    ordered = sorted(snapshots, key=lambda s: s.observed_at)
    anomaly_count = sum(1 for s in ordered if s.is_anomalous)
    if len(ordered) < 2:
        return _insufficient(ordered)

    # An anomalous snapshot marks a provider record merge. A pair may not span one,
    # because the drop is an artifact rather than real citation history. Index i may
    # itself be anomalous: the post-merge count is a valid new baseline.
    anomalous_positions = {i for i, s in enumerate(ordered) if s.is_anomalous}

    best: tuple[int, int] | None = None
    for j in range(len(ordered) - 1, -1, -1):
        for i in range(j):
            if ordered[j].citation_count < ordered[i].citation_count:
                continue
            span_days = (ordered[j].observed_at - ordered[i].observed_at).total_seconds() / 86400
            if span_days < MIN_SPAN_DAYS or span_days > MAX_LOOKBACK_DAYS:
                continue
            if any(pos in anomalous_positions for pos in range(i + 1, j + 1)):
                continue
            best = (i, j)
            break  # i ascends, so the first hit is the widest start for this end.
        if best:
            break  # j descends, so the first hit is the most recent end.

    if best is None:
        return _insufficient(ordered)

    i, j = best
    # span_days is guaranteed >= MIN_SPAN_DAYS by the filter above, so no division
    # by zero is reachable. Decimal throughout, and rounded exactly once, at the end.
    span_days = Decimal((ordered[j].observed_at - ordered[i].observed_at).total_seconds()) / Decimal(86400)
    delta = Decimal(ordered[j].citation_count - ordered[i].citation_count)
    velocity = (delta / span_days * Decimal(30)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return VelocityResult(
        status="ready",
        velocity_per_30d=velocity,
        window_start_observed_at=ordered[i].observed_at,
        window_end_observed_at=ordered[j].observed_at,
        observation_count=len(ordered),
        first_observed_at=ordered[0].observed_at,
        anomaly_count=anomaly_count,
    )


def _cohort_key(paper: Paper | None, topic_id) -> str | None:
    # Fixed 4-year bands anchored on years divisible by 4, so membership is symmetric
    # between runs. A sliding +/-2-year window would put A in B's cohort but not
    # always B in A's.
    if paper is None or paper.pub_date is None or topic_id is None:
        return None
    band = (paper.pub_date.year // BAND_WIDTH_YEARS) * BAND_WIDTH_YEARS
    return f"{topic_id}:{band}"


def recompute_all(session: Session, now: datetime | None = None) -> int:
    """Recompute every paper's velocity, then assign percentiles within cohorts."""
    now = now or datetime.utcnow()

    snapshots_by_paper: dict = {}
    for snap in session.execute(select(CitationSnapshot)).scalars().all():
        snapshots_by_paper.setdefault(snap.paper_id, []).append(snap)

    caches: dict = {}
    for cache in session.execute(select(CitationVelocityCache)).scalars().all():
        caches[cache.paper_id] = cache

    written = 0
    for paper_id, snaps in snapshots_by_paper.items():
        result = compute_velocity(snaps)
        cache = caches.get(paper_id)
        if cache is None:
            cache = CitationVelocityCache(paper_id=paper_id)
            session.add(cache)
            caches[paper_id] = cache

        paper = session.get(Paper, paper_id)
        # Ordered so a multi-topic paper always picks the same topic across runs --
        # without an ORDER BY, Postgres is free to return a different row of an
        # unordered `.limit(1)` query on different executions, which would make the
        # cohort (and thus the percentile) jump with no underlying data change.
        topic_link = session.execute(
            select(PaperTopic)
            .where(PaperTopic.paper_id == paper_id)
            .order_by(PaperTopic.topic_id)
            .limit(1)
        ).scalar_one_or_none()

        cache.status = result.status
        cache.velocity_per_30d = result.velocity_per_30d
        cache.window_start_observed_at = result.window_start_observed_at
        cache.window_end_observed_at = result.window_end_observed_at
        cache.observation_count = result.observation_count
        cache.first_observed_at = result.first_observed_at
        cache.anomaly_count = result.anomaly_count
        cache.cohort_key = _cohort_key(paper, topic_link.topic_id if topic_link else None)
        cache.computed_at = now
        # Cleared here and re-assigned below, so a shrinking cohort cannot leave a
        # stale percentile behind.
        cache.percentile = None
        cache.cohort_size = 0
        written += 1

    # A cache row whose snapshots have all disappeared -- via paper deletion cascade,
    # or the retention job down-sampling history -- must not keep claiming "ready".
    # Without this, a stale row survives every later run (it is not in
    # snapshots_by_paper, so the loop above never touches it) and keeps polluting
    # its cohort with a velocity that has no underlying observations.
    for paper_id, cache in caches.items():
        if paper_id in snapshots_by_paper:
            continue
        cache.status = "insufficient_history"
        cache.velocity_per_30d = None
        cache.window_start_observed_at = None
        cache.window_end_observed_at = None
        cache.observation_count = 0
        cache.first_observed_at = None
        cache.anomaly_count = 0
        cache.cohort_key = None
        cache.percentile = None
        cache.cohort_size = 0
        cache.computed_at = now
    session.flush()

    ready_by_cohort: dict = {}
    for cache in caches.values():
        if cache.status == "ready" and cache.cohort_key:
            ready_by_cohort.setdefault(cache.cohort_key, []).append(cache)

    for members in ready_by_cohort.values():
        size = len(members)
        for cache in members:
            cache.cohort_size = size
            if size < MIN_COHORT_SIZE:
                continue
            rank = sum(1 for other in members if other.velocity_per_30d < cache.velocity_per_30d)
            raw = Decimal(100 * rank) / Decimal(size)
            pct = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            # Clamped to 1..99: a cohort this small cannot support "0th" or "100th",
            # both of which imply a certainty the data does not have.
            cache.percentile = max(1, min(99, pct))
    session.flush()
    return written
