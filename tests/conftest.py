import os
import re

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from evidence_engine.db.session import engine
from scripts.seed_demo_data import DEMO_TOPIC

# Whether this suite may delete committed rows from the database it is pointed at.
# `reset_leaked_state` below is autouse and unconditionally DELETEs from eight tables,
# including `paper_search_index`, so running `pytest` with a production DATABASE_URL
# exported -- one stale `export` in a shell, one wrong `.env` -- would truncate a real
# deployment's search index before a single test ran.
#
# The HOST is the load-bearing check, not the name. A production database is reached over
# the network; a disposable one is on this machine. That is a far stronger signal than any
# name pattern, because names do not reliably distinguish the two -- this project's own dev
# database is called `evidence_engine`, which is exactly what a production one would be
# called too.
#
# The name check is secondary and matches whole TOKENS, not substrings. A first version of
# this guard matched raw substrings including "ci" and "dev", which let through
# `athena_precision`, `medicine_db`, `athena_decisions`, `specimen_store` and
# `athena_devices` -- a safety guard that waved through the exact thing it existed to
# catch. It also refused `evidence_engine`, breaking plain `pytest` for anyone who had not
# sourced `.superpowers/sdd/c-env.sh`.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})
# Unix-socket directories that can only reach a server on this machine. A socket path is
# NOT automatically local: `?host=/cloudsql/project:region:instance` is a Cloud SQL proxy
# socket to a database in someone's cloud.
_LOCAL_SOCKET_PREFIXES = ("/tmp", "/private/tmp", "/var/run/postgresql", "/run/postgresql")
# Named explicitly because their names carry no "this is disposable" signal at all.
_KNOWN_LOCAL_DATABASES = frozenset({"evidence_engine", "dashboard_dev"})
_DISPOSABLE_NAME_TOKENS = frozenset({"test", "tests", "dev", "ci", "scratch", "tmp", "local"})
_DISPOSABLE_NAME_PREFIXES = ("review_", "verify_", "perf_", "race_", "migration_")
# Escape hatch for a local database whose name this cannot infer. Deliberately an env var
# rather than another name pattern: setting it is a deliberate act, and widening the
# patterns is how the first version got dangerous.
_OVERRIDE_ENV = "ATHENA_TESTS_MAY_DELETE"


def _looks_disposable(name: str) -> bool:
    if name in _KNOWN_LOCAL_DATABASES:
        return True
    if name.startswith(_DISPOSABLE_NAME_PREFIXES):
        return True
    return bool(_DISPOSABLE_NAME_TOKENS & set(re.split(r"[^a-z0-9]+", name)))


def _effective_host(url) -> str:
    """The host libpq will actually connect to.

    `url.host` is NOT it. libpq accepts the host as a query parameter, and SQLAlchemy
    leaves `url.host` as None in that form -- which the first version of this guard read as
    the empty string and therefore as local. So
    `postgresql://u:p@/evidence_engine?host=db.prod.internal` -- a remote production
    database with an allowlisted name -- was ALLOWED. Verified before fixing.
    """
    query_host = url.query.get("host")
    if isinstance(query_host, (tuple, list)):  # libpq permits a repeated key
        query_host = query_host[0] if query_host else None
    return str(query_host or url.host or "").lower()


def _is_local_host(host: str) -> bool:
    if host.startswith("/"):
        return host.startswith(_LOCAL_SOCKET_PREFIXES)
    return host in _LOCAL_HOSTS


def _guard_the_database_is_disposable() -> None:
    url = engine.url
    name = (url.database or "").lower()
    host = _effective_host(url)

    # The host check is NOT waivable. The override exists for a local database whose name
    # this cannot infer; it must not also wave through a remote one, or it reinstates
    # exactly the "one stale export" threat this guard was written for -- with the export
    # now being the override itself, which someone may well leave set in their shell.
    if not _is_local_host(host):
        reason = f"host {host!r} is not this machine"
    elif os.environ.get(_OVERRIDE_ENV) == "1":
        return
    elif not _looks_disposable(name):
        reason = f"database {name!r} does not look disposable"
    else:
        return

    pytest.exit(
        f"Refusing to run: {reason}. This suite DELETEs committed rows from "
        "paper_search_index, search_index_sync_state, citation_refresh_state, "
        "citation_velocity_cache, topic_activity_snapshots, dashboard_job_state and "
        "dashboard_rate_windows before every single test, so pointing it at a real "
        f"deployment destroys data. DATABASE_URL = {url.render_as_string(hide_password=True)}. "
        f"If this really is a disposable LOCAL database, set {_OVERRIDE_ENV}=1 -- "
        "which waives the name check but never the host check.",
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
