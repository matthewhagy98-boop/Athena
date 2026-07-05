from datetime import date, datetime
from unittest.mock import patch

from sqlalchemy import select

from evidence_engine.db.models import (
    ChangeEvent,
    ChangeEventType,
    EvidenceTier,
    Paper,
    PaperTopic,
    Score,
    StudyType,
    Topic,
)
from webapp.models import PaperSearchIndex, SearchIndexSyncState
from webapp.search_index import sync_search_index


def test_sync_search_index_indexes_new_paper_and_advances_watermark(db_session):
    topic = Topic(canonical_label="Hypertension", mesh_id="D006973")
    db_session.add(topic)
    db_session.flush()

    paper = Paper(
        title="A large RCT of drug Y",
        abstract="Randomized trial in hypertensive patients.",
        pub_date=date(2026, 6, 1),
    )
    db_session.add(paper)
    db_session.flush()
    db_session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
    db_session.add(
        Score(
            paper_id=paper.id,
            study_type=StudyType.RCT,
            evidence_tier=EvidenceTier.ESTABLISHED,
            final_score=80.0,
            model_version="v1",
        )
    )
    db_session.add(
        ChangeEvent(
            topic_id=topic.id, paper_id=paper.id, event_type=ChangeEventType.NEW_PAPER, detected_at=datetime(2026, 6, 2)
        )
    )
    db_session.flush()

    sync_search_index(db_session)

    index_row = db_session.execute(
        select(PaperSearchIndex).where(PaperSearchIndex.paper_id == paper.id)
    ).scalar_one()
    assert index_row.evidence_tier == "established"
    assert index_row.study_type == "rct"
    assert index_row.topic_ids == [topic.id]
    assert index_row.publication_date == date(2026, 6, 1)

    state = db_session.execute(select(SearchIndexSyncState)).scalar_one()
    assert state.last_synced_at > datetime(2026, 6, 2)


def test_sync_search_index_only_processes_events_since_watermark(db_session):
    db_session.add(SearchIndexSyncState(last_synced_at=datetime(2026, 6, 5)))
    db_session.flush()

    topic = Topic(canonical_label="Old Topic", mesh_id="D000099")
    db_session.add(topic)
    db_session.flush()
    old_paper = Paper(title="An old paper")
    db_session.add(old_paper)
    db_session.flush()
    db_session.add(
        ChangeEvent(
            topic_id=topic.id,
            paper_id=old_paper.id,
            event_type=ChangeEventType.NEW_PAPER,
            detected_at=datetime(2026, 6, 1),
        )
    )
    db_session.flush()

    sync_search_index(db_session)

    assert (
        db_session.execute(
            select(PaperSearchIndex).where(PaperSearchIndex.paper_id == old_paper.id)
        ).scalar_one_or_none()
        is None
    )


def test_sync_search_index_leaves_tier_and_study_type_null_for_pending_score(db_session):
    topic = Topic(canonical_label="Pending Topic", mesh_id="D000102")
    db_session.add(topic)
    db_session.flush()
    paper = Paper(title="A paper awaiting rescoring")
    db_session.add(paper)
    db_session.flush()
    db_session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
    db_session.add(
        Score(
            paper_id=paper.id,
            study_type=StudyType.RCT,
            evidence_tier=EvidenceTier.SPECULATIVE,
            final_score=0.0,
            model_version="v1",
            is_pending=True,
        )
    )
    db_session.add(
        ChangeEvent(
            topic_id=topic.id, paper_id=paper.id, event_type=ChangeEventType.NEW_PAPER, detected_at=datetime(2026, 6, 2)
        )
    )
    db_session.flush()

    sync_search_index(db_session)

    index_row = db_session.execute(
        select(PaperSearchIndex).where(PaperSearchIndex.paper_id == paper.id)
    ).scalar_one()
    assert index_row.evidence_tier is None
    assert index_row.study_type is None


def test_sync_search_index_reindexes_retracted_paper(db_session):
    topic = Topic(canonical_label="Retraction Topic", mesh_id="D000100")
    db_session.add(topic)
    db_session.flush()
    paper = Paper(title="A paper that gets retracted", is_retracted=True)
    db_session.add(paper)
    db_session.flush()
    db_session.add(
        ChangeEvent(
            topic_id=topic.id,
            paper_id=paper.id,
            event_type=ChangeEventType.PAPER_RETRACTED,
            detected_at=datetime(2026, 6, 3),
        )
    )
    db_session.flush()

    sync_search_index(db_session)

    index_row = db_session.execute(
        select(PaperSearchIndex).where(PaperSearchIndex.paper_id == paper.id)
    ).scalar_one_or_none()
    assert index_row is not None


def test_sync_search_index_isolates_per_paper_failure_and_still_advances_watermark(db_session):
    topic = Topic(canonical_label="Mixed Topic", mesh_id="D000101")
    db_session.add(topic)
    db_session.flush()
    good_paper = Paper(title="A good paper")
    bad_paper = Paper(title="A problematic paper")
    db_session.add_all([good_paper, bad_paper])
    db_session.flush()
    db_session.add_all(
        [
            ChangeEvent(
                topic_id=topic.id,
                paper_id=good_paper.id,
                event_type=ChangeEventType.NEW_PAPER,
                detected_at=datetime(2026, 6, 4),
            ),
            ChangeEvent(
                topic_id=topic.id,
                paper_id=bad_paper.id,
                event_type=ChangeEventType.NEW_PAPER,
                detected_at=datetime(2026, 6, 4),
            ),
        ]
    )
    db_session.flush()

    from webapp.search_index import _reindex_paper as real_reindex

    def flaky_reindex(session, paper_id):
        if paper_id == bad_paper.id:
            raise RuntimeError("boom")
        return real_reindex(session, paper_id)

    with patch("webapp.search_index._reindex_paper", side_effect=flaky_reindex):
        sync_search_index(db_session)

    assert (
        db_session.execute(
            select(PaperSearchIndex).where(PaperSearchIndex.paper_id == good_paper.id)
        ).scalar_one_or_none()
        is not None
    )
    assert (
        db_session.execute(
            select(PaperSearchIndex).where(PaperSearchIndex.paper_id == bad_paper.id)
        ).scalar_one_or_none()
        is None
    )
    state = db_session.execute(select(SearchIndexSyncState)).scalar_one()
    assert state.last_synced_at > datetime(2026, 6, 4)
