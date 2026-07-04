# tests/digest/test_models.py
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from digest.models import DeliveryPreference, DigestFrequency, InterestProfile, ProfileTopic, User
from evidence_engine.db.models import Topic


def test_user_profile_topic_and_preference_round_trip(db_session):
    user = User(email="researcher@example.com")
    db_session.add(user)
    db_session.flush()

    profile = InterestProfile(user_id=user.id)
    db_session.add(profile)

    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    db_session.add(topic)
    db_session.flush()

    db_session.add(ProfileTopic(profile_id=profile.id, topic_id=topic.id))
    db_session.add(DeliveryPreference(user_id=user.id, frequency=DigestFrequency.WEEKLY, send_day=2))
    db_session.flush()

    fetched_user = db_session.get(User, user.id)
    fetched_preference = db_session.execute(
        select(DeliveryPreference).where(DeliveryPreference.user_id == user.id)
    ).scalar_one()

    assert fetched_user.email == "researcher@example.com"
    assert fetched_preference.frequency == DigestFrequency.WEEKLY
    assert fetched_preference.send_day == 2


def test_profile_topic_unique_constraint_rejects_duplicate_link(db_session):
    user = User(email="researcher2@example.com")
    db_session.add(user)
    db_session.flush()

    profile = InterestProfile(user_id=user.id)
    db_session.add(profile)

    topic = Topic(canonical_label="Diabetes Mellitus, Type 2", mesh_id="D003924")
    db_session.add(topic)
    db_session.flush()

    db_session.add(ProfileTopic(profile_id=profile.id, topic_id=topic.id))
    db_session.flush()

    db_session.add(ProfileTopic(profile_id=profile.id, topic_id=topic.id))
    with pytest.raises(IntegrityError):
        db_session.flush()
