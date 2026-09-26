"""The seeder's promise: after it runs, every demo paper is searchable.

`main`'s docstring and its own console message both claim the search index is rebuilt on
every run, precisely because `reset_leaked_state` truncates `paper_search_index`. These
tests hold it to that claim, which it could not previously keep.
"""

from datetime import datetime

from sqlalchemy import delete, select

from evidence_engine.db.models import ChangeEvent, Paper, PaperTopic, Topic
from scripts.seed_demo_data import DEMO_TOPIC, PAPERS, main
from webapp.models import PaperSearchIndex, SearchIndexSyncState


def _run_seeder(db_session, monkeypatch, argv=None):
    """Run the seeder inside the test transaction.

    commit becomes flush and close a no-op, matching
    tests/scripts/test_refresh_dashboard_activity.py, so the seeder's committed writes
    stay inside `db_session`'s transaction and roll back with it.
    """
    import scripts.seed_demo_data as seeder

    monkeypatch.setattr(seeder, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "commit", db_session.flush)
    monkeypatch.setattr(db_session, "close", lambda: None)
    main(argv or [])


def _demo_paper_ids(db_session) -> list:
    topic = db_session.execute(select(Topic).where(Topic.canonical_label == DEMO_TOPIC)).scalar_one()
    return list(
        db_session.execute(select(PaperTopic.paper_id).where(PaperTopic.topic_id == topic.id))
        .scalars()
        .all()
    )


def _unindexed_demo_titles(db_session) -> list[str]:
    indexed = set(db_session.execute(select(PaperSearchIndex.paper_id)).scalars().all())
    titles = []
    for paper_id in _demo_paper_ids(db_session):
        if paper_id not in indexed:
            titles.append(db_session.get(Paper, paper_id).title)
    return sorted(titles)


def _simulate_a_completed_test_run(db_session) -> None:
    """Reproduce the state `reset_leaked_state` leaves behind.

    It deletes every `change_events` row for the demo topic (so the seeder's 9 weeks of
    dashboard history cannot pollute another test's recency window) and truncates
    `paper_search_index` and `search_index_sync_state`. The demo topic, its papers and
    its scores survive. This is the state in which `npm run e2e` runs, every time.
    """
    topic = db_session.execute(select(Topic).where(Topic.canonical_label == DEMO_TOPIC)).scalar_one()
    db_session.execute(delete(ChangeEvent).where(ChangeEvent.topic_id == topic.id))
    db_session.execute(delete(PaperSearchIndex))
    db_session.execute(delete(SearchIndexSyncState))
    db_session.flush()


def test_one_seeder_run_leaves_every_demo_paper_searchable(db_session, monkeypatch):
    # Deliberately makes no assumption about the starting state. The demo topic is
    # committed by design and survives `reset_leaked_state`, so on a developer machine
    # this exercises the already-present branch; on a truly empty database it exercises
    # the first-seed branch. Either way one run must leave the demo searchable.
    _run_seeder(db_session, monkeypatch)

    assert _unindexed_demo_titles(db_session) == []


def test_reseeding_reindexes_every_demo_paper_after_a_test_run(db_session, monkeypatch):
    """The regression. `sync_search_index` indexes a paper only when a `NEW_PAPER` (or
    `PAPER_RETRACTED`) `ChangeEvent` names it, and there is no full-rebuild path.

    `_seed_dashboard_history` rebuilds events by walking `papers[n % 4]` against three
    event types at `[n % 3]`, which never pairs `PAPERS[1]` with `NEW_PAPER` -- so after
    `reset_leaked_state` has removed the first-seed anchors, re-seeding restored three of
    the four papers and reported success. The missing one is
    "Cognitive offloading and digital tool interaction", which is exactly the paper
    `e2e/smoke.spec.ts` checks, so `npm run e2e` timed out after any pytest run and
    re-running the seeder could not fix it.
    """
    _run_seeder(db_session, monkeypatch)
    _simulate_a_completed_test_run(db_session)

    _run_seeder(db_session, monkeypatch)

    assert _unindexed_demo_titles(db_session) == []


def test_reseeding_recovers_when_the_sync_watermark_is_already_current(db_session, monkeypatch):
    """A stale-high watermark must not be able to strand an unindexed paper.

    `sync_search_index` only examines events newer than `last_synced_at`. If the index is
    empty while the watermark sits at "now" -- which is what a truncated index plus a
    surviving watermark row looks like -- then every event predates the window and
    nothing is reindexed, however many `NEW_PAPER` rows exist.
    """
    _run_seeder(db_session, monkeypatch)
    topic = db_session.execute(select(Topic).where(Topic.canonical_label == DEMO_TOPIC)).scalar_one()
    db_session.execute(delete(ChangeEvent).where(ChangeEvent.topic_id == topic.id))
    db_session.execute(delete(PaperSearchIndex))
    db_session.execute(delete(SearchIndexSyncState))
    db_session.add(SearchIndexSyncState(last_synced_at=datetime.utcnow()))
    db_session.flush()

    _run_seeder(db_session, monkeypatch)

    assert _unindexed_demo_titles(db_session) == []


def test_every_demo_paper_keeps_a_new_paper_event(db_session, monkeypatch):
    """The mechanism behind the tests above, asserted directly.

    Indexability follows from a `NEW_PAPER` event existing per paper. Pinning that here
    means a future change to `_seed_dashboard_history`'s round-robin cannot quietly
    reintroduce the gap while the index assertions still pass for some other reason.
    """
    from evidence_engine.db.models import ChangeEventType

    _run_seeder(db_session, monkeypatch)
    _simulate_a_completed_test_run(db_session)
    _run_seeder(db_session, monkeypatch)

    with_new_paper = set(
        db_session.execute(
            select(ChangeEvent.paper_id).where(ChangeEvent.event_type == ChangeEventType.NEW_PAPER)
        )
        .scalars()
        .all()
    )
    missing = [
        db_session.get(Paper, pid).title
        for pid in _demo_paper_ids(db_session)
        if pid not in with_new_paper
    ]
    assert missing == [], f"{len(missing)} of {len(PAPERS)} demo papers have no NEW_PAPER event"
