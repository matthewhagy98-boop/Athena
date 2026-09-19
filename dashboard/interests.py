import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from dashboard.models import DashboardRateWindow
from digest.models import InterestProfile, ProfileTopic, User
from digest.profiles import add_interest, remove_interest
from evidence_engine.db.models import Topic

# POST /interests triggers an outbound PubMed term resolution inside get_or_create_topic,
# so it is the one C endpoint with an external dependency. Read endpoints are single
# indexed queries and are not limited.
RATE_LIMIT_PER_HOUR = 30
MAX_FREE_TEXT = 200


class RateLimitExceeded(Exception):
    """Raised when a user exceeds RATE_LIMIT_PER_HOUR adds in one clock hour."""


def _hour_start(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0)


def _consume_quota(session: Session, user_id: uuid.UUID, now: datetime) -> None:
    """Increment this user's counter for the current hour, or refuse.

    Fixed clock-hour windows rather than a rolling window: one row per user per hour,
    countable with an index, and the imprecision at a boundary is irrelevant for a limit
    whose job is to stop abuse rather than to meter fairly.
    """
    window_start = _hour_start(now)
    subject = f"user:{user_id}"
    counter = session.execute(
        select(DashboardRateWindow).where(
            DashboardRateWindow.subject == subject,
            DashboardRateWindow.window_start == window_start,
        )
    ).scalar_one_or_none()

    if counter is None:
        counter = DashboardRateWindow(subject=subject, window_start=window_start, request_count=0)
        session.add(counter)
        session.flush()

    if counter.request_count >= RATE_LIMIT_PER_HOUR:
        raise RateLimitExceeded(
            f"Limit of {RATE_LIMIT_PER_HOUR} interest additions per hour reached"
        )

    counter.request_count += 1
    session.flush()


def _require_user(session: Session, user_id: uuid.UUID) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise LookupError(f"User {user_id} not found")
    return user


def add_user_interest(
    session: Session, user_id: uuid.UUID, free_text: str, now: datetime | None = None
) -> tuple[Topic, bool]:
    """Add an interest topic, creating the InterestProfile on first use (FR-C-013).

    digest.profiles.add_interest cannot be called directly for a fresh user: it goes
    through _get_profile's .scalar_one() (digest/profiles.py:34), which raises for every
    user create_anonymous_user made. Creating the profile here is safe -- commit a5a4117
    guarded select_due_users against a profile without a DeliveryPreference, which is
    exactly the shape this creates (OQ-C-001).

    Returns (topic, created) where created is False if the user already had this interest.
    """
    user = _require_user(session, user_id)

    text = (free_text or "").strip()
    if not text:
        raise ValueError("free_text must not be empty")
    if len(text) > MAX_FREE_TEXT:
        raise ValueError(f"free_text must be {MAX_FREE_TEXT} characters or fewer")

    # Charged before the outbound call, so a burst cannot slip through while requests are
    # in flight.
    _consume_quota(session, user_id, now or datetime.utcnow())

    profile = session.execute(
        select(InterestProfile).where(InterestProfile.user_id == user_id)
    ).scalar_one_or_none()
    if profile is None:
        profile = InterestProfile(user_id=user_id)
        session.add(profile)
        session.flush()

    before = session.execute(
        select(ProfileTopic).where(ProfileTopic.profile_id == profile.id)
    ).scalars().all()
    existing_ids = {link.topic_id for link in before}

    topic = add_interest(session, user, text)
    return topic, topic.id not in existing_ids


def remove_user_interest(session: Session, user_id: uuid.UUID, topic_id: uuid.UUID) -> None:
    """Remove an interest. Raises LookupError if the user or the interest is absent.

    Not idempotent on repeat, matching DELETE /saved-searches/{id}'s existing contract.
    """
    user = _require_user(session, user_id)

    profile = session.execute(
        select(InterestProfile).where(InterestProfile.user_id == user_id)
    ).scalar_one_or_none()
    if profile is None:
        raise LookupError("User has no interest profile")

    link = session.execute(
        select(ProfileTopic).where(
            ProfileTopic.profile_id == profile.id, ProfileTopic.topic_id == topic_id
        )
    ).scalar_one_or_none()
    if link is None:
        raise LookupError(f"Interest {topic_id} not found for this user")

    remove_interest(session, user, topic_id)
