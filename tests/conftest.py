import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from evidence_engine.db.session import engine


@pytest.fixture(autouse=True)
def reset_leaked_state():
    """Clear committed rows that leak between test runs.

    Tests use `db_session`, which rolls back, so a test never leaves its own rows
    behind. But code paths that commit a session of their own do: webapp's `get_db`
    dependency commits on the way out, and `scripts/seed_demo_data.py` commits by
    design. Those rows survive into later runs, where two kinds of query notice them
    and fail for reasons unrelated to the code under test:

      * global scans, e.g. `select_due_users` reading every active user;
      * single-row watermark tables, where a stale `last_synced_at` makes the
        incremental sync skip the fixtures a test just seeded.

    Only derived or test-generated data is removed. `paper_search_index` and
    `search_index_sync_state` are rebuildable from the source tables by
    `sync_search_index`. User deletion is restricted to the `anon-*@no-reply.local`
    pattern minted by `POST /users/anonymous`, so genuine accounts and any seeded
    demo topics, papers, and scores are left untouched.
    """
    anon = "SELECT id FROM users WHERE email LIKE 'anon-%' AND email LIKE '%@no-reply.local'"
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM paper_search_index"))
        conn.execute(text("DELETE FROM search_index_sync_state"))
        # saved_searches has no ON DELETE CASCADE, so dependents go first.
        conn.execute(text(f"DELETE FROM saved_searches WHERE user_id IN ({anon})"))
        conn.execute(text(f"DELETE FROM users WHERE id IN ({anon})"))
        # citation_refresh_state is a single-row watermark keyed on job_name, and
        # the collection job commits it. Once the scheduled run has executed even
        # once, a test inserting its own row hits the uq_citation_refresh_job
        # unique constraint. citation_velocity_cache is likewise committed by the
        # job and is unique per paper. Both are fully rebuildable from
        # citation_snapshots by recompute_all.
        #
        # citation_snapshots is deliberately NOT cleared: it is append-only, it is
        # the system of record, and the provider reports only current counts, so a
        # deleted snapshot is gone for good. Tests must therefore scope their own
        # assertions by paper rather than assuming an empty table.
        conn.execute(text("DELETE FROM citation_refresh_state"))
        conn.execute(text("DELETE FROM citation_velocity_cache"))
    yield


@pytest.fixture
def db_connection():
    with engine.connect() as conn:
        yield conn


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()
