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
