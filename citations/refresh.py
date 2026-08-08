import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from citations.models import CitationRefreshState, CitationSnapshot, CitationVelocityCache
from citations.provider import CitationProviderError
from citations.velocity import MAX_LOOKBACK_DAYS as ANOMALY_RECOVERY_LOOKBACK_DAYS
from evidence_engine.db.models import Paper

logger = logging.getLogger(__name__)

JOB_NAME = "citation_refresh"


def _get_or_create_state(session: Session) -> CitationRefreshState:
    state = session.execute(
        select(CitationRefreshState).where(CitationRefreshState.job_name == JOB_NAME)
    ).scalar_one_or_none()
    if state is None:
        state = CitationRefreshState(job_name=JOB_NAME)
        session.add(state)
        session.flush()
    return state


def _get_or_create_cache(session: Session, paper_id) -> CitationVelocityCache:
    cache = session.execute(
        select(CitationVelocityCache).where(CitationVelocityCache.paper_id == paper_id)
    ).scalar_one_or_none()
    if cache is None:
        cache = CitationVelocityCache(paper_id=paper_id)
        session.add(cache)
        session.flush()
    return cache


def _latest_snapshot(session: Session, paper_id) -> CitationSnapshot | None:
    return session.execute(
        select(CitationSnapshot)
        .where(CitationSnapshot.paper_id == paper_id)
        .order_by(CitationSnapshot.observed_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _is_genuine_decrease(session: Session, paper_id, snapshot: CitationSnapshot) -> bool:
    """True if `snapshot` itself dropped below the count immediately before it.

    Distinguishes an actual provider-merge event from a recovery-tail snapshot
    that was only flagged because it climbed back over an earlier merge's
    high-water mark. Recovery-tail snapshots have a count >= their predecessor
    (they are the "growth" side of the artifact), so this is false for them.
    """
    prior = session.execute(
        select(CitationSnapshot)
        .where(
            CitationSnapshot.paper_id == paper_id,
            CitationSnapshot.observed_at < snapshot.observed_at,
        )
        .order_by(CitationSnapshot.observed_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return prior is not None and snapshot.citation_count < prior.citation_count


def _recent_anomalous_snapshot(session: Session, paper_id, now: datetime) -> CitationSnapshot | None:
    """Most recent *genuine merge/drop* within the recovery lookback window.

    Only a snapshot that is itself a decrease can anchor the window. A
    recovery-tail snapshot (flagged solely because it climbed back over the
    pre-drop high) must not qualify -- if it did, each recovery-tail flag would
    re-anchor the window on itself, and continued real growth would keep
    re-triggering the phantom-recovery check indefinitely, long after the
    original merge has aged out of the lookback period.
    """
    cutoff = now - timedelta(days=ANOMALY_RECOVERY_LOOKBACK_DAYS)
    candidates = (
        session.execute(
            select(CitationSnapshot)
            .where(
                CitationSnapshot.paper_id == paper_id,
                CitationSnapshot.is_anomalous.is_(True),
                CitationSnapshot.observed_at >= cutoff,
            )
            .order_by(CitationSnapshot.observed_at.desc())
        )
        .scalars()
        .all()
    )
    for candidate in candidates:
        if _is_genuine_decrease(session, paper_id, candidate):
            return candidate
    return None


def _pre_anomaly_high_water_mark(session: Session, paper_id, anomaly_observed_at: datetime) -> int | None:
    """Highest citation_count observed for this paper strictly before an anomaly."""
    return session.execute(
        select(func.max(CitationSnapshot.citation_count)).where(
            CitationSnapshot.paper_id == paper_id,
            CitationSnapshot.observed_at < anomaly_observed_at,
        )
    ).scalar_one()


def _is_phantom_recovery(session: Session, paper_id, new_count: int, previous, now: datetime) -> bool:
    """Detect a count climbing back to (or past) its pre-drop high after a merge.

    A provider merge that is later reverted (e.g. 240 -> 190 -> 240) is not real
    growth: the paper never actually lost or regained citations, the provider's
    bookkeeping did. Spec Sec 14.3 only flags decreases, which leaves this
    compensating increase unflagged and lets compute_velocity report a large
    velocity for a paper with zero real growth. So: whenever an anomalous
    snapshot exists within the recovery lookback window, and the new count has
    climbed back to or past the high-water mark that stood immediately before
    that anomaly, flag the new snapshot too -- it is the tail of the same
    artifact, not new evidence.

    The lookup is always time-bounded (never taken unconditionally from
    `previous`), so a flag cannot outlive ANOMALY_RECOVERY_LOOKBACK_DAYS: once
    the most recent anomalous snapshot falls outside the window, subsequent
    growth is treated as real again, even if `previous` itself was flagged.
    """
    anomaly = _recent_anomalous_snapshot(session, paper_id, now)
    if anomaly is None:
        return False
    pre_anomaly_high = _pre_anomaly_high_water_mark(session, paper_id, anomaly.observed_at)
    return pre_anomaly_high is not None and new_count >= pre_anomaly_high


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def refresh_citations(
    session: Session, client, now: datetime | None = None, batch_size: int = 100
) -> CitationRefreshState:
    """Write at most one snapshot per paper per day. Append-only; never updates a snapshot."""
    now = now or datetime.utcnow()
    observed_on = now.date()

    state = _get_or_create_state(session)
    state.status = "running"
    state.started_at = now
    state.papers_refreshed = 0
    state.papers_failed = 0
    state.batches_attempted = 0
    state.rate_limit_events = 0
    state.anomalies_detected = 0
    state.last_error = None
    session.flush()

    try:
        papers = session.execute(select(Paper)).scalars().all()

        # Papers with no provider id can never be refreshed. Record that once and
        # skip them, rather than counting them as failures on every subsequent run.
        trackable = []
        for paper in papers:
            if not paper.semantic_scholar_id:
                _get_or_create_cache(session, paper.id).refresh_status = "no_provider_id"
            else:
                trackable.append(paper)
        session.flush()

        by_provider_id = {p.semantic_scholar_id: p for p in trackable}
        had_failure = False

        for chunk in _chunks(list(by_provider_id.keys()), batch_size):
            state.batches_attempted += 1
            try:
                observations = client.fetch_batch(chunk)
            except CitationProviderError as exc:
                # One bad batch must not cost the whole day's collection.
                had_failure = True
                if exc.status_code == 429:
                    state.rate_limit_events += 1
                state.papers_failed += len(chunk)
                state.last_error = str(exc)[:2000]
                logger.warning("Citation batch failed (%s); continuing with next batch", exc)
                continue
            except Exception as exc:  # noqa: BLE001 - one bad batch must not abort the run
                had_failure = True
                state.papers_failed += len(chunk)
                state.last_error = str(exc)[:2000]
                logger.exception("Unexpected citation batch failure; continuing")
                continue

            for provider_id in chunk:
                paper = by_provider_id[provider_id]
                observation = observations.get(provider_id)
                cache = _get_or_create_cache(session, paper.id)

                if observation is None:
                    # Requested but not returned: the provider no longer knows this id.
                    cache.refresh_status = "gone"
                    continue
                cache.refresh_status = "active"

                existing = session.execute(
                    select(CitationSnapshot).where(
                        CitationSnapshot.paper_id == paper.id,
                        CitationSnapshot.observed_on == observed_on,
                        CitationSnapshot.source == "semantic_scholar",
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    # Already observed today. Append-only: the existing row stands.
                    continue

                previous = _latest_snapshot(session, paper.id)
                is_decrease = (
                    previous is not None and observation.citation_count < previous.citation_count
                )
                # `or` short-circuits, so the phantom-recovery lookup only runs when
                # this snapshot isn't already flagged as a plain decrease.
                is_anomalous = is_decrease or _is_phantom_recovery(
                    session, paper.id, observation.citation_count, previous, now
                )
                if is_anomalous:
                    state.anomalies_detected += 1

                session.add(
                    CitationSnapshot(
                        paper_id=paper.id,
                        observed_at=now,
                        observed_on=observed_on,
                        # Stored exactly as reported. Clamping a decrease would destroy
                        # the evidence that a provider record merge happened.
                        citation_count=observation.citation_count,
                        influential_citation_count=observation.influential_citation_count,
                        is_anomalous=is_anomalous,
                    )
                )
                state.papers_refreshed += 1
            session.flush()

        state.status = "partial" if had_failure else "idle"
        state.completed_at = now
        session.flush()
        return state
    except Exception as exc:
        # Anything that escapes the per-batch handler above (e.g. a bug in the
        # anomaly-detection helpers, which run outside that try/except) must not
        # leave the state row stuck on "running" forever -- that reads identically
        # to "today's run never started", which hides a real crash from operators.
        # Commit explicitly: the caller (citations/runner.py) commits only after
        # this function returns, so without a commit here a re-raised exception
        # would leave this state change as an uncommitted, and likely rolled-back,
        # write.
        state.status = "failed"
        state.last_error = str(exc)[:2000]
        state.completed_at = now
        session.commit()
        raise
