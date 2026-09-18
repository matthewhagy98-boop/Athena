from datetime import datetime, timedelta

from dashboard.changes import read_change_feed
from evidence_engine.db.models import ChangeEvent, ChangeEventType, Paper, Topic


def _topic(db_session, label="Atrial fibrillation"):
    topic = Topic(canonical_label=label)
    db_session.add(topic)
    db_session.flush()
    return topic


def _paper(db_session, title, retracted=False):
    paper = Paper(title=title, is_retracted=retracted)
    db_session.add(paper)
    db_session.flush()
    return paper


def _event(db_session, topic_id, event_type, when, paper_id=None):
    db_session.add(
        ChangeEvent(topic_id=topic_id, paper_id=paper_id, event_type=event_type, detected_at=when)
    )
    db_session.flush()


def test_new_paper_event_for_retracted_paper_hidden_but_retraction_event_shown(db_session):
    # Paper P is retracted. Its earlier "new paper" event must disappear -- continuing to
    # advertise it as new evidence is the harm. Its retraction event must remain, and
    # prominently, because that is the thing a researcher needs to know.
    topic = _topic(db_session)
    paper = _paper(db_session, "Weight outcomes in a retrospective cohort", retracted=True)
    now = datetime.utcnow()
    _event(db_session, topic.id, ChangeEventType.NEW_PAPER, now - timedelta(days=3), paper.id)
    _event(db_session, topic.id, ChangeEventType.PAPER_RETRACTED, now - timedelta(days=1), paper.id)

    feed = read_change_feed(db_session, days=7, limit=50)
    types = [e["event_type"] for day in feed["days"] for e in day["events"]]

    assert types == ["paper_retracted"]
    assert feed["total_events"] == 1


def test_events_for_a_clean_paper_are_shown(db_session):
    topic = _topic(db_session)
    paper = _paper(db_session, "Anticoagulation in adults over 85", retracted=False)
    _event(db_session, topic.id, ChangeEventType.NEW_PAPER, datetime.utcnow() - timedelta(days=1),
           paper.id)

    feed = read_change_feed(db_session, days=7, limit=50)

    assert feed["total_events"] == 1
    assert feed["days"][0]["events"][0]["paper"]["title"] == "Anticoagulation in adults over 85"


def test_an_event_with_no_paper_is_always_included(db_session):
    # consensus_updated events have paper_id NULL (evidence_engine/db/models.py:116), so a
    # filter that joined Paper without accounting for null would drop them entirely.
    topic = _topic(db_session)
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED,
           datetime.utcnow() - timedelta(days=1))

    feed = read_change_feed(db_session, days=7, limit=50)

    assert feed["total_events"] == 1
    assert feed["days"][0]["events"][0]["paper"] is None


def test_events_are_grouped_by_day_newest_first(db_session):
    topic = _topic(db_session)
    now = datetime.utcnow()
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED, now - timedelta(days=3))
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED, now - timedelta(days=1))

    feed = read_change_feed(db_session, days=7, limit=50)

    dates = [day["date"] for day in feed["days"]]
    assert dates == sorted(dates, reverse=True)
    assert len(feed["days"]) == 2


def test_events_within_a_day_are_newest_first(db_session):
    topic = _topic(db_session)
    day = datetime.utcnow() - timedelta(days=1)
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED, day.replace(hour=3))
    _event(db_session, topic.id, ChangeEventType.CONTRADICTION_FLAGGED, day.replace(hour=9))

    events = read_change_feed(db_session, days=7, limit=50)["days"][0]["events"]

    assert events[0]["event_type"] == "contradiction_flagged"


def test_the_window_excludes_older_events(db_session):
    topic = _topic(db_session)
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED,
           datetime.utcnow() - timedelta(days=20))

    assert read_change_feed(db_session, days=7, limit=50)["total_events"] == 0


def test_limit_truncates_the_most_recent_events_overall(db_session):
    # The cap is on total events, not per day: the feed is a recency window, not a
    # browsable archive, so truncating per day would hide a busy day's newest items.
    topic = _topic(db_session)
    now = datetime.utcnow()
    for index in range(6):
        _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED,
               now - timedelta(days=1, minutes=index))

    feed = read_change_feed(db_session, days=7, limit=4)

    assert feed["total_events"] == 4


def test_an_empty_feed_is_not_an_error(db_session):
    assert read_change_feed(db_session, days=7, limit=50) == {"days": [], "total_events": 0}


def test_each_event_carries_its_topic_label(db_session):
    topic = _topic(db_session, "GLP-1 receptor agonists")
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED,
           datetime.utcnow() - timedelta(days=1))

    event = read_change_feed(db_session, days=7, limit=50)["days"][0]["events"][0]

    assert event["topic"]["canonical_label"] == "GLP-1 receptor agonists"
    assert event["topic"]["id"] == str(topic.id)
