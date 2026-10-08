from datetime import datetime, timedelta

from dashboard.changes import read_change_feed
from evidence_engine.db.models import ChangeEvent, ChangeEventType, Paper, Topic


# Every test in this file drives read_change_feed at a PINNED instant, and dates its
# fixtures relative to it. read_change_feed has no topic filter, so assertions on
# `total_events` or on `days[0]["events"][0]` are assertions about every change event in
# the database inside the window. Dated relative to the real clock, they passed only
# because the test database happened to hold no other recent events -- six stray events
# on one unrelated topic turned this file red during review, and `reset_leaked_state`
# clears such rows for exactly one topic.
#
# Pinning the clock to 2020 is what makes the global assertions true rather than lucky:
# nothing in the corpus is dated then. change_events take their detected_at from insert
# time and the demo seeder dates its history relative to now, so a 2020 window is
# reliably empty of everything except what the test itself puts there.
#
# The alternative -- widening a DELETE to cover all recent change_events -- is the fix
# tests/conftest.py explicitly warns against, because the next step down that road
# destroys real corpus data.
FEED_NOW = datetime(2020, 6, 15, 12, 0, 0)


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


def _ours(feed, topic):
    """Only this topic's events, flattened newest-first.

    The pinned clock above makes a stray *recent* event harmless; this makes a stray event
    dated anywhere harmless, which is the rule tests/conftest.py already prescribes for
    citation_snapshots: scope your own assertions rather than assuming an empty table.
    """
    return [e for day in feed["days"] for e in day["events"] if e["topic"]["id"] == str(topic.id)]


def _our_days(feed, topic):
    """The day buckets that contain this topic's events, in feed order."""
    return [
        day["date"]
        for day in feed["days"]
        if any(e["topic"]["id"] == str(topic.id) for e in day["events"])
    ]


def _require_private_window(feed, topic):
    """For the two tests that genuinely assert on the GLOBAL feed.

    `limit` truncates overall, so "the cap is overall rather than per-day" cannot be
    checked through a topic filter -- the test needs the window to itself. The pinned 2020
    clock normally gives it that; this turns the otherwise-baffling wall of red into one
    sentence naming the cause.
    """
    foreign = [
        e
        for day in feed["days"]
        for e in day["events"]
        if e["topic"]["id"] != str(topic.id)
    ]
    assert not foreign, (
        f"{len(foreign)} change event(s) from other topics fall inside this test's pinned "
        f"window ({FEED_NOW:%Y-%m-%d}); this test asserts on the global feed and needs the "
        "window to itself. Clear them or move FEED_NOW."
    )


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
    now = FEED_NOW
    _event(db_session, topic.id, ChangeEventType.NEW_PAPER, now - timedelta(days=3), paper.id)
    _event(db_session, topic.id, ChangeEventType.PAPER_RETRACTED, now - timedelta(days=1), paper.id)

    feed = read_change_feed(db_session, days=7, limit=50, now=FEED_NOW)

    assert [e["event_type"] for e in _ours(feed, topic)] == ["paper_retracted"]


def test_events_for_a_clean_paper_are_shown(db_session):
    topic = _topic(db_session)
    paper = _paper(db_session, "Anticoagulation in adults over 85", retracted=False)
    _event(db_session, topic.id, ChangeEventType.NEW_PAPER, FEED_NOW - timedelta(days=1),
           paper.id)

    feed = read_change_feed(db_session, days=7, limit=50, now=FEED_NOW)

    ours = _ours(feed, topic)
    assert len(ours) == 1
    assert ours[0]["paper"]["title"] == "Anticoagulation in adults over 85"


def test_an_event_with_no_paper_is_always_included(db_session):
    # consensus_updated events have paper_id NULL (evidence_engine/db/models.py:116), so a
    # filter that joined Paper without accounting for null would drop them entirely.
    topic = _topic(db_session)
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED,
           FEED_NOW - timedelta(days=1))

    feed = read_change_feed(db_session, days=7, limit=50, now=FEED_NOW)

    ours = _ours(feed, topic)
    assert len(ours) == 1
    assert ours[0]["paper"] is None


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
    now = FEED_NOW
    for day in (3, 1, 5, 2):  # middle, newest, oldest, then middle again
        _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED, now - timedelta(days=day))

    feed = read_change_feed(db_session, days=7, limit=50, now=FEED_NOW)

    expected = [(now - timedelta(days=day)).date().isoformat() for day in (1, 2, 3, 5)]
    assert _our_days(feed, topic) == expected


def test_events_within_a_day_are_newest_first(db_session):
    topic = _topic(db_session)
    day = FEED_NOW - timedelta(days=1)
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED, day.replace(hour=3))
    _event(db_session, topic.id, ChangeEventType.CONTRADICTION_FLAGGED, day.replace(hour=9))

    ours = _ours(read_change_feed(db_session, days=7, limit=50, now=FEED_NOW), topic)

    assert ours[0]["event_type"] == "contradiction_flagged"


def test_the_window_excludes_older_events(db_session):
    topic = _topic(db_session)
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED,
           FEED_NOW - timedelta(days=20))

    assert _ours(read_change_feed(db_session, days=7, limit=50, now=FEED_NOW), topic) == []


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
    now = FEED_NOW
    for day in (1, 2, 3):
        for minute in range(4):
            _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED,
                   now - timedelta(days=day, minutes=minute))

    feed = read_change_feed(db_session, days=7, limit=5, now=FEED_NOW)
    _require_private_window(feed, topic)

    assert feed["total_events"] == 5, "the cap was applied per day rather than overall"
    assert len(feed["days"]) == 2, "an overall cap of 5 spans exactly two of the three days"


def test_an_empty_feed_is_not_an_error(db_session):
    # An empty window must answer with the empty shape, not an error and not null -- the
    # widget renders "No change recorded in this period" from it (FR-C-015).
    #
    # This one genuinely asserts on the global feed: "empty" is a statement about the whole
    # window, so it cannot be topic-scoped. The pinned 2020 clock is what makes the window
    # private; the explicit message below is so that a database which does hold events
    # there says so, rather than failing as a mystery inequality.
    feed = read_change_feed(db_session, days=7, limit=50, now=FEED_NOW)

    assert feed == {"days": [], "total_events": 0}, (
        f"the pinned window ({FEED_NOW:%Y-%m-%d}, 7 days) is not empty in this database, so "
        "this test cannot assert emptiness. Clear those events or move FEED_NOW."
    )


def test_each_event_carries_its_topic_label(db_session):
    topic = _topic(db_session, "GLP-1 receptor agonists")
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED,
           FEED_NOW - timedelta(days=1))

    event = _ours(read_change_feed(db_session, days=7, limit=50, now=FEED_NOW), topic)[0]

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
    _event(db_session, topic.id, ChangeEventType.NEW_PAPER, FEED_NOW - timedelta(days=1),
           paper.id)

    event = _ours(read_change_feed(db_session, days=7, limit=50, now=FEED_NOW), topic)[0]

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
    _event(db_session, topic.id, ChangeEventType.NEW_PAPER, FEED_NOW - timedelta(days=1),
           paper.id)

    event = _ours(read_change_feed(db_session, days=7, limit=50, now=FEED_NOW), topic)[0]

    assert event["evidence_tier"] == "established"


def test_the_days_parameter_actually_narrows_the_window(db_session):
    """Every other test calls days=7, so hardcoding timedelta(days=7) survives them all.

    The endpoint accepts days between 1 and 30 and the UI will use it; a cutoff that
    ignores the caller would silently serve a week's feed whatever was asked for.
    """
    topic = _topic(db_session)
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED,
           FEED_NOW - timedelta(days=5))

    assert len(_ours(read_change_feed(db_session, days=7, limit=50, now=FEED_NOW), topic)) == 1
    assert _ours(read_change_feed(db_session, days=3, limit=50, now=FEED_NOW), topic) == []


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
    when = FEED_NOW - timedelta(days=1)
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED, when)

    event = _ours(read_change_feed(db_session, days=7, limit=50, now=FEED_NOW), topic)[0]

    assert event["detected_at"].endswith("Z"), event["detected_at"]
    assert event["detected_at"] == _iso(when)


def _events_for(feed, topic):
    """Only this topic's events.

    read_change_feed has no topic filter, so assertions on `total_events` or on
    `days[0]["events"][0]` are assertions about every change event in the database
    within the window. That holds on an empty test database and fails the moment the
    suite runs anywhere the ingestion pipeline has ever written -- six stray events on
    one unrelated topic turned this file red during review. tests/conftest.py already
    prescribes this rule for citation_snapshots: scope your own assertions rather than
    assuming an empty table.
    """
    return [
        event
        for day in feed["days"]
        for event in day["events"]
        if event["topic"]["id"] == str(topic.id)
    ]


def test_the_change_feed_window_is_half_open_at_its_cutoff(db_session):
    """`cutoff < detected_at <= now`, pinned at both ends.

    This was the one half-open boundary on the branch that no test could reach: the
    clock was read inside read_change_feed, so nothing could place an event exactly on
    the cutoff, and mutating `>` to `>=` survived the whole suite. The convention has
    been got wrong three separate times here, always on one side only.
    """
    topic = _topic(db_session, "Boundary topic")
    now = FEED_NOW
    cutoff = now - timedelta(days=7)
    for label, when in (
        ("on the cutoff", cutoff),
        ("just inside", cutoff + timedelta(microseconds=1)),
        ("on now", now),
        ("just after now", now + timedelta(microseconds=1)),
    ):
        paper = _paper(db_session, f"Paper {label}")
        db_session.add(
            ChangeEvent(
                topic_id=topic.id,
                paper_id=paper.id,
                event_type=ChangeEventType.NEW_PAPER,
                detected_at=when,
            )
        )
    db_session.flush()

    titles = {
        event["paper"]["title"]
        for event in _events_for(read_change_feed(db_session, days=7, limit=50, now=now), topic)
    }

    # Excluded: exactly on the cutoff (half-open at the start).
    assert "Paper on the cutoff" not in titles
    # Included: one microsecond later.
    assert "Paper just inside" in titles
    # Included: exactly now (closed at the end).
    assert "Paper on now" in titles
    # Excluded: one microsecond in the future.
    assert "Paper just after now" not in titles


def test_a_future_dated_event_never_appears(db_session):
    """A clock-skewed ingest or a backfill with a bad date would otherwise sit at the
    top of a recency feed permanently, which is the worst position for a wrong row."""
    topic = _topic(db_session, "Future topic")
    now = FEED_NOW
    paper = _paper(db_session, "Dated next year")
    db_session.add(
        ChangeEvent(
            topic_id=topic.id,
            paper_id=paper.id,
            event_type=ChangeEventType.NEW_PAPER,
            detected_at=now + timedelta(days=365),
        )
    )
    db_session.flush()

    assert _events_for(read_change_feed(db_session, days=7, limit=50, now=now), topic) == []
