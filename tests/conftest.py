import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from evidence_engine.db.session import engine
from scripts.seed_demo_data import DEMO_TOPIC

# A database this suite is allowed to delete committed rows from. `reset_leaked_state`
# below is autouse and unconditionally DELETEs from eight tables, including
# `paper_search_index`, so running `pytest` with a production DATABASE_URL exported --
# one stale `export` in a shell, one wrong `.env` -- would silently truncate a real
# deployment's search index before a single test ran. Nothing stopped that.
#
# Deliberately an allowlist of name patterns rather than a denylist: the failure mode is
# someone's real database having a name nobody thought to exclude.
_DELETABLE_DATABASE_PATTERNS = ("test", "dev", "review_", "verify_", "perf_", "race_", "ci")


def _guard_the_database_is_disposable() -> None:
    name = (engine.url.database or "").lower()
    if not any(pattern in name for pattern in _DELETABLE_DATABASE_PATTERNS):
        pytest.exit(
            f"Refusing to run: DATABASE_URL points at {name!r}, which does not look like a "
            "test or development database. This suite deletes committed rows from "
            "paper_search_index, search_index_sync_state, citation_refresh_state, "
            "citation_velocity_cache, topic_activity_snapshots, dashboard_job_state and "
            "dashboard_rate_windows before every test. If this database really is "
            "disposable, add its name pattern to _DELETABLE_DATABASE_PATTERNS in "
            "tests/conftest.py.",
            returncode=3,
        )


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
        incremental sync skip the fixtures a test just seeded;
      * relative-time-window queries, where a row dated "recently" by one committed
        script satisfies another test's "last N days" filter.

    Only derived or test-generated data is removed. `paper_search_index` and
    `search_index_sync_state` are rebuildable from the source tables by
    `sync_search_index`. User deletion is restricted to the `anon-*@no-reply.local`
    pattern minted by `POST /users/anonymous`, so genuine accounts and any seeded
    demo topics, papers, and scores are left untouched.
    """
    _guard_the_database_is_disposable()
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
        # dashboard_job_state is the same kind of single-row watermark as
        # citation_refresh_state above, and topic_activity_snapshots is its derived
        # cache; both are committed by scripts/refresh_dashboard_activity.py and by
        # scripts/seed_demo_data.py's --run-dashboard-job flag, and both are fully
        # rebuildable by re-running refresh_activity_snapshots.
        conn.execute(text("DELETE FROM topic_activity_snapshots"))
        conn.execute(text("DELETE FROM dashboard_job_state"))
        # dashboard_rate_windows leaks by design: dashboard.interests._consume_quota
        # commits on its own connection precisely so the charge survives the request
        # session's rollback, which means a test's charges outlive the test. Left
        # behind, they accumulate against a fixed clock-hour window and would
        # eventually make a later test's first add answer 429 for no reason of its own.
        conn.execute(text("DELETE FROM dashboard_rate_windows"))
        # scripts/seed_demo_data.py also commits 9 weeks of ChangeEvent history for
        # the demo topic, dated relative to "now" so the dashboard has a real
        # trend_score to demonstrate. Unlike the demo topic's papers (dated by fixed
        # calendar month, comfortably outside any "last N days" query by the time
        # this suite runs), those events land inside exactly the kind of recency
        # window dashboard/changes.py's read_change_feed queries, and would
        # otherwise make an unrelated test's "the feed is empty" assertion fail for
        # a reason that has nothing to do with the code under test. The demo topic
        # itself, its papers, and its scores are left untouched, as before -- only
        # this one code path's recent-dated rows are cleared.
        conn.execute(
            text("DELETE FROM change_events WHERE topic_id IN (SELECT id FROM topics WHERE canonical_label = :label)"),
            {"label": DEMO_TOPIC},
        )
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
