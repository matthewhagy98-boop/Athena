import uuid
from datetime import date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from digest.profiles import create_user
from evidence_engine.db.models import Paper
from webapp.models import PaperSearchIndex, SavedSearch, SearchIndexSyncState


def test_paper_search_index_round_trip(db_session):
    paper = Paper(title="A trial of drug X")
    db_session.add(paper)
    db_session.flush()

    index_row = PaperSearchIndex(
        paper_id=paper.id,
        topic_ids=[uuid.uuid4()],
        evidence_tier="established",
        study_type="rct",
        publication_date=date(2026, 1, 1),
    )
    db_session.add(index_row)
    db_session.flush()

    fetched = db_session.execute(
        select(PaperSearchIndex).where(PaperSearchIndex.paper_id == paper.id)
    ).scalar_one()
    assert fetched.evidence_tier == "established"
    assert fetched.study_type == "rct"
    assert fetched.publication_date == date(2026, 1, 1)
    assert fetched.search_vector is None


def test_paper_search_index_unique_constraint_on_paper_id(db_session):
    paper = Paper(title="Another trial")
    db_session.add(paper)
    db_session.flush()

    db_session.add(PaperSearchIndex(paper_id=paper.id))
    db_session.flush()

    db_session.add(PaperSearchIndex(paper_id=paper.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_search_index_sync_state_round_trip(db_session):
    state = SearchIndexSyncState(last_synced_at=datetime(2026, 7, 1))
    db_session.add(state)
    db_session.flush()

    fetched = db_session.get(SearchIndexSyncState, state.id)
    assert fetched.last_synced_at == datetime(2026, 7, 1)


def test_saved_search_round_trip(db_session):
    user = create_user(db_session, "searcher@example.com")

    saved = SavedSearch(
        user_id=user.id,
        name="Strong RCTs on X",
        query_params={"q": "drug X", "tier": "established"},
    )
    db_session.add(saved)
    db_session.flush()

    fetched = db_session.get(SavedSearch, saved.id)
    assert fetched.name == "Strong RCTs on X"
    assert fetched.query_params == {"q": "drug X", "tier": "established"}
    assert fetched.last_run_at is None
