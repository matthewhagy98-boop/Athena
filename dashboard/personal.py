import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dashboard.activity import _iso
from digest.models import InterestProfile, ProfileTopic, User
from evidence_engine.db.models import ChangeEvent, ChangeEventType, Topic

_TYPE_FIELDS = {
    ChangeEventType.NEW_PAPER: "new_paper",
    ChangeEventType.CONSENSUS_UPDATED: "consensus_updated",
    ChangeEventType.CONTRADICTION_FLAGGED: "contradiction_flagged",
    ChangeEventType.PAPER_RETRACTED: "paper_retracted",
}


def _empty_breakdown() -> dict:
    return {field: 0 for field in _TYPE_FIELDS.values()}


def personal_topic_summary(session: Session, user_id: uuid.UUID, days: int) -> dict:
    """Per-topic change counts for exactly the user's interest topics.

    Resolves the profile with scalar_one_or_none rather than calling
    digest.profiles.list_interests, which reaches _get_profile's .scalar_one()
    (digest/profiles.py:34) and raises NoResultFound. Every user created by
    create_anonymous_user lacks a profile, so the raising path is the COMMON case on this
    surface -- a dashboard that 500s for every first-time visitor.

    Raises LookupError for a user_id that matches no User, which the endpoint turns into
    a 404: a typo'd id must not be indistinguishable from a real user who has simply not
    personalised yet.
    """
    user = session.get(User, user_id)
    if user is None:
        raise LookupError(f"User {user_id} not found")

    profile = session.execute(
        select(InterestProfile).where(InterestProfile.user_id == user_id)
    ).scalar_one_or_none()
    if profile is None:
        return {
            "has_profile": False,
            "computed_at": None,
            "window_start": None,
            "window_end": None,
            "topics": [],
        }

    links = session.execute(
        select(ProfileTopic, Topic)
        .join(Topic, Topic.id == ProfileTopic.topic_id)
        .where(ProfileTopic.profile_id == profile.id)
        # Matches list_interests' ordering (digest/profiles.py:67).
        .order_by(ProfileTopic.added_at)
    ).all()

    now = datetime.utcnow()
    window_start = now - timedelta(days=days)
    topic_ids = [topic.id for _, topic in links]

    counts: dict = {}
    latest: dict = {}
    if topic_ids:
        rows = session.execute(
            select(
                ChangeEvent.topic_id,
                ChangeEvent.event_type,
                func.count().label("n"),
                func.max(ChangeEvent.detected_at).label("latest"),
            )
            .where(
                ChangeEvent.topic_id.in_(topic_ids),
                ChangeEvent.detected_at > window_start,
                ChangeEvent.detected_at <= now,
            )
            .group_by(ChangeEvent.topic_id, ChangeEvent.event_type)
        ).all()
        for topic_id, event_type, n, most_recent in rows:
            bucket = counts.setdefault(topic_id, _empty_breakdown())
            field = _TYPE_FIELDS.get(event_type)
            if field is not None:
                bucket[field] += n
            if topic_id not in latest or most_recent > latest[topic_id]:
                latest[topic_id] = most_recent

    return {
        "has_profile": True,
        "computed_at": _iso(now),
        "window_start": _iso(window_start),
        "window_end": _iso(now),
        "topics": [
            {
                "topic": {"id": str(topic.id), "canonical_label": topic.canonical_label},
                # Topics with no events are listed with a zero count (FR-C-008): dropping
                # them would make the widget look like the user has fewer interests than
                # they do, and "no change this week" is itself information.
                "event_count": sum(counts.get(topic.id, _empty_breakdown()).values()),
                "breakdown": counts.get(topic.id, _empty_breakdown()),
                "latest_event_at": _iso(latest.get(topic.id)),
            }
            for _, topic in links
        ],
    }


def _plural(count: int, singular: str) -> str:
    return f"{count} {singular}" if count == 1 else f"{count} {singular}s"


def render_blurb(summary: dict) -> str | None:
    """A deterministic sentence summarising the window. Never LLM-written.

    Plan decision (OQ-C-002): this delivers most of the reference design's "blurb" value
    with zero model cost and no hallucination risk, and is honest in a way generated prose
    would not be. Sub-project B may later replace it with a real narrative.

    Built with an f-string rather than Jinja2: the template is one sentence with no
    control flow beyond pluralisation, and a template file would put the copy rules
    (FR-C-015) somewhere the tests asserting them do not look.
    """
    if not summary.get("has_profile"):
        return None

    topics = summary.get("topics", [])
    topic_phrase = _plural(len(topics), "topic")

    totals = {field: 0 for field in _TYPE_FIELDS.values()}
    for row in topics:
        for field, value in row.get("breakdown", {}).items():
            totals[field] = totals.get(field, 0) + value

    parts = []
    if totals["new_paper"]:
        parts.append(_plural(totals["new_paper"], "new paper"))
    if totals["consensus_updated"]:
        parts.append(_plural(totals["consensus_updated"], "consensus update"))
    if totals["contradiction_flagged"]:
        parts.append(_plural(totals["contradiction_flagged"], "flagged contradiction"))
    if totals["paper_retracted"]:
        parts.append(_plural(totals["paper_retracted"], "retraction"))

    if not parts:
        # "No change this week", never "nothing found" or "no results" (FR-C-015).
        return f"No change in your {topic_phrase} this week."

    if len(parts) == 1:
        subject = parts[0]
    else:
        subject = ", ".join(parts[:-1]) + f" and {parts[-1]}"
    return f"{subject} across your {topic_phrase} this week."
