"""Tests for the test fixtures themselves.

`tests/conftest.py` underwrites every other assertion in this suite: if `db_session`
stopped rolling back, or `reset_leaked_state` stopped running first, tests would start
passing or failing for reasons unrelated to the code under test and nothing would say so.
A code-review audit of this branch named this file's absence as the first thing it would
look at next, for exactly that reason.

Nothing here tests the code under development. It tests the things the rest of the suite
assumes without checking.
"""

import re
import uuid

import pytest
from sqlalchemy import select, text

import tests.conftest as conftest
from scripts.seed_demo_data import DEMO_TOPIC
from evidence_engine.db.models import ChangeEvent, ChangeEventType, Paper, Topic
from evidence_engine.db.session import engine

# Unique per run. A fixed marker made these tests depend on every PREVIOUS run having
# been clean -- and mutating `db_session` to commit instead of roll back, which is how you
# check these tests work at all, leaves exactly that debris behind. Two of them then
# "failed" for two later mutations that had nothing to do with them: a false kill, not a
# finding. A test of isolation must not itself depend on the database being clean.
_MARKER = f"fixture-guarantee-probe-{uuid.uuid4()}"


def test_an_uncommitted_row_is_invisible_to_another_connection(db_session):
    """Weaker than it looks, and labelled accordingly.

    This is MVCC, not the fixture: an unflushed or flushed-but-uncommitted row is
    invisible to another connection whether or not `db_session` ever rolls back. Mutating
    `transaction.rollback()` to `transaction.commit()` leaves this test passing, so it does
    NOT verify isolation -- the pair of tests at the bottom of this file does that, across
    a test boundary, which is the only place the teardown's behaviour becomes observable.
    """
    db_session.add(Topic(canonical_label=_MARKER, mesh_id=f"D_PROBE_{uuid.uuid4().hex[:8]}"))
    db_session.flush()

    with engine.connect() as other:
        visible = other.execute(
            text("SELECT count(*) FROM topics WHERE canonical_label = :label"),
            {"label": _MARKER},
        ).scalar()

    assert visible == 0


def test_an_explicit_commit_inside_db_session_still_does_not_escape(db_session):
    """`session.commit()` inside a test looks like it should persist, and does not.

    SQLAlchemy joins the session to the connection's existing transaction, so the commit
    lands on a savepoint and the fixture's rollback still discards it. This is load-bearing
    and surprising: `dashboard/activity.py::refresh_activity_snapshots` commits the
    `running` marker mid-function, and `scripts/seed_demo_data.py` commits by design. If
    this stopped holding, those paths would start writing real rows from every test run.
    """
    db_session.add(Topic(canonical_label=_MARKER, mesh_id=f"D_PROBE_{uuid.uuid4().hex[:8]}"))
    db_session.commit()

    with engine.connect() as other:
        visible = other.execute(
            text("SELECT count(*) FROM topics WHERE canonical_label = :label"),
            {"label": _MARKER},
        ).scalar()

    assert visible == 0, (
        "an explicitly committed row escaped the fixture transaction -- every test that "
        "calls commit() is now writing to the real database"
    )


def test_reset_leaked_state_takes_effect_before_db_session_can_read(db_session):
    """Ordering, not just presence.

    `reset_leaked_state` commits its DELETEs on its own connection, and `db_session` opens
    a transaction afterwards. If that order ever inverted, the deletes would be invisible
    to the test (or would block on its locks) and every "the table starts empty" assumption
    in the suite would quietly stop holding.
    """
    assert db_session.execute(text("SELECT count(*) FROM paper_search_index")).scalar() == 0
    assert db_session.execute(text("SELECT count(*) FROM search_index_sync_state")).scalar() == 0


def test_the_anon_user_cleanup_pattern_still_matches_what_the_app_mints(db_session):
    """A drift test between two files that have no reason to stay in step.

    `reset_leaked_state` deletes users matching `anon-%` AND `%@no-reply.local`, and
    `digest.profiles.create_anonymous_user` is what mints them. Those committed users are
    deleted rather than rolled back because `POST /users/anonymous` commits through
    `get_db`. If the email format ever changed, the cleanup would silently match nothing,
    anonymous users would accumulate forever, and the first symptom would be an unrelated
    global-scan test (`select_due_users`) failing for no visible reason.
    """
    from digest.profiles import create_anonymous_user

    user = create_anonymous_user(db_session)

    assert re.fullmatch(r"anon-[0-9a-f-]{36}@no-reply\.local", user.email), user.email


# --- the destructive-delete guard -------------------------------------------------------


@pytest.mark.parametrize(
    "name,disposable",
    [
        ("evidence_engine", True),      # this project's own dev database, named explicitly
        ("dashboard_dev", True),
        ("evidence_engine_test", True),
        ("review_a", True),
        ("verify_f3", True),
        ("migration_check", True),
        # Every one of these was ALLOWED by the first version of this guard, which matched
        # raw substrings including "ci" and "dev". A guard that waves through
        # athena_precision is worse than no guard, because it reads as protection.
        ("athena_precision", False),
        ("medicine_db", False),
        ("athena_decisions", False),
        ("specimen_store", False),
        ("athena_devices", False),
        ("athena_production", False),
        ("evidence_engine_prod", False),
    ],
)
def test_the_guard_classifies_database_names_by_token_not_substring(name, disposable):
    assert conftest._looks_disposable(name) is disposable


def test_the_guard_refuses_a_remote_host_whatever_the_database_is_called(monkeypatch):
    """The host is the load-bearing check. Names cannot distinguish a dev database from a
    production one -- this project's dev database is called `evidence_engine`, which is
    exactly what production would be called -- but a production database is reached over
    the network and a disposable one is not."""
    monkeypatch.delenv(conftest._OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(
        conftest, "engine", _stub_engine(host="db.prod.internal", database="dashboard_dev")
    )

    with pytest.raises(pytest.exit.Exception) as exit_info:
        conftest._guard_the_database_is_disposable()

    assert "is not this machine" in str(exit_info.value)


def test_the_guard_refuses_a_local_database_whose_name_is_not_disposable(monkeypatch):
    """The name half of the rule. Without this, deleting the name check entirely passes --
    `_looks_disposable` is tested as a pure function above, but nothing connected it to the
    guard's decision."""
    monkeypatch.delenv(conftest._OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(
        conftest, "engine", _stub_engine(host="localhost", database="athena_precision")
    )

    with pytest.raises(pytest.exit.Exception) as exit_info:
        conftest._guard_the_database_is_disposable()

    assert "does not look disposable" in str(exit_info.value)


def test_reset_leaked_state_actually_calls_the_guard():
    """Structural, deliberately, because the alternative is untestable.

    The guard runs during autouse fixture SETUP, before any test body, so no test can
    monkeypatch it in time to observe the call. Deleting the call from the fixture left
    every other test here passing -- the guard was fully tested and entirely unwired.
    Reading the source is a weaker check than executing it; it is also the only one
    available, and it catches exactly that deletion.
    """
    import inspect

    source = inspect.getsource(conftest.reset_leaked_state)

    assert "_guard_the_database_is_disposable()" in source, (
        "reset_leaked_state no longer calls the guard, so the suite will happily delete "
        "committed rows from whatever DATABASE_URL points at"
    )


def test_the_guard_allows_the_local_default_so_plain_pytest_still_works(monkeypatch):
    """The first version refused `evidence_engine`, which is what `.env` ships with -- so
    plain `pytest`, without sourcing c-env.sh, would not run at all. A guard nobody can
    get past gets deleted rather than fixed."""
    monkeypatch.delenv(conftest._OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(
        conftest, "engine", _stub_engine(host="localhost", database="evidence_engine")
    )

    conftest._guard_the_database_is_disposable()  # must not raise


def test_the_override_is_honoured(monkeypatch):
    monkeypatch.setenv(conftest._OVERRIDE_ENV, "1")
    monkeypatch.setattr(
        conftest, "engine", _stub_engine(host="db.prod.internal", database="anything")
    )

    conftest._guard_the_database_is_disposable()  # must not raise


def _stub_engine(host: str, database: str):
    class _Url:
        def __init__(self):
            self.host = host
            self.database = database

        def render_as_string(self, hide_password=True):
            return f"postgresql://user:***@{host}/{database}"

    class _Engine:
        url = _Url()

    return _Engine()


# --- two-phase checks ------------------------------------------------------------------
#
# `db_session`'s rollback and `reset_leaked_state`'s DELETEs only become observable ACROSS
# a test boundary: inside one test, the teardown has not run yet and the cleanup already
# has. So these two pairs plant something in the first test and assert about it in the
# second. Declaration order is execution order -- no order-randomising plugin is installed,
# which `pytest -p no:randomly` and `pip list` both confirm -- and each pair is named so a
# future reader does not reorder them casually.

_ESCAPE_PROBE = f"rollback-escape-probe-{uuid.uuid4()}"
_QUOTA_PROBE = f"quota-cleanup-probe-{uuid.uuid4()}"
_PAPER_PROBE_ID = str(uuid.uuid4())
# Phase 1 records what it planted for phase 2 to look for.
_PLANTED: dict = {}


def test_phase1_plant_rows_that_must_not_survive(db_session):
    """Writes through `db_session` (must be rolled back by its teardown) and commits a
    `dashboard_rate_windows` row on a separate connection (must be deleted by
    `reset_leaked_state` before the next test)."""
    from datetime import datetime

    from dashboard.models import DashboardRateWindow

    db_session.add(Topic(canonical_label=_ESCAPE_PROBE, mesh_id=f"D_ESC_{uuid.uuid4().hex[:8]}"))
    db_session.flush()

    # Committed on their own connection, exactly as the production paths do: _consume_quota
    # for the rate window, get_db for the search index, the daily job for the watermark.
    #
    # Each of these tables gets a `count == 0` assertion elsewhere in this file, and all of
    # them were vacuous: the table is already empty on a clean database, so deleting the
    # cleanup line changed nothing. Only a committed row planted here can tell.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO dashboard_rate_windows (id, subject, window_start, request_count) "
                "VALUES (gen_random_uuid(), :subject, :start, 1)"
            ),
            {"subject": _QUOTA_PROBE, "start": datetime(2026, 1, 1)},
        )
        conn.execute(
            text(
                "INSERT INTO search_index_sync_state (id, last_synced_at) "
                "VALUES (gen_random_uuid(), :at)"
            ),
            {"at": datetime(2026, 1, 1)},
        )

    # The paper and its index row go through the ORM rather than raw SQL: `papers` has
    # several NOT NULL columns with Python-side defaults, so hand-written INSERTs here
    # would be a list of column names to keep in step with the model for no benefit.
    from digest.profiles import create_anonymous_user
    from evidence_engine.db.session import SessionLocal
    from webapp.models import PaperSearchIndex

    committer = SessionLocal()
    try:
        paper = Paper(id=uuid.UUID(_PAPER_PROBE_ID), title=f"search-index-probe-{_PAPER_PROBE_ID}")
        committer.add(paper)
        committer.flush()
        committer.add(PaperSearchIndex(paper_id=paper.id))
        # A committed anonymous user, as POST /users/anonymous leaves behind through
        # get_db. reset_leaked_state removes these by email pattern; without that they
        # accumulate forever and the first thing to notice is an unrelated global scan
        # (digest's select_due_users) failing for no visible reason.
        anon = create_anonymous_user(committer)
        # A recently-dated change event on the demo topic, as seed_demo_data commits.
        # These land inside exactly the recency window read_change_feed queries, which is
        # why reset_leaked_state clears them for this one topic.
        demo = committer.execute(
            select(Topic).where(Topic.canonical_label == DEMO_TOPIC)
        ).scalar_one_or_none()
        if demo is not None:
            event = ChangeEvent(
                topic_id=demo.id,
                event_type=ChangeEventType.CONSENSUS_UPDATED,
                detected_at=datetime.utcnow(),
            )
            committer.add(event)
            committer.flush()
            _PLANTED["demo_event_id"] = event.id
        committer.commit()
        _PLANTED["anon_user_id"] = anon.id
    finally:
        committer.close()
    assert DashboardRateWindow is not None  # import is the point; keeps linters quiet


def test_phase2_neither_row_survived(db_session):
    """If `db_session` stopped rolling back, the Topic is here. If `reset_leaked_state`
    stopped clearing `dashboard_rate_windows`, the quota row is here. Both mutations were
    invisible to every other test in this file."""
    leaked_topic = db_session.execute(
        text("SELECT count(*) FROM topics WHERE canonical_label = :label"),
        {"label": _ESCAPE_PROBE},
    ).scalar()
    leaked_quota = db_session.execute(
        text("SELECT count(*) FROM dashboard_rate_windows WHERE subject = :subject"),
        {"subject": _QUOTA_PROBE},
    ).scalar()

    assert leaked_topic == 0, (
        "a row written through db_session survived into the next test -- the fixture is "
        "committing rather than rolling back, and every test is now writing real rows"
    )
    assert leaked_quota == 0, (
        "a committed dashboard_rate_windows row survived into the next test -- "
        "reset_leaked_state is no longer clearing it, so quota charges accumulate and a "
        "later test's first interest add will answer 429 for no reason of its own"
    )

    leaked_index = db_session.execute(
        text("SELECT count(*) FROM paper_search_index WHERE paper_id = :pid"),
        {"pid": _PAPER_PROBE_ID},
    ).scalar()
    leaked_watermark = db_session.execute(
        text("SELECT count(*) FROM search_index_sync_state")
    ).scalar()

    # The probe paper is not something reset_leaked_state removes -- it only clears
    # derived rows -- so this test owns cleaning it up.
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM paper_search_index WHERE paper_id = :pid"), {"pid": _PAPER_PROBE_ID})
        conn.execute(text("DELETE FROM papers WHERE id = :pid"), {"pid": _PAPER_PROBE_ID})

    assert leaked_index == 0, (
        "a committed paper_search_index row survived into the next test -- the index is no "
        "longer being cleared, and a stale index is what makes search tests pass or fail "
        "for reasons unrelated to the code under test"
    )
    leaked_anon = db_session.execute(
        text("SELECT count(*) FROM users WHERE id = :uid"),
        {"uid": _PLANTED["anon_user_id"]},
    ).scalar()

    if "demo_event_id" in _PLANTED:
        leaked_event = db_session.execute(
            text("SELECT count(*) FROM change_events WHERE id = :eid"),
            {"eid": _PLANTED["demo_event_id"]},
        ).scalar()
        assert leaked_event == 0, (
            "a committed change_event on the demo topic survived into the next test -- "
            "these sit inside read_change_feed's recency window and make unrelated "
            "change-feed assertions fail"
        )

    assert leaked_anon == 0, (
        "a committed anonymous user survived into the next test -- these accumulate with "
        "every run, and the first symptom is an unrelated global-scan test failing"
    )
    assert leaked_watermark == 0, (
        "a committed search_index_sync_state row survived -- a stale watermark makes the "
        "incremental sync skip the fixtures a test just seeded and report success"
    )
