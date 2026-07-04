import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from evidence_engine.db.models import Topic
from evidence_engine.topics.registry import get_or_create_topic

from digest.models import DeliveryPreference, DigestFrequency, InterestProfile, ProfileTopic, User


def create_user(session: Session, email: str) -> User:
    user = User(email=email)
    session.add(user)
    session.flush()

    session.add(InterestProfile(user_id=user.id))
    session.add(DeliveryPreference(user_id=user.id, frequency=DigestFrequency.WEEKLY, send_day=0))
    session.flush()
    return user


def _get_profile(session: Session, user: User) -> InterestProfile:
    return session.execute(
        select(InterestProfile).where(InterestProfile.user_id == user.id)
    ).scalar_one()


def add_interest(session: Session, user: User, free_text: str) -> Topic:
    profile = _get_profile(session, user)
    topic = get_or_create_topic(session, free_text)

    existing = session.execute(
        select(ProfileTopic).where(ProfileTopic.profile_id == profile.id, ProfileTopic.topic_id == topic.id)
    ).scalar_one_or_none()
    if existing is None:
        session.add(ProfileTopic(profile_id=profile.id, topic_id=topic.id))
        session.flush()
    return topic


def remove_interest(session: Session, user: User, topic_id: uuid.UUID) -> None:
    profile = _get_profile(session, user)
    link = session.execute(
        select(ProfileTopic).where(ProfileTopic.profile_id == profile.id, ProfileTopic.topic_id == topic_id)
    ).scalar_one_or_none()
    if link is not None:
        session.delete(link)
        session.flush()


def list_interests(session: Session, user: User) -> list[Topic]:
    profile = _get_profile(session, user)
    return (
        session.execute(
            select(Topic)
            .join(ProfileTopic, ProfileTopic.topic_id == Topic.id)
            .where(ProfileTopic.profile_id == profile.id)
            .order_by(ProfileTopic.added_at)
        )
        .scalars()
        .all()
    )


def get_delivery_preference(session: Session, user: User) -> DeliveryPreference:
    return session.execute(
        select(DeliveryPreference).where(DeliveryPreference.user_id == user.id)
    ).scalar_one()


def update_delivery_preference(
    session: Session,
    user: User,
    frequency: DigestFrequency | None = None,
    send_day: int | None = None,
) -> DeliveryPreference:
    preference = get_delivery_preference(session, user)
    if frequency is not None:
        preference.frequency = frequency
    if send_day is not None:
        preference.send_day = send_day
    session.flush()
    return preference
