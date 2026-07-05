import uuid

import pytest

from digest.profiles import create_user
from evidence_engine.db.models import Paper, PaperTopic, Topic
from webapp.saved_searches import (
    create_saved_search,
    delete_saved_search,
    list_saved_searches,
    run_saved_search,
)


def test_create_and_list_saved_searches(db_session):
    user = create_user(db_session, "searcher@example.com")

    create_saved_search(db_session, user, "My Search", {"q": "hypertension"})
    create_saved_search(db_session, user, "My Search", {"q": "diabetes"})

    searches = list_saved_searches(db_session, user)
    assert len(searches) == 2
    assert {s.name for s in searches} == {"My Search"}


def test_delete_saved_search_removes_it(db_session):
    user = create_user(db_session, "searcher2@example.com")
    saved = create_saved_search(db_session, user, "Temp Search", {"q": "x"})

    delete_saved_search(db_session, user, saved.id)

    assert list_saved_searches(db_session, user) == []


def test_delete_saved_search_raises_when_not_owned_by_user(db_session):
    owner = create_user(db_session, "owner@example.com")
    other = create_user(db_session, "other@example.com")
    saved = create_saved_search(db_session, owner, "Owner's Search", {"q": "x"})

    with pytest.raises(ValueError):
        delete_saved_search(db_session, other, saved.id)


def test_delete_saved_search_raises_when_not_found(db_session):
    user = create_user(db_session, "searcher3@example.com")

    with pytest.raises(ValueError):
        delete_saved_search(db_session, user, uuid.uuid4())


def test_run_saved_search_executes_stored_query_and_updates_last_run_at(db_session):
    user = create_user(db_session, "searcher4@example.com")
    topic = Topic(canonical_label="Search Topic", mesh_id="D000001")
    db_session.add(topic)
    db_session.flush()
    paper = Paper(title="A matching paper")
    db_session.add(paper)
    db_session.flush()
    db_session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
    db_session.flush()

    from webapp.search_index import sync_search_index
    from evidence_engine.db.models import ChangeEvent, ChangeEventType
    from datetime import datetime

    db_session.add(
        ChangeEvent(topic_id=topic.id, paper_id=paper.id, event_type=ChangeEventType.NEW_PAPER, detected_at=datetime(2026, 6, 1))
    )
    db_session.flush()
    sync_search_index(db_session)

    saved = create_saved_search(db_session, user, "Topic Search", {"topic_id": str(topic.id)})

    page = run_saved_search(db_session, user, saved.id)

    assert page.total == 1
    fetched = list_saved_searches(db_session, user)[0]
    assert fetched.last_run_at is not None


def test_run_saved_search_raises_when_not_owned_by_user(db_session):
    owner = create_user(db_session, "owner2@example.com")
    other = create_user(db_session, "other2@example.com")
    saved = create_saved_search(db_session, owner, "Owner's Search", {"q": "x"})

    with pytest.raises(ValueError):
        run_saved_search(db_session, other, saved.id)


def test_run_saved_search_filters_by_date_range_stored_as_iso_strings(db_session):
    from datetime import date, datetime
    from webapp.search_index import sync_search_index
    from evidence_engine.db.models import ChangeEvent, ChangeEventType

    user = create_user(db_session, "date_searcher@example.com")

    # Create a topic
    topic = Topic(canonical_label="Date Filter Topic", mesh_id="D000999")
    db_session.add(topic)
    db_session.flush()

    # Create two papers with different publication dates
    # Paper 1: Inside the target range (2026-02-15)
    paper_in_range = Paper(title="Paper in date range", pub_date=date(2026, 2, 15))
    db_session.add(paper_in_range)
    db_session.flush()
    db_session.add(PaperTopic(paper_id=paper_in_range.id, topic_id=topic.id))
    db_session.flush()

    # Paper 2: Outside the target range (2026-04-01)
    paper_out_of_range = Paper(title="Paper outside date range", pub_date=date(2026, 4, 1))
    db_session.add(paper_out_of_range)
    db_session.flush()
    db_session.add(PaperTopic(paper_id=paper_out_of_range.id, topic_id=topic.id))
    db_session.flush()

    # Add ChangeEvents for both papers so they get indexed
    db_session.add(
        ChangeEvent(
            topic_id=topic.id,
            paper_id=paper_in_range.id,
            event_type=ChangeEventType.NEW_PAPER,
            detected_at=datetime(2026, 6, 1),
        )
    )
    db_session.add(
        ChangeEvent(
            topic_id=topic.id,
            paper_id=paper_out_of_range.id,
            event_type=ChangeEventType.NEW_PAPER,
            detected_at=datetime(2026, 6, 1),
        )
    )
    db_session.flush()

    # Sync the search index to pick up both papers
    sync_search_index(db_session)

    # Create a saved search with ISO-format date strings (how they're stored as JSONB)
    # Target range: 2026-02-01 to 2026-03-31
    # Paper 1 (2026-02-15) is IN this range
    # Paper 2 (2026-04-01) is OUT of this range
    saved = create_saved_search(
        db_session,
        user,
        "Date Range Search",
        {
            "topic_id": str(topic.id),
            "date_from": "2026-02-01",
            "date_to": "2026-03-31",
        },
    )

    # Run the saved search - this will parse the ISO strings back to date objects
    page = run_saved_search(db_session, user, saved.id)

    # Assert that only the in-range paper is returned
    assert page.total == 1, f"Expected 1 paper in date range, got {page.total}"
    assert len(page.rows) == 1
    assert page.rows[0].paper.id == paper_in_range.id
