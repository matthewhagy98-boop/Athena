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
    # Seeded in deliberately scrambled order, and asserted against the exact expected
    # sequence rather than against sorted(dates, reverse=True).
    #
    # The original seeded two days in ascending order and asserted the result was sorted.
    # Removing the ORDER BY from the query left it passing -- verified empirically, not
    # argued -- because with two rows inserted oldest-first, Postgres happened to return
    # them in an order the assertion accepted. Comparing a list to its own sorted form
    # can only fail if the list is unsorted, which is a weaker claim than "these dates,
    # in this order".
    topic = _topic(db_session)
    now = datetime.utcnow()
    for day in (3, 1, 5, 2):  # middle, newest, oldest, then middle again
        _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED, now - timedelta(days=day))

    feed = read_change_feed(db_session, days=7, limit=50)

    expected = [(now - timedelta(days=day)).date().isoformat() for day in (1, 2, 3, 5)]
    assert [d["date"] for d in feed["days"]] == expected
    assert len(feed["days"]) == 4


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
    #
    # Events must span SEVERAL days to tell the two rules apart. With everything on one
    # day -- as this test originally seeded it -- an overall cap of 4 and a per-day cap
    # of 4 produce the identical number, so the test could not detect the behaviour it
    # names. Twelve events over three days with limit=5 separates them: an overall cap
    # returns 5 events across 2 days, a per-day cap returns all 12 across 3.
    topic = _topic(db_session)
    now = datetime.utcnow()
    for day in (1, 2, 3):
        for minute in range(4):
            _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED,
                   now - timedelta(days=day, minutes=minute))

    feed = read_change_feed(db_session, days=7, limit=5)

    assert feed["total_events"] == 5, "the cap was applied per day rather than overall"
    assert len(feed["days"]) == 2, "an overall cap of 5 spans exactly two of the three days"


def test_an_empty_feed_is_not_an_error(db_session):
    assert read_change_feed(db_session, days=7, limit=50) == {"days": [], "total_events": 0}


def test_each_event_carries_its_topic_label(db_session):
    topic = _topic(db_session, "GLP-1 receptor agonists")
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED,
           datetime.utcnow() - timedelta(days=1))

    event = read_change_feed(db_session, days=7, limit=50)["days"][0]["events"][0]

    assert event["topic"]["canonical_label"] == "GLP-1 receptor agonists"
    assert event["topic"]["id"] == str(topic.id)


def test_a_pending_score_is_not_surfaced_as_an_evidence_tier(db_session):
    """A pending Score is not a score.

    Score rows are created with is_pending=True before scoring completes, carrying column
    defaults -- evidence_tier='speculative', final_score=0.0. Surfacing those labels an
    unscored paper as speculative evidence, which is a claim about the work that nobody
    made. Sub-project A shipped exactly this defect once; webapp/search_index.py carries
    the same rule.

    Nothing covered it here: dropping the is_pending guard passed all nine other tests,
    because no fixture had a Score at all.
    """
    from evidence_engine.db.models import EvidenceTier, Score, StudyType

    topic = _topic(db_session)
    paper = _paper(db_session, "Freshly ingested, not yet scored")
    db_session.add(
        Score(
            paper_id=paper.id,
            evidence_tier=EvidenceTier.SPECULATIVE,  # the column default, not a judgement
            study_type=StudyType.UNKNOWN,
            final_score=0.0,
            is_pending=True,
            model_version="v1",
        )
    )
    db_session.flush()
    _event(db_session, topic.id, ChangeEventType.NEW_PAPER, datetime.utcnow() - timedelta(days=1),
           paper.id)

    event = read_change_feed(db_session, days=7, limit=50)["days"][0]["events"][0]

    assert event["evidence_tier"] is None, (
        "a pending Score's placeholder tier reached the feed as though it were a real one"
    )


def test_a_settled_score_is_surfaced(db_session):
    # The complement: the guard must not suppress a real tier, or the feed would never
    # show one at all and the test above would pass vacuously.
    from evidence_engine.db.models import EvidenceTier, Score, StudyType

    topic = _topic(db_session)
    paper = _paper(db_session, "Scored")
    db_session.add(
        Score(
            paper_id=paper.id,
            evidence_tier=EvidenceTier.ESTABLISHED,
            study_type=StudyType.RCT,
            final_score=80.0,
            is_pending=False,
            model_version="v1",
        )
    )
    db_session.flush()
    _event(db_session, topic.id, ChangeEventType.NEW_PAPER, datetime.utcnow() - timedelta(days=1),
           paper.id)

    event = read_change_feed(db_session, days=7, limit=50)["days"][0]["events"][0]

    assert event["evidence_tier"] == "established"


def test_the_days_parameter_actually_narrows_the_window(db_session):
    """Every other test calls days=7, so hardcoding timedelta(days=7) survives them all.

    The endpoint accepts days between 1 and 30 and the UI will use it; a cutoff that
    ignores the caller would silently serve a week's feed whatever was asked for.
    """
    topic = _topic(db_session)
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED,
           datetime.utcnow() - timedelta(days=5))

    assert read_change_feed(db_session, days=7, limit=50)["total_events"] == 1
    assert read_change_feed(db_session, days=3, limit=50)["total_events"] == 0


def test_timestamps_carry_an_explicit_utc_offset(db_session):
    """The Z suffix, which had no direct coverage anywhere in this module.

    Every timestamp here is naive UTC, and a bare isoformat() emits no offset. JavaScript
    parses an offset-less date-time as LOCAL time, so the whole feed would shift by the
    viewer's UTC offset -- filing events under the wrong day heading for anyone west of
    UTC. dashboard.activity._iso exists for this, and reimplementing the timestamp inline
    without it would have passed every other test in this file.
    """
    from dashboard.activity import _iso

    topic = _topic(db_session)
    when = datetime.utcnow() - timedelta(days=1)
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED, when)

    event = read_change_feed(db_session, days=7, limit=50)["days"][0]["events"][0]

    assert event["detected_at"].endswith("Z"), event["detected_at"]
    assert event["detected_at"] == _iso(when)
