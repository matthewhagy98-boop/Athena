import uuid
from datetime import datetime, timedelta

import pytest

from dashboard.personal import personal_topic_summary, render_blurb
from digest.models import InterestProfile, ProfileTopic
from digest.profiles import create_anonymous_user
from evidence_engine.db.models import ChangeEvent, ChangeEventType, Topic


def _topic(db_session, label):
    topic = Topic(canonical_label=label)
    db_session.add(topic)
    db_session.flush()
    return topic


def _interested(db_session, user, *topics):
    profile = InterestProfile(user_id=user.id)
    db_session.add(profile)
    db_session.flush()
    for topic in topics:
        db_session.add(ProfileTopic(profile_id=profile.id, topic_id=topic.id))
    db_session.flush()
    return profile


def _event(db_session, topic_id, event_type, days_ago):
    db_session.add(
        ChangeEvent(
            topic_id=topic_id,
            event_type=event_type,
            detected_at=datetime.utcnow() - timedelta(days=days_ago),
        )
    )
    db_session.flush()


def test_personal_endpoint_returns_empty_for_user_without_profile(db_session):
    # Every user from create_anonymous_user lacks a profile, so this is the COMMON case
    # on this surface, not an edge case. digest.profiles.list_interests would raise
    # NoResultFound here via _get_profile's .scalar_one() (digest/profiles.py:34) --
    # which is exactly why this package resolves the profile itself.
    user = create_anonymous_user(db_session)

    summary = personal_topic_summary(db_session, user.id, days=7)

    assert summary == {
        "has_profile": False,
        "computed_at": None,
        "window_start": None,
        "window_end": None,
        "topics": [],
    }


def test_an_unknown_user_raises_rather_than_reporting_no_profile(db_session):
    # A typo'd user_id must not look identical to a real user who has not personalised;
    # the endpoint turns this into a 404.
    with pytest.raises(LookupError):
        personal_topic_summary(db_session, uuid.uuid4(), days=7)


def test_counts_cover_exactly_the_users_interest_topics(db_session):
    user = create_anonymous_user(db_session)
    mine = _topic(db_session, "Atrial fibrillation")
    theirs = _topic(db_session, "Someone else's topic")
    _interested(db_session, user, mine)
    _event(db_session, mine.id, ChangeEventType.NEW_PAPER, 1)
    _event(db_session, theirs.id, ChangeEventType.NEW_PAPER, 1)

    summary = personal_topic_summary(db_session, user.id, days=7)

    assert [t["topic"]["canonical_label"] for t in summary["topics"]] == ["Atrial fibrillation"]
    assert summary["topics"][0]["event_count"] == 1


def test_a_quiet_interest_topic_is_listed_with_a_zero_count(db_session):
    # FR-C-008. Dropping silent topics would make the widget look like the user has
    # fewer interests than they do, and "no change this week" is itself information.
    user = create_anonymous_user(db_session)
    quiet = _topic(db_session, "Sepsis biomarkers")
    _interested(db_session, user, quiet)

    summary = personal_topic_summary(db_session, user.id, days=7)

    assert summary["topics"][0]["event_count"] == 0
    assert summary["topics"][0]["latest_event_at"] is None
    assert summary["topics"][0]["breakdown"]["new_paper"] == 0


def test_the_breakdown_and_latest_event_are_reported(db_session):
    user = create_anonymous_user(db_session)
    topic = _topic(db_session, "Mixed")
    _interested(db_session, user, topic)
    _event(db_session, topic.id, ChangeEventType.NEW_PAPER, 3)
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED, 1)

    row = personal_topic_summary(db_session, user.id, days=7)["topics"][0]

    assert row["event_count"] == 2
    assert row["breakdown"] == {
        "new_paper": 1,
        "consensus_updated": 1,
        "contradiction_flagged": 0,
        "paper_retracted": 0,
    }
    assert row["latest_event_at"] is not None


def test_topics_are_ordered_by_when_the_user_added_them(db_session):
    # Matches list_interests' ordering (digest/profiles.py:67), so the dashboard and any
    # future interest list agree.
    user = create_anonymous_user(db_session)
    first = _topic(db_session, "Added first")
    second = _topic(db_session, "Added second")
    profile = InterestProfile(user_id=user.id)
    db_session.add(profile)
    db_session.flush()
    db_session.add(ProfileTopic(profile_id=profile.id, topic_id=first.id,
                                added_at=datetime(2026, 1, 1)))
    db_session.add(ProfileTopic(profile_id=profile.id, topic_id=second.id,
                                added_at=datetime(2026, 6, 1)))
    db_session.flush()

    labels = [t["topic"]["canonical_label"]
              for t in personal_topic_summary(db_session, user.id, days=7)["topics"]]

    assert labels == ["Added first", "Added second"]


def test_the_blurb_is_a_deterministic_sentence(db_session):
    # Deliberately NOT LLM-written (plan decision, OQ-C-002). A templated sentence is
    # honest in a way generated prose would not be, costs nothing, and cannot hallucinate.
    summary = {
        "has_profile": True,
        "topics": [
            {"event_count": 10, "breakdown": {"new_paper": 9, "consensus_updated": 1,
                                              "contradiction_flagged": 0, "paper_retracted": 0}},
            {"event_count": 2, "breakdown": {"new_paper": 1, "consensus_updated": 1,
                                             "contradiction_flagged": 0, "paper_retracted": 0}},
            {"event_count": 0, "breakdown": {"new_paper": 0, "consensus_updated": 0,
                                             "contradiction_flagged": 0, "paper_retracted": 0}},
        ],
    }

    assert render_blurb(summary) == (
        "10 new papers and 2 consensus updates across your 3 topics this week."
    )


def test_the_blurb_uses_singular_forms_where_appropriate(db_session):
    summary = {
        "has_profile": True,
        "topics": [
            {"event_count": 1, "breakdown": {"new_paper": 1, "consensus_updated": 0,
                                             "contradiction_flagged": 0, "paper_retracted": 0}},
        ],
    }

    assert render_blurb(summary) == "1 new paper across your 1 topic this week."


def test_the_blurb_says_nothing_changed_rather_than_listing_zeros(db_session):
    summary = {
        "has_profile": True,
        "topics": [
            {"event_count": 0, "breakdown": {"new_paper": 0, "consensus_updated": 0,
                                             "contradiction_flagged": 0, "paper_retracted": 0}},
        ],
    }

    assert render_blurb(summary) == "No change in your 1 topic this week."


def test_there_is_no_blurb_without_a_profile(db_session):
    assert render_blurb({"has_profile": False, "topics": []}) is None


def test_the_blurb_never_uses_forbidden_copy(db_session):
    # Driven across every branch of render_blurb, not one fixture. The branch the copy
    # rules constrain MOST is the zero-change one -- "No change this week", never
    # "nothing found" or "no results" -- and a single all-positive fixture never reaches
    # it. A regression that put forbidden wording specifically in that sentence would
    # have passed the original version of this test.
    forbidden = ["trending", "hot", "popular", "breakthrough", "important",
                 "momentum", "real-time", "live", "nothing found", "no results"]

    def summary(*topics):
        return {"has_profile": True, "topics": list(topics)}

    def topic(new_paper=0, consensus=0, contradiction=0, retracted=0):
        return {
            "event_count": new_paper + consensus + contradiction + retracted,
            "breakdown": {
                "new_paper": new_paper,
                "consensus_updated": consensus,
                "contradiction_flagged": contradiction,
                "paper_retracted": retracted,
            },
        }

    cases = {
        "all four types": summary(topic(30, 4, 4, 2)),
        "new papers only": summary(topic(new_paper=12)),
        "a single new paper": summary(topic(new_paper=1)),
        "consensus only": summary(topic(consensus=3)),
        "contradictions only": summary(topic(contradiction=2)),
        "retractions only": summary(topic(retracted=1)),
        "zero change, one topic": summary(topic()),
        "zero change, several topics": summary(topic(), topic(), topic()),
        "mixed quiet and busy": summary(topic(), topic(new_paper=5)),
    }

    for name, payload in cases.items():
        text = render_blurb(payload).lower()
        for word in forbidden:
            assert word not in text, f"{name!r} produced forbidden copy {word!r}: {text!r}"


def test_the_zero_change_branch_says_no_change(db_session):
    # Pins the wording the rules actually prescribe, not just the absence of bad wording.
    # Asserting only what a string must NOT contain is satisfied by any replacement,
    # including an empty one.
    text = render_blurb({"has_profile": True, "topics": [
        {"event_count": 0, "breakdown": {"new_paper": 0, "consensus_updated": 0,
                                         "contradiction_flagged": 0, "paper_retracted": 0}},
    ]})

    assert "no change" in text.lower()


def test_every_event_type_lands_in_its_own_breakdown_slot(db_session):
    """Distinct counts per type, so a swapped mapping cannot produce an identical dict.

    No test created a CONTRADICTION_FLAGGED or PAPER_RETRACTED event at all, and the one
    test using two types gave each a count of 1 -- so swapping NEW_PAPER and
    CONSENSUS_UPDATED in _TYPE_FIELDS produced exactly the same breakdown and survived.
    Distinct counts make every mapping observable.
    """
    user = create_anonymous_user(db_session)
    topic = _topic(db_session, "All four")
    _interested(db_session, user, topic)
    for count, event_type in (
        (1, ChangeEventType.NEW_PAPER),
        (2, ChangeEventType.CONSENSUS_UPDATED),
        (3, ChangeEventType.CONTRADICTION_FLAGGED),
        (4, ChangeEventType.PAPER_RETRACTED),
    ):
        for _ in range(count):
            _event(db_session, topic.id, event_type, 1)

    row = personal_topic_summary(db_session, user.id, days=7)["topics"][0]

    assert row["breakdown"] == {
        "new_paper": 1,
        "consensus_updated": 2,
        "contradiction_flagged": 3,
        "paper_retracted": 4,
    }
    assert row["event_count"] == 10


def test_the_personal_window_is_half_open_at_both_ends(db_session):
    """`window_start < detected_at <= now`, pinned on both sides.

    This is the third time on this branch that only one side of a boundary was tested.
    `now` is injectable so the boundary can be hit exactly rather than approximately.
    """
    user = create_anonymous_user(db_session)
    topic = _topic(db_session, "Boundaries")
    _interested(db_session, user, topic)

    now = datetime(2026, 8, 2, 12, 0, 0)
    window_start = now - timedelta(days=7)
    db_session.add(
        ChangeEvent(topic_id=topic.id, event_type=ChangeEventType.NEW_PAPER,
                    detected_at=window_start)
    )
    db_session.add(
        ChangeEvent(topic_id=topic.id, event_type=ChangeEventType.NEW_PAPER, detected_at=now)
    )
    db_session.flush()

    row = personal_topic_summary(db_session, user.id, days=7, now=now)["topics"][0]

    # Exactly window_start is excluded; exactly now is included.
    assert row["event_count"] == 1
