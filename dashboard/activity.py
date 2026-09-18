import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from dashboard.models import DashboardJobState, TopicActivitySnapshot
from dashboard.trend import TopicCounts, is_eligible, rank_topics, score_topic
from dashboard.windows import BASELINE_WINDOWS, baseline_windows, window_for
from evidence_engine.db.models import ChangeEvent, ChangeEventType, Topic

JOB_NAME = "activity_snapshot"
RETENTION_DAYS = 180

_TYPE_FIELDS = {
    ChangeEventType.NEW_PAPER: "new_paper",
    ChangeEventType.CONSENSUS_UPDATED: "consensus_updated",
    ChangeEventType.CONTRADICTION_FLAGGED: "contradiction_flagged",
    ChangeEventType.PAPER_RETRACTED: "paper_retracted",
}


def _counts_in_window(session: Session, start: datetime, end: datetime) -> dict:
    """Per-topic counts, broken down by event type, for one half-open window.

    One grouped query for every topic at once rather than a query per topic: the job
    walks nine windows, and per-topic queries would make that O(topics x windows).
    """
    rows = session.execute(
        select(
            ChangeEvent.topic_id,
            ChangeEvent.event_type,
            func.count().label("n"),
        )
        .where(ChangeEvent.detected_at > start, ChangeEvent.detected_at <= end)
        .group_by(ChangeEvent.topic_id, ChangeEvent.event_type)
    ).all()

    counts: dict = {}
    for topic_id, event_type, n in rows:
        bucket = counts.setdefault(
            topic_id,
            {"total": 0, "new_paper": 0, "consensus_updated": 0,
             "contradiction_flagged": 0, "paper_retracted": 0},
        )
        bucket["total"] += n
        field = _TYPE_FIELDS.get(event_type)
        if field is not None:
            bucket[field] += n
    return counts


def _first_event_at(session: Session) -> dict:
    """Earliest event per topic, used to decide how many complete weeks it was tracked."""
    rows = session.execute(
        select(ChangeEvent.topic_id, func.min(ChangeEvent.detected_at)).group_by(
            ChangeEvent.topic_id
        )
    ).all()
    return {topic_id: first for topic_id, first in rows}


def refresh_activity_snapshots(session: Session, as_of: datetime | None = None) -> uuid.UUID:
    """Compute one generation of rankings and publish it. Returns the generation id.

    The write order is the contract with readers (FR-C-010): rows are written under a
    fresh generation id, and only once every row is in does the watermark advance to it.
    A run that dies mid-write leaves the previous generation serving, and its orphaned
    rows are pruned by a later run rather than ever being read.
    """
    as_of = as_of or datetime.utcnow()
    generation = uuid.uuid4()
    current = window_for(as_of, 0)

    state = session.execute(
        select(DashboardJobState).where(DashboardJobState.job_name == JOB_NAME)
    ).scalar_one_or_none()
    if state is None:
        state = DashboardJobState(job_name=JOB_NAME)
        session.add(state)
    state.status = "running"
    state.running_generation_id = generation
    state.started_at = as_of
    session.flush()

    current_counts = _counts_in_window(session, current.start, current.end)
    priors = [_counts_in_window(session, w.start, w.end) for w in baseline_windows(as_of)]
    first_seen = _first_event_at(session)

    scored = []
    for topic_id, bucket in current_counts.items():
        if not is_eligible(bucket["total"]):
            continue
        # How many complete baseline windows the topic actually existed for. A window
        # counts only if the topic's first event predates its start -- otherwise the
        # topic's silence through that window is absence of TRACKING, not absence of
        # activity, and averaging it in as a zero would understate the baseline and
        # inflate the ratio against it.
        #
        # This reaches 8 exactly when the first event predates the earliest baseline
        # window, so no separate "fully tracked" branch is needed: `first <=
        # earliest_baseline_start` implies `first <= w.start` for every window, and the
        # sum is already 8. An earlier draft had that branch; it was dead logic.
        first = first_seen.get(topic_id)
        weeks = sum(1 for w in baseline_windows(as_of) if first is not None and first <= w.start)
        prior_counts = [p.get(topic_id, {}).get("total", 0) for p in priors]
        scored.append(
            score_topic(
                TopicCounts(
                    topic_id=topic_id,
                    event_count=bucket["total"],
                    new_paper=bucket["new_paper"],
                    consensus_updated=bucket["consensus_updated"],
                    contradiction_flagged=bucket["contradiction_flagged"],
                    paper_retracted=bucket["paper_retracted"],
                ),
                prior_counts,
                weeks_tracked=weeks,
            )
        )

    for position, item in enumerate(rank_topics(scored), start=1):
        session.add(
            TopicActivitySnapshot(
                generation_id=generation,
                topic_id=item.counts.topic_id,
                window_start=current.start,
                window_end=current.end,
                event_count=item.counts.event_count,
                new_paper_count=item.counts.new_paper,
                consensus_updated_count=item.counts.consensus_updated,
                contradiction_count=item.counts.contradiction_flagged,
                retraction_count=item.counts.paper_retracted,
                baseline_mean=item.baseline_mean,
                baseline_weeks=item.baseline_weeks,
                trend_score=item.trend_score,
                is_newly_tracked=item.is_newly_tracked,
                rank=position,
                computed_at=as_of,
            )
        )
    session.flush()

    # Publish. Everything above this line is invisible to readers.
    state.current_generation_id = generation
    state.running_generation_id = None
    state.status = "idle"
    state.completed_at = as_of
    state.topics_processed = len(scored)
    state.topics_failed = 0
    state.last_error = None
    session.flush()

    _prune(session, generation, as_of)
    return generation


def _prune(session: Session, keep_generation: uuid.UUID, as_of: datetime) -> None:
    """Drop generations older than the retention horizon.

    The current generation is exempt regardless of age: a dashboard that stopped being
    refreshed should keep serving its last good ranking rather than silently emptying.
    """
    cutoff = as_of - timedelta(days=RETENTION_DAYS)
    session.execute(
        delete(TopicActivitySnapshot).where(
            TopicActivitySnapshot.computed_at < cutoff,
            TopicActivitySnapshot.generation_id != keep_generation,
        )
    )
    session.flush()


def read_current_activity(session: Session, limit: int) -> dict:
    """The API payload for GET /dashboard/activity."""
    state = session.execute(
        select(DashboardJobState).where(DashboardJobState.job_name == JOB_NAME)
    ).scalar_one_or_none()
    if state is None or state.current_generation_id is None:
        # Cold start: no job has run. Answer with nulls rather than an error, so the
        # dashboard renders its empty state instead of a failure.
        return {"computed_at": None, "window_start": None, "window_end": None, "topics": []}

    rows = session.execute(
        select(TopicActivitySnapshot, Topic)
        .join(Topic, Topic.id == TopicActivitySnapshot.topic_id)
        .where(TopicActivitySnapshot.generation_id == state.current_generation_id)
        .order_by(TopicActivitySnapshot.rank)
        .limit(limit)
    ).all()

    if not rows:
        return {
            "computed_at": _iso(state.completed_at),
            "window_start": None,
            "window_end": None,
            "topics": [],
        }

    first_snapshot = rows[0][0]
    return {
        "computed_at": _iso(state.completed_at),
        "window_start": _iso(first_snapshot.window_start),
        "window_end": _iso(first_snapshot.window_end),
        "topics": [
            {
                "topic": {"id": str(topic.id), "canonical_label": topic.canonical_label},
                "rank": snapshot.rank,
                "event_count": snapshot.event_count,
                "breakdown": {
                    "new_paper": snapshot.new_paper_count,
                    "consensus_updated": snapshot.consensus_updated_count,
                    "contradiction_flagged": snapshot.contradiction_count,
                    "paper_retracted": snapshot.retraction_count,
                },
                "baseline_mean": float(snapshot.baseline_mean)
                if snapshot.baseline_mean is not None
                else None,
                "baseline_weeks": snapshot.baseline_weeks,
                "trend_score": float(snapshot.trend_score)
                if snapshot.trend_score is not None
                else None,
                "is_newly_tracked": snapshot.is_newly_tracked,
            }
            for snapshot, topic in rows
        ],
    }


def _iso(value: datetime | None) -> str | None:
    """Naive UTC timestamps need an explicit Z, or JavaScript parses them as local time.

    Same reasoning as citations/read.py's iso_utc: an offset-less date-time is read by
    the browser in the viewer's own zone, which would shift every "data as of" label and
    could push computed_at across the 36-hour staleness threshold for anyone west of UTC.
    """
    return None if value is None else value.isoformat() + "Z"
