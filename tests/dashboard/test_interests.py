import uuid
from datetime import datetime, timedelta

import pytest

from dashboard.interests import (
    MAX_FREE_TEXT,
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


def test_the_quota_is_charged_before_the_outbound_call(db_session, monkeypatch):
    """Ordering, not just presence. Charging after the call survives every other test.

    This endpoint's whole reason for having a limit is that get_or_create_topic reaches
    PubMed. If the counter were incremented only on success, a burst of concurrent
    requests would all pass the check while every one of them was still in flight, and
    the provider would see the full burst. Charging first means a failed call still costs
    the caller its slot -- the conservative direction for a limit whose job is to protect
    someone else's service.
    """
    from sqlalchemy import select as _select

    from dashboard.models import DashboardRateWindow

    user = create_anonymous_user(db_session)

    def failing_get_or_create_topic(session, free_text):
        raise RuntimeError("PubMed unreachable")

    monkeypatch.setattr("digest.profiles.get_or_create_topic", failing_get_or_create_topic)

    with pytest.raises(RuntimeError):
        add_user_interest(db_session, user.id, "unreachable topic", now=NOW)

    counter = db_session.execute(
        _select(DashboardRateWindow).where(DashboardRateWindow.subject == f"user:{user.id}")
    ).scalar_one_or_none()

    assert counter is not None, "no quota was charged for a request that reached the provider"
    assert counter.request_count == 1


def test_the_documented_limit_is_thirty_per_hour():
    """The number comes from the spec, not from taste.

    Spec section 12: POST /interests "MUST be capped at 30 requests/hour per user_id".
    The other tests drive the limit symbolically through RATE_LIMIT_PER_HOUR, so the
    constant could drift to any value and they would all still pass. Unlike a tuning knob,
    a spec-stated figure is worth pinning -- changing it should be a deliberate act that
    updates the spec too.
    """
    assert RATE_LIMIT_PER_HOUR == 30


def test_rejected_input_does_not_consume_quota(db_session):
    """Validation runs before the quota is charged, and nothing pinned that ordering.

    The quota exists to protect PubMed from repeated outbound calls. Blank text never
    reaches PubMed, so charging for it would let a caller exhaust their own hourly budget
    on input that cost the provider nothing -- punishing a typo as though it were abuse.
    """
    from sqlalchemy import select as _select

    from dashboard.models import DashboardRateWindow

    user = create_anonymous_user(db_session)

    with pytest.raises(ValueError):
        add_user_interest(db_session, user.id, "   ", now=NOW)

    counter = db_session.execute(
        _select(DashboardRateWindow).where(DashboardRateWindow.subject == f"user:{user.id}")
    ).scalar_one_or_none()

    assert counter is None or counter.request_count == 0


def test_the_documented_free_text_cap_is_two_hundred():
    """Same reasoning as test_the_documented_limit_is_thirty_per_hour, applied to the
    constant that did not get it: the other tests drive the cap symbolically, so it could
    drift to any value and they would all still pass."""
    assert MAX_FREE_TEXT == 200


def test_free_text_is_accepted_at_the_cap_and_rejected_one_character_past_it(db_session):
    """The cap had zero coverage: raising it to MAX_FREE_TEXT * 100 survived the whole
    suite. This is the one endpoint that forwards its input to an outbound PubMed term
    resolution, so an unbounded free_text is a request body someone else has to parse.

    Pinned from both sides, because a test that only sends an over-long string also
    passes against a cap set far too low.
    """
    user = create_anonymous_user(db_session)

    topic, _ = add_user_interest(db_session, user.id, "a" * MAX_FREE_TEXT, now=NOW)
    assert topic is not None

    with pytest.raises(ValueError, match="characters or fewer"):
        add_user_interest(db_session, user.id, "a" * (MAX_FREE_TEXT + 1), now=NOW)


def test_over_long_free_text_does_not_consume_quota(db_session):
    """The same property test_rejected_input_does_not_consume_quota pins for blank text.
    An over-long string never reaches PubMed either, so it must not cost the caller a
    slot -- otherwise a caller fat-fingering a paste burns their hourly budget on input
    that cost the provider nothing."""
    from sqlalchemy import select as _select

    from dashboard.models import DashboardRateWindow

    user = create_anonymous_user(db_session)

    with pytest.raises(ValueError):
        add_user_interest(db_session, user.id, "a" * (MAX_FREE_TEXT + 1), now=NOW)

    charged = db_session.execute(
        _select(DashboardRateWindow).where(DashboardRateWindow.subject == f"user:{user.id}")
    ).scalar_one_or_none()
    assert charged is None
