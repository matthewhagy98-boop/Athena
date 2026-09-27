from datetime import date, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select

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
from webapp.search_index import _reindex_paper, rebuild_search_index, sync_search_index


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

    def flaky_reindex_wrapper(session, paper_id):
        # For the bad paper, call real_reindex but then fail after it does its work
        real_reindex(session, paper_id)
        if paper_id == bad_paper.id:
            raise RuntimeError("boom")

    with patch("webapp.search_index._reindex_paper", side_effect=flaky_reindex_wrapper):
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


# --- rebuild_search_index: the way back from the source table ----------------------
#
# sync_search_index can only ever reindex a paper some event names. These tests pin the
# capability it structurally lacks: recovering an index from `papers` itself.


def _paper_with_no_events(db_session, title: str) -> Paper:
    """A paper that exists but that no ChangeEvent has ever named.

    This is the state `sync_search_index` cannot reach -- deliberately no event, so any
    test using it fails if the rebuild is secretly still reading the event stream.
    """
    paper = Paper(title=title, abstract=f"Abstract for {title}.", pub_date=date(2026, 6, 1))
    db_session.add(paper)
    db_session.flush()
    return paper


def _is_indexed(db_session, paper: Paper) -> bool:
    return (
        db_session.execute(
            select(PaperSearchIndex).where(PaperSearchIndex.paper_id == paper.id)
        ).scalar_one_or_none()
        is not None
    )


def test_rebuild_indexes_a_paper_no_event_has_ever_named(db_session):
    """The core capability. A paper with no NEW_PAPER event is invisible to the
    incremental sync forever; the rebuild indexes it because it is in `papers`."""
    paper = _paper_with_no_events(db_session, "A paper that no change event mentions")

    sync_search_index(db_session)
    assert not _is_indexed(db_session, paper), "precondition: the event-driven sync cannot see it"

    indexed = rebuild_search_index(db_session)

    assert _is_indexed(db_session, paper)
    assert indexed >= 1


def test_rebuild_repairs_a_truncated_index_whose_watermark_is_current(db_session):
    """The trap that made this function necessary.

    An index truncated while its watermark row survives cannot be repaired by
    `sync_search_index` at any cost: every event predates the window, so it walks an
    empty event set and reports success over an empty index.
    """
    topic = Topic(canonical_label="Rebuild topic", mesh_id="D_REBUILD")
    db_session.add(topic)
    db_session.flush()
    paper = _paper_with_no_events(db_session, "Indexed, then truncated out from under us")
    db_session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
    db_session.add(
        ChangeEvent(
            topic_id=topic.id,
            paper_id=paper.id,
            event_type=ChangeEventType.NEW_PAPER,
            detected_at=datetime.utcnow(),
        )
    )
    db_session.flush()
    sync_search_index(db_session)
    assert _is_indexed(db_session, paper)

    # Exactly what reset_leaked_state leaves behind: rows gone, watermark current.
    db_session.execute(delete(PaperSearchIndex))
    db_session.flush()
    sync_search_index(db_session)
    assert not _is_indexed(db_session, paper), "precondition: the sync reports success over the hole"

    rebuild_search_index(db_session)

    assert _is_indexed(db_session, paper)


def test_rebuild_leaves_the_watermark_at_scan_start_so_a_concurrent_event_is_not_skipped(db_session):
    """A paper created while the rebuild is running is not in its scan, so the rebuild
    must leave the watermark behind that paper's event rather than in front of it.

    Setting the watermark to the finish time would place a mid-scan event before the next
    sync's window and strand that paper permanently -- the same class of hole the rebuild
    exists to repair, reintroduced by the repair itself.
    """
    _paper_with_no_events(db_session, "Just something for the scan to iterate over")
    topic = Topic(canonical_label="Concurrent topic", mesh_id="D_CONCURRENT")
    db_session.add(topic)
    db_session.flush()

    latecomer: dict[str, Paper] = {}
    real_reindex = _reindex_paper

    def reindex_then_land_a_new_paper(session, paper_id):
        real_reindex(session, paper_id)
        if latecomer:
            return
        # Arrives mid-scan: after started_at, before the rebuild finishes.
        paper = Paper(title="Landed mid-rebuild", abstract="...", pub_date=date(2026, 6, 2))
        session.add(paper)
        session.flush()
        session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
        session.add(
            ChangeEvent(
                topic_id=topic.id,
                paper_id=paper.id,
                event_type=ChangeEventType.NEW_PAPER,
                detected_at=datetime.utcnow(),
            )
        )
        session.flush()
        latecomer["paper"] = paper

    with patch("webapp.search_index._reindex_paper", side_effect=reindex_then_land_a_new_paper):
        rebuild_search_index(db_session)

    assert latecomer, "the test did not actually land a paper mid-scan"
    # The rebuild's own scan could not have covered it, so this is the watermark's doing.
    sync_search_index(db_session)
    assert _is_indexed(db_session, latecomer["paper"])


def test_rebuild_raises_and_holds_the_watermark_when_a_paper_fails(db_session):
    """A rebuild must never report success over a partial index -- that is the failure it
    exists to undo. It is the opposite tradeoff from `sync_search_index`, which skips a
    bad paper on purpose because a later event will retry it. A rebuild has no later
    event."""
    good = _paper_with_no_events(db_session, "Reindexes fine")
    bad = _paper_with_no_events(db_session, "Blows up on reindex")
    state = db_session.execute(select(SearchIndexSyncState)).scalar_one_or_none()
    if state is None:
        sync_search_index(db_session)
        state = db_session.execute(select(SearchIndexSyncState)).scalar_one()
    watermark_before = state.last_synced_at

    real_reindex = _reindex_paper

    def blow_up_on_one(session, paper_id):
        if paper_id == bad.id:
            raise RuntimeError("boom")
        real_reindex(session, paper_id)

    with patch("webapp.search_index._reindex_paper", side_effect=blow_up_on_one):
        with pytest.raises(RuntimeError, match="Rebuild failed for 1 of"):
            rebuild_search_index(db_session)

    db_session.refresh(state)
    assert state.last_synced_at == watermark_before
    assert _is_indexed(db_session, good), "the papers that did succeed are still written"
    assert not _is_indexed(db_session, bad)
