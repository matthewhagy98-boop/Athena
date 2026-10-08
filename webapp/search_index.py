import logging
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from evidence_engine.db.models import ChangeEvent, ChangeEventType, Paper, PaperTopic, Score

from webapp.models import PaperSearchIndex, SearchIndexSyncState

logger = logging.getLogger("search_index_sync")

EPOCH = datetime(1970, 1, 1)
_REINDEX_TRIGGER_EVENTS = (ChangeEventType.NEW_PAPER, ChangeEventType.PAPER_RETRACTED)


def _get_or_create_sync_state(session: Session) -> SearchIndexSyncState:
    """The single watermark row, created on first use.

    The create path is an upsert against the singleton index added in e5a71c8d9f20,
    rather than the select-then-insert it used to be. That raced: two processes starting
    sync on a database with no row both selected nothing, both inserted, and from then on
    every call raised MultipleResultsFound -- search indexing permanently broken until
    someone deleted a row by hand. Reproduced before fixing; it needs a fresh database and
    two processes starting together, which is a first deploy or a restored backup
    reindexed in parallel.

    `ON CONFLICT DO NOTHING` then re-select, rather than catching IntegrityError: a
    conflict here is the ordinary outcome of a second caller, not an error, and letting
    the exception escape would abort the caller's transaction.

    The constraint is what prevents the permanent breakage; this upsert only turns a lost
    run into a clean one. Its cross-session path is not covered by the suite -- that
    ordering needs two interleaved transactions, which a single test transaction cannot
    reach -- and was verified by a two-process probe. The test alongside it says so rather
    than implying coverage it does not have.
    """
    state = session.execute(select(SearchIndexSyncState)).scalar_one_or_none()
    if state is not None:
        return state

    session.execute(
        pg_insert(SearchIndexSyncState)
        .values(last_synced_at=EPOCH)
        .on_conflict_do_nothing()
    )
    session.flush()
    return session.execute(select(SearchIndexSyncState)).scalar_one()


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


def rebuild_search_index(session: Session) -> int:
    """Reindex every paper from `papers`, ignoring the event stream entirely.

    `sync_search_index` is incremental and event-driven: it reindexes a paper only when a
    `NEW_PAPER` or `PAPER_RETRACTED` event names it inside the window after
    `last_synced_at`. That is what makes it cheap, and it is also why it cannot repair
    itself. Once index rows are lost -- truncated by a test fixture, dropped by a bad
    migration, corrupted -- no future event names those papers again, so they stay
    unsearchable forever. The sharper edge is that an empty index whose watermark is
    current makes the incremental sync walk an empty event set and report success over
    the hole.

    This is the way back from the source table: a paper is indexed here because it
    exists, not because something happened to it. It is the general form of the
    workaround `scripts/seed_demo_data.py` needed to keep the demo searchable.

    Returns the number of papers indexed. Raises if any paper failed rather than
    advancing the watermark over a partial index -- reporting success over an incomplete
    rebuild is the exact failure this function exists to undo. `sync_search_index` makes
    the opposite tradeoff deliberately: it skips a failed paper so one bad row cannot
    stall the incremental stream, and the next event naming that paper retries it. A
    rebuild has no next event to fall back on.
    """
    started_at = datetime.utcnow()
    state = _get_or_create_sync_state(session)

    paper_ids = session.execute(select(Paper.id)).scalars().all()

    failed = 0
    for paper_id in paper_ids:
        try:
            with session.begin_nested():
                _reindex_paper(session, paper_id)
        except Exception:
            logger.exception("Failed to reindex paper %s", paper_id)
            failed += 1

    if failed:
        raise RuntimeError(
            f"Rebuild failed for {failed} of {len(paper_ids)} papers; the watermark was not "
            "advanced. See the logged exceptions for the per-paper causes."
        )

    # The time the scan STARTED, not the time it finished. A paper created while the
    # rebuild was running was not in `paper_ids`, so its event still has to be picked up
    # by the next incremental sync; a finish-time watermark would place that event before
    # the next window and strand the paper exactly the way this function exists to
    # prevent. Reprocessing a few events is free -- `_reindex_paper` upserts.
    state.last_synced_at = started_at
    session.flush()
    logger.info("Rebuilt search index from source: %d papers", len(paper_ids))
    return len(paper_ids)


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
