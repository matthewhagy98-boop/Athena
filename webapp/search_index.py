import logging
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from evidence_engine.db.models import ChangeEvent, ChangeEventType, Paper, PaperTopic, Score

from webapp.models import PaperSearchIndex, SearchIndexSyncState

logger = logging.getLogger("search_index_sync")

EPOCH = datetime(1970, 1, 1)
_REINDEX_TRIGGER_EVENTS = (ChangeEventType.NEW_PAPER, ChangeEventType.PAPER_RETRACTED)


def _get_or_create_sync_state(session: Session) -> SearchIndexSyncState:
    state = session.execute(select(SearchIndexSyncState)).scalar_one_or_none()
    if state is None:
        state = SearchIndexSyncState(last_synced_at=EPOCH)
        session.add(state)
        session.flush()
    return state


def _reindex_paper(session: Session, paper_id) -> None:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise ValueError(f"Paper {paper_id} not found")

    topic_ids = (
        session.execute(select(PaperTopic.topic_id).where(PaperTopic.paper_id == paper_id)).scalars().all()
    )
    score = session.execute(select(Score).where(Score.paper_id == paper_id)).scalar_one_or_none()
    # A paper scored-but-pending (score.is_pending) has no meaningful tier/study_type yet —
    # exposing the pending row's default/stale value would misrepresent it as scored.
    scored = score is not None and not score.is_pending

    index_row = session.execute(
        select(PaperSearchIndex).where(PaperSearchIndex.paper_id == paper_id)
    ).scalar_one_or_none()
    if index_row is None:
        index_row = PaperSearchIndex(paper_id=paper_id)
        session.add(index_row)

    index_row.topic_ids = list(topic_ids)
    index_row.evidence_tier = score.evidence_tier.value if scored else None
    index_row.study_type = score.study_type.value if scored else None
    index_row.publication_date = paper.pub_date
    index_row.indexed_at = datetime.utcnow()
    session.flush()

    search_text = f"{paper.title} {paper.abstract or ''}"
    session.execute(
        text("UPDATE paper_search_index SET search_vector = to_tsvector('english', :search_text) WHERE id = :id"),
        {"search_text": search_text, "id": index_row.id},
    )


def sync_search_index(session: Session) -> None:
    state = _get_or_create_sync_state(session)
    window_start = state.last_synced_at
    window_end = datetime.utcnow()

    events = (
        session.execute(
            select(ChangeEvent).where(
                ChangeEvent.detected_at > window_start,
                ChangeEvent.detected_at <= window_end,
                ChangeEvent.event_type.in_(_REINDEX_TRIGGER_EVENTS),
            )
        )
        .scalars()
        .all()
    )
    paper_ids = {event.paper_id for event in events if event.paper_id is not None}

    for paper_id in paper_ids:
        try:
            with session.begin_nested():
                _reindex_paper(session, paper_id)
        except Exception:
            logger.exception("Failed to reindex paper %s", paper_id)
            continue

    state.last_synced_at = window_end
    session.flush()
