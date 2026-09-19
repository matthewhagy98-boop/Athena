import uuid
from datetime import datetime, timedelta

import pytest

from dashboard.interests import (
    RATE_LIMIT_PER_HOUR,
    RateLimitExceeded,
    add_user_interest,
    remove_user_interest,
)
from digest.models import InterestProfile
from digest.profiles import create_anonymous_user
from evidence_engine.db.models import Topic
from sqlalchemy import select

NOW = datetime(2026, 8, 2, 9, 30)


@pytest.fixture(autouse=True)
def _no_pubmed(monkeypatch):
    """get_or_create_topic reaches PubMed. No test may make that call."""
    def fake_get_or_create_topic(session, free_text):
        existing = session.execute(
            select(Topic).where(Topic.canonical_label == free_text.title())
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        topic = Topic(canonical_label=free_text.title())
        session.add(topic)
        session.flush()
        return topic

    monkeypatch.setattr("digest.profiles.get_or_create_topic", fake_get_or_create_topic)


def test_the_first_interest_creates_the_profile(db_session):
    # FR-C-013. create_anonymous_user writes no profile (digest/profiles.py:23), and
    # digest's own add_interest would raise NoResultFound on that user.
    user = create_anonymous_user(db_session)

    topic, created = add_user_interest(db_session, user.id, "atrial fibrillation", now=NOW)

    assert created is True
    assert topic.canonical_label == "Atrial Fibrillation"
    profile = db_session.execute(
        select(InterestProfile).where(InterestProfile.user_id == user.id)
    ).scalar_one()
    assert profile is not None


def test_adding_the_same_interest_twice_is_idempotent(db_session):
    user = create_anonymous_user(db_session)
    add_user_interest(db_session, user.id, "sepsis biomarkers", now=NOW)

    _, created = add_user_interest(db_session, user.id, "sepsis biomarkers", now=NOW)

    assert created is False


def test_an_unknown_user_raises(db_session):
    with pytest.raises(LookupError):
        add_user_interest(db_session, uuid.uuid4(), "anything", now=NOW)


def test_blank_free_text_is_rejected(db_session):
    user = create_anonymous_user(db_session)

    with pytest.raises(ValueError):
        add_user_interest(db_session, user.id, "   ", now=NOW)


def test_the_rate_limit_blocks_the_call_that_exceeds_it(db_session):
    # This endpoint triggers an outbound PubMed call, so it is the one C route with an
    # external dependency and the only one that can be abused into hammering a provider.
    user = create_anonymous_user(db_session)
    for index in range(RATE_LIMIT_PER_HOUR):
        add_user_interest(db_session, user.id, f"topic {index}", now=NOW)

    with pytest.raises(RateLimitExceeded):
        add_user_interest(db_session, user.id, "one too many", now=NOW)


def test_the_counter_resets_in_the_next_hour(db_session):
    user = create_anonymous_user(db_session)
    for index in range(RATE_LIMIT_PER_HOUR):
        add_user_interest(db_session, user.id, f"topic {index}", now=NOW)

    topic, _ = add_user_interest(db_session, user.id, "next hour", now=NOW + timedelta(hours=1))

    assert topic is not None


def test_the_limit_is_per_user_not_global(db_session):
    first = create_anonymous_user(db_session)
    second = create_anonymous_user(db_session)
    for index in range(RATE_LIMIT_PER_HOUR):
        add_user_interest(db_session, first.id, f"topic {index}", now=NOW)

    topic, _ = add_user_interest(db_session, second.id, "mine", now=NOW)

    assert topic is not None


def test_a_rejected_request_does_not_consume_quota_from_the_next_hour(db_session):
    # The counter increments before the outbound call, so a blocked request must not also
    # poison the following window.
    user = create_anonymous_user(db_session)
    for index in range(RATE_LIMIT_PER_HOUR):
        add_user_interest(db_session, user.id, f"topic {index}", now=NOW)
    with pytest.raises(RateLimitExceeded):
        add_user_interest(db_session, user.id, "blocked", now=NOW)

    topic, _ = add_user_interest(db_session, user.id, "allowed", now=NOW + timedelta(hours=1))

    assert topic is not None


def test_removing_an_interest_leaves_the_profile(db_session):
    user = create_anonymous_user(db_session)
    topic, _ = add_user_interest(db_session, user.id, "removable", now=NOW)

    remove_user_interest(db_session, user.id, topic.id)

    profile = db_session.execute(
        select(InterestProfile).where(InterestProfile.user_id == user.id)
    ).scalar_one()
    assert profile is not None


def test_removing_an_interest_the_user_does_not_have_raises(db_session):
    user = create_anonymous_user(db_session)
    add_user_interest(db_session, user.id, "kept", now=NOW)

    with pytest.raises(LookupError):
        remove_user_interest(db_session, user.id, uuid.uuid4())


def test_removing_from_a_user_with_no_profile_raises(db_session):
    user = create_anonymous_user(db_session)

    with pytest.raises(LookupError):
        remove_user_interest(db_session, user.id, uuid.uuid4())
