from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from dashboard.activity import _iso
from evidence_engine.db.models import ChangeEvent, ChangeEventType, Paper, Score, Topic


def read_change_feed(
    session: Session, days: int, limit: int, now: datetime | None = None
) -> dict:
    """Recent change events, grouped by calendar day, newest first.

    `total_events` counts the events in THIS response, after `limit` truncation -- not
    the number matching the window. The feed is a recency view, so "N changes" means "N
    shown here".

    Retraction filter (spec 14.3): an event is included when it is itself a retraction,
    or has no paper, or its paper is not retracted. The effect is that a paper later found
    to be retracted stops being advertised as new evidence, while the retraction itself
    stays visible -- which is the event a researcher most needs to see.

    The window is half-open on both ends -- `cutoff < detected_at <= now` -- matching the
    rest of the sub-project. `now` is injectable so a test can place an event exactly on
    each boundary; while the clock was read internally, the cutoff comparison was the one
    half-open boundary on the branch that no test could reach, and mutating `>` to `>=`
    survived the whole suite.

    The upper bound is deliberate too. Without it a future-dated event -- a clock-skewed
    ingest, a backfill with a bad date -- would appear in the feed forever, always sorting
    first, which is the one position in a recency view where a wrong row does most damage.
    """
    now = now or datetime.utcnow()
    cutoff = now - timedelta(days=days)

    rows = session.execute(
        select(ChangeEvent, Topic, Paper, Score)
        .join(Topic, Topic.id == ChangeEvent.topic_id)
        .outerjoin(Paper, Paper.id == ChangeEvent.paper_id)
        .outerjoin(Score, Score.paper_id == ChangeEvent.paper_id)
        .where(
            ChangeEvent.detected_at > cutoff,
            ChangeEvent.detected_at <= now,
            or_(
                ChangeEvent.event_type == ChangeEventType.PAPER_RETRACTED,
                ChangeEvent.paper_id.is_(None),
                Paper.is_retracted.is_(False),
            ),
        )
        .order_by(ChangeEvent.detected_at.desc())
        .limit(limit)
    ).all()

    days_out: list[dict] = []
    index_by_date: dict[str, int] = {}
    for event, topic, paper, score in rows:
        date_key = event.detected_at.date().isoformat()
        if date_key not in index_by_date:
            index_by_date[date_key] = len(days_out)
            days_out.append({"date": date_key, "events": []})
        days_out[index_by_date[date_key]]["events"].append(
            {
                "event_type": event.event_type.value,
                "detected_at": _iso(event.detected_at),
                "topic": {"id": str(topic.id), "canonical_label": topic.canonical_label},
                "paper": None
                if paper is None
                else {"id": str(paper.id), "title": paper.title},
                # A pending Score carries column defaults (evidence_tier='speculative'),
                # so surfacing it would label an unscored paper as speculative evidence --
                # the defect sub-project A shipped once. Treated as no tier instead.
                "evidence_tier": score.evidence_tier.value
                if score is not None and not score.is_pending and score.evidence_tier
                else None,
            }
        )

    return {"days": days_out, "total_events": len(rows)}
