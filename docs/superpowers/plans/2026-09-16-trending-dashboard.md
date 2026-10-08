# Trending and Dashboard Widgets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Dashboard landing route that answers "what should I look at right now?" before the user types anything — most-active topics over 7 days, a dated feed of what changed, and a personal summary once the user declares interests.

**Architecture:** A new `dashboard/` package owning two tables. Rankings are precomputed once a day by a scheduled job into an immutable *generation* of snapshot rows; readers only ever see the generation a watermark row points at, so a half-written run is never visible. Everything is derived from `ChangeEvent` rows the evidence engine already writes — C reads engine tables and adds one index, and changes no engine logic.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 + Alembic (same DB and `Base` as `evidence_engine`), FastAPI, Jinja2 (already a dependency via `digest/render.py`), React 18 + TypeScript + TanStack Query.

## Global Constraints

- **Eligibility floor: `event_count >= 5`.** A topic below it never appears in the ranking (FR-C-002), enforced in `dashboard/trend.py` and asserted by tests, not left to callers.
- **Baseline floor: `baseline_weeks >= 8`.** Below it, `trend_score` is `null` and `is_newly_tracked` is `true`, and the UI shows no change-versus-baseline figure (FR-C-003, FR-C-004).
- **Window convention is half-open: `window_start < detected_at <= window_end`.** This matches `webapp/visualizations.py:51-53` and `digest/aggregate.py:52-53` exactly. A different convention here would make dashboard counts disagree with the topic timeline chart for the same period, which users would read as a bug.
- **Readers never see a partial generation** (FR-C-010). `dashboard_job_state.current_generation_id` is advanced only after a run completes.
- **The change feed hides events for retracted papers, except retractions themselves** (FR-C-006): include when `event_type == 'paper_retracted'` OR `paper_id IS NULL` OR `Paper.is_retracted = false`.
- **The personal endpoint must never raise for a user without a profile** (FR-C-007). Resolve with `scalar_one_or_none()`; do NOT call `digest.profiles.list_interests`, which reaches `_get_profile`'s `.scalar_one()` (`digest/profiles.py:34`) and raises `NoResultFound`. Every user from `create_anonymous_user` lacks a profile, so the raising path is the *common* case on this surface.
- **Dashboard endpoints MUST NOT write to** `change_events`, `papers`, `scores`, or `consensus_snapshots` (FR-C-017). **One carve-out, added after review found the original wording false:** `POST /interests` writes to `topics`, via `digest.profiles.add_interest` → `evidence_engine.topics.registry.get_or_create_topic`, which inserts a `Topic` row for a MeSH term nobody has followed yet and appends the caller's free text to `Topic.aliases`. This is unavoidable — you cannot follow a topic that does not exist — and it is the only engine-table write any dashboard endpoint performs.
- **Copy rules (FR-C-015, FR-C-016).** Use "Most active topics", "Changes"/"What changed", "Newly tracked", "No change this week", "Data as of {timestamp}", "volume of newly indexed and changed evidence". NEVER use: "trending", "hot", "popular", "breakthrough", "important", "updates", "new topic", "nothing found", "no results", "live", "real-time", "up to date", "research momentum", "scientific activity".
- Everything is gated behind `DASHBOARD_ENABLED`, default `false`.
- **Every `pytest` and `alembic` command on this branch MUST be preceded by `source .superpowers/sdd/c-env.sh`.** Sub-project C runs against an isolated `dashboard_dev` database. Concurrent sessions share one dev database — every worktree's `.env` is a symlink to the main one — and a parallel session applied a migration that does not exist on this branch, which left Alembic unable to autogenerate or upgrade here. Editing `.env` would have repointed that session's database mid-run. A command run without sourcing it will silently hit the shared database and either fail on an unknown revision or corrupt someone else's state.
- Run tests as `source .superpowers/sdd/c-env.sh && arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest` from the repo root; the venv's `pydantic_core` is x86_64-only. PostgreSQL runs in docker container `evidence-engine-postgres-1`.
- Frontend: from `webapp/frontend`, `npx vitest run` and `npm run build`. The build is the type check and must be clean.

## Corrections to the spec — verified against the repo on 2026-09-16

The spec was written 2026-08-02 and four of its repo references have since drifted. These supersede it:

1. **Alembic head is `9fa56c44734a`** (sub-project B's synthesis tables), not `5d7c21d9f44e`. Chain from the current head.
2. **The `StaticFiles` mount is at `webapp/api.py:333`**, not `:212`. It must remain the last statement in the file — it catches all unmatched paths, so any route declared after it is unreachable.
3. **`App.tsx:21` currently redirects `/` to `/search`.** FR-C-014 changes the target to `/dashboard`.
4. **`IconSidebar.tsx:4-6` has three entries** (Search, Compare, Saved searches). Dashboard becomes the first.

## Decisions taken before planning

- **OQ-C-001 — RESOLVED** 2026-08-03 in commit `a5a4117`. `select_due_users` now guards both `list_interests` and `get_delivery_preference`, so creating an `InterestProfile` for an anonymous user cannot abort digest delivery. **`digest/runner.py` needs no change in this plan.** The spec's §24 note about conditionally modifying it is obsolete.
- **OQ-C-002 — Option B (user decision, 2026-09-16).** Ship a deterministic Jinja2 templated sentence, clearly not AI-written. Sub-project B has landed but is deliberately not used here: it is gated off, costs a model call per dashboard load on the landing page, and its guardrail is built for comparing papers rather than summarising event counts.
- **OQ-C-003 — Option A** (spec recommendation). Fixed 7-day window. A second window doubles the job's output and the test matrix to serve a preference nobody has expressed; adding one later is additive.
- **OQ-C-004 — Option B (user decision, 2026-09-16).** C owns a `dashboard_rate_windows` table. The spec's recommended Option A assumed sub-project B would ship a generalisable `synthesis_rate_windows` table — **B deliberately shipped without one**, and B's own rate limiting is separate in-flight work. C stays independently shippable rather than racing it. A later consolidation can merge the two; the roadmap already flags a shared limiter as cross-cutting.
- **OQ-C-005 — Option A** (spec recommendation). No type filter on the change feed in v1; the warning treatment for retractions and contradictions does the work a filter would.

## File Structure

| File | Responsibility |
|---|---|
| `dashboard/models.py` | `TopicActivitySnapshot`, `DashboardJobState`, `DashboardRateWindow` |
| `dashboard/windows.py` | Window boundary arithmetic (§14.2). Pure functions, no DB. |
| `dashboard/trend.py` | Eligibility, trend score, ranking (§14.1). Pure functions, no DB. |
| `dashboard/activity.py` | Reads `change_events`, writes a snapshot generation; reads the current generation back |
| `dashboard/changes.py` | The change feed and its retraction filter (§14.3) |
| `dashboard/personal.py` | Per-topic summary for a user's interests, profile-tolerant (§14.4); the templated blurb |
| `dashboard/interests.py` | Add/remove an interest topic, with rate limiting |
| `scripts/refresh_dashboard_activity.py` | The daily job entry point |

---

## Task 1: Package Scaffolding, Models & Migration

**Files:**
- Create: `dashboard/__init__.py`, `dashboard/models.py`
- Modify: `alembic/env.py` (register the new models)
- Create: `alembic/versions/<hash>_dashboard_tables.py` (autogenerated, then hand-checked)
- Create: `tests/dashboard/__init__.py`, `tests/dashboard/conftest.py`, `tests/dashboard/test_models.py`

**Interfaces:**
- Consumes: `evidence_engine.db.models.Base`, `Topic` (existing).
- Produces: ORM classes `TopicActivitySnapshot`, `DashboardJobState`, `DashboardRateWindow` — imported by every later task.

- [ ] **Step 1: Create the package and test package**

`dashboard/__init__.py` and `tests/dashboard/__init__.py`, both empty.

- [ ] **Step 2: Write `dashboard/models.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from evidence_engine.db.models import Base


class TopicActivitySnapshot(Base):
    """One topic's activity for one 7-day window, within one job generation.

    Rows are immutable and disposable: the job writes a whole generation, then flips
    dashboard_job_state.current_generation_id to point at it. Readers only ever see a
    completed generation, which is what keeps a half-written run invisible.
    """

    __tablename__ = "topic_activity_snapshots"
    __table_args__ = (
        UniqueConstraint("generation_id", "topic_id", name="uq_activity_generation_topic"),
        # The exact shape of the read query: newest generation, ordered by rank.
        Index("ix_activity_generation_rank", "generation_id", "rank"),
        Index("ix_activity_computed_at", "computed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    generation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), nullable=False
    )
    window_start: Mapped[datetime] = mapped_column(nullable=False)
    window_end: Mapped[datetime] = mapped_column(nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_paper_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consensus_updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contradiction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retraction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    baseline_mean: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    baseline_weeks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Null exactly when baseline_weeks < 8. NUMERIC rather than float so a stored rank
    # cannot drift with binary-float representation.
    trend_score: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    is_newly_tracked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)


class DashboardJobState(Base):
    """Single logical row per job name.

    Follows the single-row-watermark precedent of SearchIndexSyncState
    (webapp/models.py:25). current_generation_id is the contract with readers: it is
    advanced only after a run completes.
    """

    __tablename__ = "dashboard_job_state"
    __table_args__ = (UniqueConstraint("job_name", name="uq_dashboard_job_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_name: Mapped[str] = mapped_column(String, nullable=False)
    current_generation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    running_generation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="idle")
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    topics_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    topics_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class DashboardRateWindow(Base):
    """Per-user request counter for POST /interests.

    C owns this rather than sharing a table with sub-project B: B shipped without a
    rate-window table, and its rate limiting is separate in-flight work (plan decision,
    OQ-C-004). A later consolidation can merge the two.
    """

    __tablename__ = "dashboard_rate_windows"
    __table_args__ = (
        UniqueConstraint("subject", "window_start", name="uq_dashboard_rate_subject_window"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Opaque so the table is not FK-bound to users: an anonymous id that is later purged
    # must not take its counter rows with it, and must not fail an insert either.
    subject: Mapped[str] = mapped_column(String, nullable=False)
    window_start: Mapped[datetime] = mapped_column(nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
```

- [ ] **Step 3: Register the models with Alembic**

`alembic/env.py` registers each package explicitly. There are currently **five** such lines (`digest.models`, `webapp.models`, `enterprise_api.models`, `citations.models`, `synthesis.models`). Add a sixth in the same style, after `synthesis.models`, **before** autogenerating or the migration will come out empty:

```python
import dashboard.models  # noqa: F401 - import to register dashboard models with Base.metadata
```

- [ ] **Step 4: Write `tests/dashboard/conftest.py`**

`TopicActivitySnapshot.topic_id` is a FK to `topics.id`, declared in `evidence_engine.db.models`, which this package does not import. Without this the test package cannot run standalone — the same issue `tests/synthesis/conftest.py` documents.

```python
# Registers the tables this package's foreign keys point at.
#
# TopicActivitySnapshot.topic_id references topics.id from evidence_engine, and the
# personal-summary tests touch users/interest_profiles from digest. dashboard/models.py
# deliberately does not import digest -- a package declaring a cross-package FK does not
# import the defining package here (webapp/models.py:36 FKs users.id the same way). That
# leaves registration to whatever imported first, which is fine for the app
# (alembic/env.py imports every package) and for the full suite, but not for this package
# alone: collect tests/dashboard/ by itself and SQLAlchemy raises NoReferencedTableError.
#
# Do not delete these as unused imports.
import digest.models  # noqa: F401
import evidence_engine.db.models  # noqa: F401
```

- [ ] **Step 5: Write the failing test**

Create `tests/dashboard/test_models.py`:

```python
import uuid
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from dashboard.models import DashboardJobState, DashboardRateWindow, TopicActivitySnapshot
from evidence_engine.db.models import Topic


def _topic(db_session, label="Atrial fibrillation"):
    topic = Topic(canonical_label=label)
    db_session.add(topic)
    db_session.flush()
    return topic


def _snapshot(topic_id, **overrides):
    defaults = dict(
        generation_id=uuid.uuid4(),
        topic_id=topic_id,
        window_start=datetime(2026, 7, 26),
        window_end=datetime(2026, 8, 2),
        event_count=24,
        rank=1,
    )
    defaults.update(overrides)
    return TopicActivitySnapshot(**defaults)


def test_snapshot_round_trip(db_session):
    topic = _topic(db_session)
    row = _snapshot(topic.id, new_paper_count=19, baseline_mean=7.375, baseline_weeks=8,
                    trend_score=4.173)
    db_session.add(row)
    db_session.flush()

    stored = db_session.get(TopicActivitySnapshot, row.id)
    assert stored.event_count == 24
    assert float(stored.trend_score) == 4.173
    assert stored.is_newly_tracked is False
    assert stored.consensus_updated_count == 0


def test_a_newly_tracked_snapshot_stores_a_null_score(db_session):
    topic = _topic(db_session, "Long COVID sequelae")
    row = _snapshot(topic.id, baseline_weeks=3, baseline_mean=None, trend_score=None,
                    is_newly_tracked=True, rank=4)
    db_session.add(row)
    db_session.flush()

    assert row.trend_score is None
    assert row.baseline_mean is None
    assert row.is_newly_tracked is True


def test_one_topic_appears_once_per_generation(db_session):
    topic = _topic(db_session)
    generation = uuid.uuid4()
    db_session.add(_snapshot(topic.id, generation_id=generation))
    db_session.flush()
    db_session.add(_snapshot(topic.id, generation_id=generation, rank=2))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_the_same_topic_may_appear_in_two_generations(db_session):
    # Generations are independent runs; the unique constraint must not block tomorrow's.
    topic = _topic(db_session)
    db_session.add(_snapshot(topic.id, generation_id=uuid.uuid4()))
    db_session.flush()
    db_session.add(_snapshot(topic.id, generation_id=uuid.uuid4()))
    db_session.flush()  # must not raise


def test_deleting_a_topic_cascades_to_its_snapshots(db_session):
    # Snapshots are derived and disposable, so a deleted topic must not leave orphans
    # or block its own deletion with a FK violation.
    from sqlalchemy import select

    topic = _topic(db_session, "Doomed")
    db_session.add(_snapshot(topic.id))
    db_session.flush()

    db_session.delete(topic)
    db_session.flush()

    remaining = db_session.execute(
        select(TopicActivitySnapshot).where(TopicActivitySnapshot.topic_id == topic.id)
    ).scalars().all()
    assert remaining == []


def test_job_state_round_trip(db_session):
    state = DashboardJobState(job_name="activity_snapshot")
    db_session.add(state)
    db_session.flush()

    assert state.status == "idle"
    assert state.current_generation_id is None
    assert state.topics_processed == 0


def test_job_name_is_unique(db_session):
    db_session.add(DashboardJobState(job_name="activity_snapshot"))
    db_session.flush()
    db_session.add(DashboardJobState(job_name="activity_snapshot"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_rate_window_round_trip(db_session):
    window = DashboardRateWindow(subject="user:abc", window_start=datetime(2026, 8, 2, 9, 0))
    db_session.add(window)
    db_session.flush()

    assert window.request_count == 0


def test_one_counter_per_subject_per_window(db_session):
    start = datetime(2026, 8, 2, 9, 0)
    db_session.add(DashboardRateWindow(subject="user:abc", window_start=start))
    db_session.flush()
    db_session.add(DashboardRateWindow(subject="user:abc", window_start=start))
    with pytest.raises(IntegrityError):
        db_session.flush()
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/dashboard/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard'`, or `relation "topic_activity_snapshots" does not exist` once the module exists but the migration has not run.

- [ ] **Step 7: Generate the migration and apply it**

```bash
arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/alembic revision --autogenerate -m "dashboard tables"
arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/alembic upgrade head
```

Open the generated file and confirm three things, adding them by hand if autogenerate missed them:

1. `down_revision = "9fa56c44734a"` — the current head. If a different revision has landed since, chain from that instead; never rewrite an existing revision.
2. The `topic_id` foreign key carries `ondelete="CASCADE"`.
3. **Add this index by hand — autogenerate will NOT emit it**, because it is on a table `dashboard/models.py` does not declare:

```python
op.create_index(
    "ix_change_events_detected_at",
    "change_events",
    ["detected_at"],
    unique=False,
)
```

and the matching `op.drop_index("ix_change_events_detected_at", table_name="change_events")` in `downgrade()`. Every window query in this plan filters `change_events` by `detected_at`, and the table has no index on it today. This is the one change C makes to an engine-owned table, and it is additive.

- [ ] **Step 8: Run the tests**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/dashboard/test_models.py -v`
Expected: 9 passed.

- [ ] **Step 9: Verify the index exists on the engine table**

```bash
docker exec evidence-engine-postgres-1 psql -U postgres -d athena -c "\di ix_change_events_detected_at"
```

Expected: one row. If empty, the hand-added index in Step 7 was not applied.

- [ ] **Step 10: Commit**

```bash
git add dashboard/ tests/dashboard/ alembic/
git commit -m "feat: add dashboard tables and models"
```

---

## Task 2: Window Boundaries

**Files:**
- Create: `dashboard/windows.py`
- Test: `tests/dashboard/test_windows.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `WINDOW_DAYS: int`; `BASELINE_WINDOWS: int`; `Window` dataclass with `start: datetime`, `end: datetime`; `window_for(as_of: datetime, index: int) -> Window`; `baseline_windows(as_of: datetime) -> list[Window]`. Tasks 3 and 4 use all of these.

The half-open convention here is load-bearing and is the whole content of this task. Get it wrong and every count on the dashboard disagrees with the topic timeline chart for the same period.

- [ ] **Step 1: Write the failing test**

Create `tests/dashboard/test_windows.py`:

```python
from datetime import datetime

from dashboard.windows import BASELINE_WINDOWS, WINDOW_DAYS, baseline_windows, window_for


def test_current_window_ends_at_midnight_utc_of_the_run_day():
    # The run time's clock time is discarded: windows are day-aligned so two runs on the
    # same day produce identical boundaries.
    w = window_for(datetime(2026, 8, 2, 4, 10, 22), 0)

    assert w.end == datetime(2026, 8, 2, 0, 0, 0)
    assert w.start == datetime(2026, 7, 26, 0, 0, 0)


def test_window_index_steps_back_by_whole_weeks():
    w1 = window_for(datetime(2026, 8, 2, 4, 10), 1)

    assert w1.end == datetime(2026, 7, 26, 0, 0, 0)
    assert w1.start == datetime(2026, 7, 19, 0, 0, 0)


def test_windows_do_not_overlap_and_leave_no_gap():
    as_of = datetime(2026, 8, 2, 4, 10)
    w0, w1 = window_for(as_of, 0), window_for(as_of, 1)

    assert w1.end == w0.start


def test_event_at_window_start_boundary_excluded_from_current_window():
    # The half-open rule: window_start < detected_at <= window_end. An event at exactly
    # window_start belongs to the PREVIOUS window. This matches
    # webapp/visualizations.py:51-53 and digest/aggregate.py:52-53 exactly; diverging
    # would make dashboard counts disagree with the topic timeline for the same period.
    as_of = datetime(2026, 8, 2, 4, 10)
    w0 = window_for(as_of, 0)
    w1 = window_for(as_of, 1)
    boundary = datetime(2026, 7, 26, 0, 0, 0)

    assert not (w0.start < boundary <= w0.end)
    assert w1.start < boundary <= w1.end


def test_event_at_window_end_boundary_included_in_current_window():
    as_of = datetime(2026, 8, 2, 4, 10)
    w0 = window_for(as_of, 0)
    boundary = datetime(2026, 8, 2, 0, 0, 0)

    assert w0.start < boundary <= w0.end


def test_baseline_returns_the_eight_windows_before_the_current_one():
    as_of = datetime(2026, 8, 2, 4, 10)

    windows = baseline_windows(as_of)

    assert len(windows) == BASELINE_WINDOWS == 8
    # Starts at index 1, not 0: the current window is never part of its own baseline.
    assert windows[0].end == window_for(as_of, 1).end
    assert windows[-1].end == window_for(as_of, 8).end
    assert all(w.end <= window_for(as_of, 0).start for w in windows)


def test_window_length_is_seven_days():
    w = window_for(datetime(2026, 8, 2), 0)

    assert (w.end - w.start).days == WINDOW_DAYS == 7
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/dashboard/test_windows.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.windows'`.

- [ ] **Step 3: Write `dashboard/windows.py`**

```python
from dataclasses import dataclass
from datetime import datetime, timedelta

WINDOW_DAYS = 7
# Eight complete prior weeks are required before a topic gets a trend score (FR-C-003).
BASELINE_WINDOWS = 8


@dataclass(frozen=True)
class Window:
    """A half-open interval: start < detected_at <= end."""

    start: datetime
    end: datetime


def _midnight_utc(value: datetime) -> datetime:
    return datetime(value.year, value.month, value.day)


def window_for(as_of: datetime, index: int) -> Window:
    """The window `index` weeks back from the run day. Index 0 is the current window.

    Day-aligned on purpose: the run's clock time is discarded so two runs on the same day
    produce identical boundaries, which is what makes a re-run idempotent.
    """
    end = _midnight_utc(as_of) - timedelta(days=index * WINDOW_DAYS)
    return Window(start=end - timedelta(days=WINDOW_DAYS), end=end)


def baseline_windows(as_of: datetime) -> list[Window]:
    """The eight windows immediately preceding the current one, newest first.

    Starts at index 1: the current window is never part of its own baseline, or every
    topic would be compared against itself and the ratio would collapse toward 1.
    """
    return [window_for(as_of, index) for index in range(1, BASELINE_WINDOWS + 1)]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/dashboard/test_windows.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add dashboard/windows.py tests/dashboard/test_windows.py
git commit -m "feat: add dashboard window boundary arithmetic"
```

---

## Task 3: Trend Score and Ranking

**Files:**
- Create: `dashboard/trend.py`
- Test: `tests/dashboard/test_trend.py`

**Interfaces:**
- Consumes: `dashboard.windows.BASELINE_WINDOWS` (Task 2).
- Produces: `MIN_EVENTS: int`; `TopicCounts` dataclass with `topic_id: UUID`, `event_count: int`, `new_paper: int`, `consensus_updated: int`, `contradiction_flagged: int`, `paper_retracted: int`; `ScoredTopic` dataclass with `counts: TopicCounts`, `baseline_mean: float | None`, `baseline_weeks: int`, `trend_score: float | None`, `is_newly_tracked: bool`; `is_eligible(event_count: int) -> bool`; `score_topic(counts, prior_counts: list[int], weeks_tracked: int) -> ScoredTopic`; `rank_topics(scored: list[ScoredTopic]) -> list[ScoredTopic]`. Task 4 uses all of these.

Pure functions only. No database, no I/O.

- [ ] **Step 1: Write the failing test**

Create `tests/dashboard/test_trend.py`:

```python
import math
import uuid

from dashboard.trend import MIN_EVENTS, TopicCounts, is_eligible, rank_topics, score_topic

ID_A = uuid.UUID("9c1e77a2-4b3d-4f18-9a2b-6d5e4c3b2a10")
ID_B = uuid.UUID("2f8b41c7-9d0e-4a55-b731-8c6f5e4d3a29")


def _counts(topic_id=ID_A, event_count=24, **kw):
    base = dict(new_paper=event_count, consensus_updated=0, contradiction_flagged=0,
                paper_retracted=0)
    base.update(kw)
    return TopicCounts(topic_id=topic_id, event_count=event_count, **base)


def test_trend_score_matches_worked_example():
    # Spec 14.1's worked example, asserted exactly.
    #   b = (6+9+4+11+8+7+5+9)/8 = 7.375
    #   activity_ratio = 25 / 8.375 = 2.98507...
    #   volume_weight  = log10(25)  = 1.39794...
    #   trend_score    = round(4.17307..., 3) = 4.173
    scored = score_topic(_counts(event_count=24), [6, 9, 4, 11, 8, 7, 5, 9], weeks_tracked=8)

    assert scored.trend_score == 4.173
    assert scored.baseline_mean == 7.375
    assert scored.is_newly_tracked is False


def test_zero_baseline_does_not_divide_by_zero():
    # The +1 smoothing in numerator and denominator removes the division a raw c/b would
    # hit for any topic with a silent baseline -- the most common case in a young corpus.
    #   (10+1)/(0+1) * log10(11) = 11 * 1.04139... = 11.455
    scored = score_topic(_counts(event_count=10), [0] * 8, weeks_tracked=8)

    assert scored.trend_score == round(11 * math.log10(11), 3) == 11.455


def test_topic_below_five_events_is_ineligible():
    assert is_eligible(MIN_EVENTS) is True
    assert is_eligible(MIN_EVENTS - 1) is False
    assert MIN_EVENTS == 5


def test_fewer_than_eight_weeks_yields_no_score():
    scored = score_topic(_counts(event_count=9), [3, 4, 2], weeks_tracked=3)

    assert scored.trend_score is None
    assert scored.baseline_mean is None
    assert scored.is_newly_tracked is True
    assert scored.baseline_weeks == 3


def test_exactly_eight_weeks_yields_a_score():
    # The boundary is >= 8, not > 8.
    scored = score_topic(_counts(event_count=10), [1] * 8, weeks_tracked=8)

    assert scored.trend_score is not None
    assert scored.is_newly_tracked is False


def test_an_absent_prior_window_counts_as_zero_not_as_a_skipped_term():
    # Absence genuinely means no activity, so it must drag the mean down rather than be
    # dropped from the denominator.
    with_gap = score_topic(_counts(event_count=10), [8, 0, 8, 0, 8, 0, 8, 0], weeks_tracked=8)

    assert with_gap.baseline_mean == 4.0


def test_ranking_is_by_score_descending():
    high = score_topic(_counts(topic_id=ID_A, event_count=24), [1] * 8, weeks_tracked=8)
    low = score_topic(_counts(topic_id=ID_B, event_count=6), [5] * 8, weeks_tracked=8)

    ranked = rank_topics([low, high])

    assert [s.counts.topic_id for s in ranked] == [ID_A, ID_B]


def test_a_busy_newly_tracked_topic_is_not_buried_below_a_marginal_old_one():
    # Newly tracked topics interleave by event count rather than being segregated to the
    # bottom, so a genuinely busy new topic outranks a barely-elevated established one.
    marginal_old = score_topic(_counts(topic_id=ID_A, event_count=6), [5] * 8, weeks_tracked=8)
    busy_new = score_topic(_counts(topic_id=ID_B, event_count=40), [], weeks_tracked=0)

    ranked = rank_topics([marginal_old, busy_new])

    assert ranked[0].counts.topic_id == ID_B


def test_ranking_is_stable_for_equal_keys():
    # Two topics with identical activity must not swap order between runs, or the
    # dashboard appears to reshuffle for no reason.
    a = score_topic(_counts(topic_id=ID_A, event_count=10), [2] * 8, weeks_tracked=8)
    b = score_topic(_counts(topic_id=ID_B, event_count=10), [2] * 8, weeks_tracked=8)

    assert [s.counts.topic_id for s in rank_topics([a, b])] == [ID_A, ID_B]
    assert [s.counts.topic_id for s in rank_topics([b, a])] == [ID_B, ID_A]


def test_breakdown_counts_are_carried_through_untouched():
    counts = _counts(event_count=24, new_paper=19, consensus_updated=2,
                     contradiction_flagged=2, paper_retracted=1)

    scored = score_topic(counts, [1] * 8, weeks_tracked=8)

    assert scored.counts.new_paper == 19
    assert scored.counts.paper_retracted == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/dashboard/test_trend.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.trend'`.

- [ ] **Step 3: Write `dashboard/trend.py`**

```python
import math
import uuid
from dataclasses import dataclass

from dashboard.windows import BASELINE_WINDOWS

# A topic below this never appears in the ranking (FR-C-002). Enforced here rather than
# left to the caller, so there is exactly one place the floor can be wrong.
MIN_EVENTS = 5


@dataclass(frozen=True)
class TopicCounts:
    topic_id: uuid.UUID
    event_count: int
    new_paper: int
    consensus_updated: int
    contradiction_flagged: int
    paper_retracted: int


@dataclass(frozen=True)
class ScoredTopic:
    counts: TopicCounts
    baseline_mean: float | None
    baseline_weeks: int
    trend_score: float | None
    is_newly_tracked: bool


def is_eligible(event_count: int) -> bool:
    return event_count >= MIN_EVENTS


def score_topic(counts: TopicCounts, prior_counts: list[int], weeks_tracked: int) -> ScoredTopic:
    """Score one topic against its own recent history.

    What this measures: the volume of newly indexed and changed evidence for a topic
    relative to that topic's own recent history. A topic can rank highly because an
    adapter backfilled older papers, because one consensus regeneration fired, or because
    retractions were detected -- none of which is a scientific development. It is NOT a
    measure of importance, quality, novelty, or clinical relevance. FR-C-015 and FR-C-016
    exist to stop the interface implying otherwise.
    """
    if weeks_tracked < BASELINE_WINDOWS:
        # Not enough history to compare against. Ranked by raw count instead, and the UI
        # shows no change-versus-baseline figure (FR-C-003, FR-C-004).
        return ScoredTopic(
            counts=counts,
            baseline_mean=None,
            baseline_weeks=weeks_tracked,
            trend_score=None,
            is_newly_tracked=True,
        )

    baseline_mean = sum(prior_counts) / len(prior_counts)
    # Laplace smoothing on both sides: removes the division by zero a raw c/b would hit
    # for any topic with a silent baseline, which is the common case in a young corpus.
    activity_ratio = (counts.event_count + 1) / (baseline_mean + 1)
    volume_weight = math.log10(counts.event_count + 1)
    # Rounded exactly once, at the end, so intermediate precision is not compounded.
    return ScoredTopic(
        counts=counts,
        baseline_mean=baseline_mean,
        baseline_weeks=weeks_tracked,
        trend_score=round(activity_ratio * volume_weight, 3),
        is_newly_tracked=False,
    )


def rank_topics(scored: list[ScoredTopic]) -> list[ScoredTopic]:
    """Rank by trend_score where there is one, by event_count where there is not.

    Newly tracked topics interleave by count rather than being segregated below scored
    ones, so a genuinely busy new topic is not buried under a marginally elevated old one.
    Python's sort is stable, so equal keys preserve input order and the ranking does not
    reshuffle between runs for no reason.
    """
    return sorted(
        scored,
        key=lambda s: s.trend_score if s.trend_score is not None else float(s.counts.event_count),
        reverse=True,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/dashboard/test_trend.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add dashboard/trend.py tests/dashboard/test_trend.py
git commit -m "feat: add dashboard trend score and ranking"
```

---

### Amendment 2026-09-17: newly-tracked topics rank on a provisional baseline

Task 3's review found that `rank_topics` mixed non-commensurable quantities: scored
topics sorted on `trend_score` (a smoothed log-ratio, typically 4-5) while newly-tracked
topics sorted on raw `event_count` (unbounded). Measured, the failure is systematic
rather than marginal — any newly-tracked topic with about 9 or more events outranks a
scored topic with a typical score, even at 3x the event count:

| scored topic | its key | new topic | its key | order |
|---|---|---|---|---|
| c=30, b=10 | 4.203 | c=9 | 9.0 | new first |
| c=24, b=7.375 | 4.369 | c=12 | 12.0 | new first |
| c=50, b=20 | 4.147 | c=30 | 30.0 | new first |

The widget displays raw counts (FR-C-004), so a reader sees "9 changes" above
"30 changes" under a heading reading *Most active topics*, with nothing on screen to
explain it.

**Resolution (user decision).** Newly-tracked topics are ranked with the same formula,
substituting a *provisional* baseline: the median `baseline_mean` of the scored topics in
the same generation — "we do not know this topic's history, so assume it is typical."
Both kinds then sit on one scale and a busy new topic still is not buried.

**This changes the ranking key only, never the stored value.** FR-C-003 requires
`trend_score` to be null for a newly-tracked topic, and it stays null on the row and in
the API. The provisional score exists solely to order the list.

Interface changes:
- `rank_topics(scored: list[ScoredTopic], provisional_baseline: float) -> list[ScoredTopic]`.
  For a topic with `trend_score is not None` the key is that score; otherwise the key is
  `(c + 1) / (provisional_baseline + 1) * log10(c + 1)`.
- `dashboard/activity.py` computes the median of `baseline_mean` across scored topics
  before ranking and passes it. When no topic is scored, pass `0.0`: every topic is then
  newly tracked, the same baseline applies to all of them, and the key stays monotonic in
  `event_count`, which is the correct ordering for that case.

Required tests: a scored topic with more events outranks a newly-tracked topic with
fewer, for the middle-range magnitudes in the table above; and the no-scored-topics case
orders purely by count.

---

## Task 4: Activity Aggregation and the Daily Job

**Files:**
- Create: `dashboard/activity.py`, `scripts/refresh_dashboard_activity.py`
- Modify: `evidence_engine/config.py` (add `dashboard_enabled`)
- Test: `tests/dashboard/test_activity.py`, `tests/scripts/test_refresh_dashboard_activity.py`

**Interfaces:**
- Consumes: `dashboard.windows` (Task 2), `dashboard.trend` (Task 3), `dashboard.models` (Task 1).
- Produces: `JOB_NAME: str`; `RETENTION_DAYS: int`; `refresh_activity_snapshots(session, as_of: datetime | None = None) -> uuid.UUID` returning the new generation id; `read_current_activity(session, limit: int) -> dict` returning the API payload. Task 7's endpoint calls `read_current_activity`.

This is the task where FR-C-010 lives: a reader must never see a generation that is still being written.

- [ ] **Step 1: Add the setting**

In `evidence_engine/config.py`, alongside the existing fields:

```python
    dashboard_enabled: bool = False
```

Read from the environment as `DASHBOARD_ENABLED`.

- [ ] **Step 2: Write the failing test**

Create `tests/dashboard/test_activity.py`:

```python
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select

from dashboard.activity import JOB_NAME, read_current_activity, refresh_activity_snapshots
from dashboard.models import DashboardJobState, TopicActivitySnapshot
from evidence_engine.db.models import ChangeEvent, ChangeEventType, Topic

AS_OF = datetime(2026, 8, 2, 4, 10)


def _topic(db_session, label):
    topic = Topic(canonical_label=label)
    db_session.add(topic)
    db_session.flush()
    return topic


def _events(db_session, topic_id, count, days_before_end, event_type=ChangeEventType.NEW_PAPER):
    """`days_before_end` is measured back from the current window's end (midnight of AS_OF)."""
    moment = datetime(2026, 8, 2) - timedelta(days=days_before_end)
    for _ in range(count):
        db_session.add(
            ChangeEvent(topic_id=topic_id, event_type=event_type, detected_at=moment)
        )
    db_session.flush()


def test_a_topic_below_the_floor_is_not_ranked(db_session):
    topic = _topic(db_session, "Quiet topic")
    _events(db_session, topic.id, 4, days_before_end=1)

    refresh_activity_snapshots(db_session, as_of=AS_OF)
    payload = read_current_activity(db_session, limit=10)

    assert payload["topics"] == []


def test_a_topic_at_the_floor_is_ranked(db_session):
    topic = _topic(db_session, "Busy enough")
    _events(db_session, topic.id, 5, days_before_end=1)

    refresh_activity_snapshots(db_session, as_of=AS_OF)
    payload = read_current_activity(db_session, limit=10)

    assert [t["topic"]["canonical_label"] for t in payload["topics"]] == ["Busy enough"]
    assert payload["topics"][0]["event_count"] == 5
    assert payload["topics"][0]["rank"] == 1


def test_the_breakdown_by_event_type_is_recorded(db_session):
    topic = _topic(db_session, "Mixed")
    _events(db_session, topic.id, 4, 1, ChangeEventType.NEW_PAPER)
    _events(db_session, topic.id, 2, 2, ChangeEventType.CONSENSUS_UPDATED)
    _events(db_session, topic.id, 1, 3, ChangeEventType.PAPER_RETRACTED)

    refresh_activity_snapshots(db_session, as_of=AS_OF)
    row = read_current_activity(db_session, limit=10)["topics"][0]

    assert row["event_count"] == 7
    assert row["breakdown"] == {
        "new_paper": 4,
        "consensus_updated": 2,
        "contradiction_flagged": 0,
        "paper_retracted": 1,
    }


def test_an_event_on_the_window_start_boundary_is_excluded(db_session):
    # Half-open: window_start < detected_at <= window_end. An event at exactly
    # window_start belongs to the previous window and must not inflate this one.
    topic = _topic(db_session, "Boundary")
    _events(db_session, topic.id, 5, days_before_end=1)
    _events(db_session, topic.id, 3, days_before_end=7)  # exactly window_start

    refresh_activity_snapshots(db_session, as_of=AS_OF)
    row = read_current_activity(db_session, limit=10)["topics"][0]

    assert row["event_count"] == 5


def test_a_topic_without_eight_weeks_of_history_is_newly_tracked(db_session):
    topic = _topic(db_session, "Young")
    _events(db_session, topic.id, 9, days_before_end=1)
    _events(db_session, topic.id, 2, days_before_end=10)

    refresh_activity_snapshots(db_session, as_of=AS_OF)
    row = read_current_activity(db_session, limit=10)["topics"][0]

    assert row["is_newly_tracked"] is True
    assert row["trend_score"] is None
    assert row["baseline_mean"] is None


def test_a_topic_with_full_history_gets_a_score(db_session):
    topic = _topic(db_session, "Established")
    _events(db_session, topic.id, 24, days_before_end=1)
    # One event in each of the 8 prior weeks, plus one older than all of them so the
    # topic's first event predates the earliest baseline window.
    for week in range(1, 9):
        _events(db_session, topic.id, 1, days_before_end=7 * week + 1)
    _events(db_session, topic.id, 1, days_before_end=70)

    refresh_activity_snapshots(db_session, as_of=AS_OF)
    row = read_current_activity(db_session, limit=10)["topics"][0]

    assert row["is_newly_tracked"] is False
    assert row["baseline_weeks"] == 8
    assert row["trend_score"] is not None


def test_readers_never_see_a_partially_written_generation(db_session):
    # FR-C-010. The job writes rows first and advances the watermark last, so a run that
    # dies mid-write leaves the previous generation serving.
    topic = _topic(db_session, "First")
    _events(db_session, topic.id, 6, days_before_end=1)
    refresh_activity_snapshots(db_session, as_of=AS_OF)
    first = read_current_activity(db_session, limit=10)

    # Simulate a half-written later run: rows exist under a new generation id, but the
    # watermark has not been advanced to it.
    orphan_generation = uuid.uuid4()
    db_session.add(
        TopicActivitySnapshot(
            generation_id=orphan_generation,
            topic_id=topic.id,
            window_start=datetime(2026, 7, 26),
            window_end=datetime(2026, 8, 2),
            event_count=999,
            rank=1,
        )
    )
    db_session.flush()

    assert read_current_activity(db_session, limit=10)["topics"] == first["topics"]
    assert read_current_activity(db_session, limit=10)["topics"][0]["event_count"] != 999


def test_a_second_run_replaces_what_readers_see(db_session):
    topic = _topic(db_session, "Changing")
    _events(db_session, topic.id, 6, days_before_end=1)
    refresh_activity_snapshots(db_session, as_of=AS_OF)

    _events(db_session, topic.id, 5, days_before_end=2)
    refresh_activity_snapshots(db_session, as_of=AS_OF)

    assert read_current_activity(db_session, limit=10)["topics"][0]["event_count"] == 11


def test_the_job_records_its_outcome(db_session):
    topic = _topic(db_session, "Recorded")
    _events(db_session, topic.id, 6, days_before_end=1)

    generation = refresh_activity_snapshots(db_session, as_of=AS_OF)

    state = db_session.execute(
        select(DashboardJobState).where(DashboardJobState.job_name == JOB_NAME)
    ).scalar_one()
    assert state.current_generation_id == generation
    assert state.status == "idle"
    assert state.completed_at is not None
    assert state.topics_processed == 1
    assert state.running_generation_id is None


def test_cold_start_returns_nulls_not_an_error(db_session):
    # No job has ever run. The endpoint must still answer.
    payload = read_current_activity(db_session, limit=10)

    assert payload == {
        "computed_at": None,
        "window_start": None,
        "window_end": None,
        "topics": [],
    }


def test_limit_truncates_the_ranking(db_session):
    for index in range(4):
        topic = _topic(db_session, f"Topic {index}")
        _events(db_session, topic.id, 5 + index, days_before_end=1)

    refresh_activity_snapshots(db_session, as_of=AS_OF)
    payload = read_current_activity(db_session, limit=2)

    assert len(payload["topics"]) == 2
    assert [t["rank"] for t in payload["topics"]] == [1, 2]


def test_old_generations_are_pruned_but_the_current_one_is_never(db_session):
    from dashboard.activity import RETENTION_DAYS

    topic = _topic(db_session, "Retained")
    _events(db_session, topic.id, 6, days_before_end=1)

    stale_generation = uuid.uuid4()
    db_session.add(
        TopicActivitySnapshot(
            generation_id=stale_generation,
            topic_id=topic.id,
            window_start=datetime(2025, 1, 1),
            window_end=datetime(2025, 1, 8),
            event_count=1,
            rank=1,
            computed_at=datetime(2026, 8, 2) - timedelta(days=RETENTION_DAYS + 1),
        )
    )
    db_session.flush()

    current = refresh_activity_snapshots(db_session, as_of=AS_OF)

    remaining = db_session.execute(
        select(TopicActivitySnapshot.generation_id).distinct()
    ).scalars().all()
    assert stale_generation not in remaining
    assert current in remaining
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/dashboard/test_activity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.activity'`.

- [ ] **Step 4: Write `dashboard/activity.py`**

```python
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from dashboard.models import DashboardJobState, TopicActivitySnapshot
from dashboard.trend import TopicCounts, is_eligible, rank_topics, score_topic
from dashboard.windows import BASELINE_WINDOWS, baseline_windows, window_for
from evidence_engine.db.models import ChangeEvent, ChangeEventType, Topic

JOB_NAME = "activity_snapshot"
RETENTION_DAYS = 180

_TYPE_FIELDS = {
    ChangeEventType.NEW_PAPER: "new_paper",
    ChangeEventType.CONSENSUS_UPDATED: "consensus_updated",
    ChangeEventType.CONTRADICTION_FLAGGED: "contradiction_flagged",
    ChangeEventType.PAPER_RETRACTED: "paper_retracted",
}


def _counts_in_window(session: Session, start: datetime, end: datetime) -> dict:
    """Per-topic counts, broken down by event type, for one half-open window.

    One grouped query for every topic at once rather than a query per topic: the job
    walks nine windows, and per-topic queries would make that O(topics x windows).
    """
    rows = session.execute(
        select(
            ChangeEvent.topic_id,
            ChangeEvent.event_type,
            func.count().label("n"),
        )
        .where(ChangeEvent.detected_at > start, ChangeEvent.detected_at <= end)
        .group_by(ChangeEvent.topic_id, ChangeEvent.event_type)
    ).all()

    counts: dict = {}
    for topic_id, event_type, n in rows:
        bucket = counts.setdefault(
            topic_id,
            {"total": 0, "new_paper": 0, "consensus_updated": 0,
             "contradiction_flagged": 0, "paper_retracted": 0},
        )
        bucket["total"] += n
        field = _TYPE_FIELDS.get(event_type)
        if field is not None:
            bucket[field] += n
    return counts


def _first_event_at(session: Session) -> dict:
    """Earliest event per topic, used to decide how many complete weeks it was tracked."""
    rows = session.execute(
        select(ChangeEvent.topic_id, func.min(ChangeEvent.detected_at)).group_by(
            ChangeEvent.topic_id
        )
    ).all()
    return {topic_id: first for topic_id, first in rows}


def refresh_activity_snapshots(session: Session, as_of: datetime | None = None) -> uuid.UUID:
    """Compute one generation of rankings and publish it. Returns the generation id.

    The write order is the contract with readers (FR-C-010): rows are written under a
    fresh generation id, and only once every row is in does the watermark advance to it.
    A run that dies mid-write leaves the previous generation serving, and its orphaned
    rows are pruned by a later run rather than ever being read.
    """
    as_of = as_of or datetime.utcnow()
    generation = uuid.uuid4()
    current = window_for(as_of, 0)

    state = session.execute(
        select(DashboardJobState).where(DashboardJobState.job_name == JOB_NAME)
    ).scalar_one_or_none()
    if state is None:
        state = DashboardJobState(job_name=JOB_NAME)
        session.add(state)
    state.status = "running"
    state.running_generation_id = generation
    state.started_at = as_of
    session.flush()

    current_counts = _counts_in_window(session, current.start, current.end)
    priors = [_counts_in_window(session, w.start, w.end) for w in baseline_windows(as_of)]
    first_seen = _first_event_at(session)

    scored = []
    for topic_id, bucket in current_counts.items():
        if not is_eligible(bucket["total"]):
            continue
        # How many complete baseline windows the topic actually existed for. A window
        # counts only if the topic's first event predates its start -- otherwise the
        # topic's silence through that window is absence of TRACKING, not absence of
        # activity, and averaging it in as a zero would understate the baseline and
        # inflate the ratio against it.
        #
        # This reaches 8 exactly when the first event predates the earliest baseline
        # window, so no separate "fully tracked" branch is needed: `first <=
        # earliest_baseline_start` implies `first <= w.start` for every window, and the
        # sum is already 8. An earlier draft had that branch; it was dead logic.
        first = first_seen.get(topic_id)
        weeks = sum(1 for w in baseline_windows(as_of) if first is not None and first <= w.start)
        prior_counts = [p.get(topic_id, {}).get("total", 0) for p in priors]
        scored.append(
            score_topic(
                TopicCounts(
                    topic_id=topic_id,
                    event_count=bucket["total"],
                    new_paper=bucket["new_paper"],
                    consensus_updated=bucket["consensus_updated"],
                    contradiction_flagged=bucket["contradiction_flagged"],
                    paper_retracted=bucket["paper_retracted"],
                ),
                prior_counts,
                weeks_tracked=weeks,
            )
        )

    for position, item in enumerate(rank_topics(scored), start=1):
        session.add(
            TopicActivitySnapshot(
                generation_id=generation,
                topic_id=item.counts.topic_id,
                window_start=current.start,
                window_end=current.end,
                event_count=item.counts.event_count,
                new_paper_count=item.counts.new_paper,
                consensus_updated_count=item.counts.consensus_updated,
                contradiction_count=item.counts.contradiction_flagged,
                retraction_count=item.counts.paper_retracted,
                baseline_mean=item.baseline_mean,
                baseline_weeks=item.baseline_weeks,
                trend_score=item.trend_score,
                is_newly_tracked=item.is_newly_tracked,
                rank=position,
                computed_at=as_of,
            )
        )
    session.flush()

    # Publish. Everything above this line is invisible to readers.
    state.current_generation_id = generation
    state.running_generation_id = None
    state.status = "idle"
    state.completed_at = as_of
    state.topics_processed = len(scored)
    state.topics_failed = 0
    state.last_error = None
    session.flush()

    _prune(session, generation, as_of)
    return generation


def _prune(session: Session, keep_generation: uuid.UUID, as_of: datetime) -> None:
    """Drop generations older than the retention horizon.

    The current generation is exempt regardless of age: a dashboard that stopped being
    refreshed should keep serving its last good ranking rather than silently emptying.
    """
    cutoff = as_of - timedelta(days=RETENTION_DAYS)
    session.execute(
        delete(TopicActivitySnapshot).where(
            TopicActivitySnapshot.computed_at < cutoff,
            TopicActivitySnapshot.generation_id != keep_generation,
        )
    )
    session.flush()


def read_current_activity(session: Session, limit: int) -> dict:
    """The API payload for GET /dashboard/activity."""
    state = session.execute(
        select(DashboardJobState).where(DashboardJobState.job_name == JOB_NAME)
    ).scalar_one_or_none()
    if state is None or state.current_generation_id is None:
        # Cold start: no job has run. Answer with nulls rather than an error, so the
        # dashboard renders its empty state instead of a failure.
        return {"computed_at": None, "window_start": None, "window_end": None, "topics": []}

    rows = session.execute(
        select(TopicActivitySnapshot, Topic)
        .join(Topic, Topic.id == TopicActivitySnapshot.topic_id)
        .where(TopicActivitySnapshot.generation_id == state.current_generation_id)
        .order_by(TopicActivitySnapshot.rank)
        .limit(limit)
    ).all()

    if not rows:
        return {
            "computed_at": _iso(state.completed_at),
            "window_start": None,
            "window_end": None,
            "topics": [],
        }

    first_snapshot = rows[0][0]
    return {
        "computed_at": _iso(state.completed_at),
        "window_start": _iso(first_snapshot.window_start),
        "window_end": _iso(first_snapshot.window_end),
        "topics": [
            {
                "topic": {"id": str(topic.id), "canonical_label": topic.canonical_label},
                "rank": snapshot.rank,
                "event_count": snapshot.event_count,
                "breakdown": {
                    "new_paper": snapshot.new_paper_count,
                    "consensus_updated": snapshot.consensus_updated_count,
                    "contradiction_flagged": snapshot.contradiction_count,
                    "paper_retracted": snapshot.retraction_count,
                },
                "baseline_mean": float(snapshot.baseline_mean)
                if snapshot.baseline_mean is not None
                else None,
                "baseline_weeks": snapshot.baseline_weeks,
                "trend_score": float(snapshot.trend_score)
                if snapshot.trend_score is not None
                else None,
                "is_newly_tracked": snapshot.is_newly_tracked,
            }
            for snapshot, topic in rows
        ],
    }


def _iso(value: datetime | None) -> str | None:
    """Naive UTC timestamps need an explicit Z, or JavaScript parses them as local time.

    Same reasoning as citations/read.py's iso_utc: an offset-less date-time is read by
    the browser in the viewer's own zone, which would shift every "data as of" label and
    could push computed_at across the 36-hour staleness threshold for anyone west of UTC.
    """
    return None if value is None else value.isoformat() + "Z"
```

- [ ] **Step 5: Run the tests**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/dashboard/test_activity.py -v`
Expected: 12 passed.

- [ ] **Step 6: Write the job entry point**

Create `scripts/refresh_dashboard_activity.py`:

```python
"""Daily dashboard activity refresh.

Run as a module so package imports resolve:
    arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/python -m scripts.refresh_dashboard_activity
"""

import logging
import sys

from evidence_engine.db.session import SessionLocal
from dashboard.activity import JOB_NAME, refresh_activity_snapshots
from dashboard.models import DashboardJobState
from sqlalchemy import select

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    session = SessionLocal()
    try:
        generation = refresh_activity_snapshots(session)
        session.commit()
        logger.info("dashboard.activity_refreshed generation=%s", generation)
        return 0
    except Exception as exc:
        session.rollback()
        # Record the failure so the dashboard can surface staleness rather than the
        # operator discovering it from an empty widget.
        try:
            state = session.execute(
                select(DashboardJobState).where(DashboardJobState.job_name == JOB_NAME)
            ).scalar_one_or_none()
            if state is not None:
                state.status = "failed"
                state.running_generation_id = None
                state.last_error = str(exc)[:2000]
                session.commit()
        except Exception:  # pragma: no cover - the failure path must not mask the original
            session.rollback()
        logger.exception("dashboard.activity_refresh_failed")
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: Write the job test**

Create `tests/scripts/test_refresh_dashboard_activity.py` (create `tests/scripts/__init__.py` if it does not exist):

```python
from datetime import datetime, timedelta

from sqlalchemy import select

from dashboard.activity import JOB_NAME
from dashboard.models import DashboardJobState
from evidence_engine.db.models import ChangeEvent, ChangeEventType, Topic


def test_a_failed_run_is_recorded_rather_than_silent(db_session, monkeypatch):
    # An operator must be able to tell a stale dashboard from an empty one.
    import scripts.refresh_dashboard_activity as job

    monkeypatch.setattr(job, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "commit", db_session.flush)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(
        job, "refresh_activity_snapshots", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    assert job.main() == 1

    state = db_session.execute(
        select(DashboardJobState).where(DashboardJobState.job_name == JOB_NAME)
    ).scalar_one_or_none()
    assert state is not None
    assert state.status == "failed"
    assert "boom" in state.last_error


def test_a_successful_run_returns_zero(db_session, monkeypatch):
    import scripts.refresh_dashboard_activity as job

    topic = Topic(canonical_label="Job topic")
    db_session.add(topic)
    db_session.flush()
    for _ in range(6):
        db_session.add(
            ChangeEvent(
                topic_id=topic.id,
                event_type=ChangeEventType.NEW_PAPER,
                detected_at=datetime.utcnow() - timedelta(days=1),
            )
        )
    db_session.flush()

    monkeypatch.setattr(job, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "commit", db_session.flush)
    monkeypatch.setattr(db_session, "close", lambda: None)

    assert job.main() == 0
```

Note: `DashboardJobState` must exist for the failure test to find a row. If `refresh_activity_snapshots` never ran, there is no row to mark failed — so the failure path creates one. Add that to `main()`'s except branch if the test shows it missing, rather than weakening the assertion.

- [ ] **Step 8: Run the full suite**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest -q`
Expected: all pass, no regressions.

- [ ] **Step 9: Commit**

```bash
git add dashboard/activity.py scripts/refresh_dashboard_activity.py evidence_engine/config.py tests/dashboard/test_activity.py tests/scripts/
git commit -m "feat: add dashboard activity aggregation and daily refresh job"
```

---

## Task 5: Change Feed

**Files:**
- Create: `dashboard/changes.py`
- Test: `tests/dashboard/test_changes.py`

**Interfaces:**
- Consumes: `dashboard.activity._iso` (Task 4) — import it, do not reimplement.
- Produces: `read_change_feed(session, days: int, limit: int) -> dict`. Task 7's endpoint calls it.

The retraction filter (§14.3) is the whole point of this task: a paper that turns out to be retracted must stop appearing as new evidence, but its retraction must appear prominently.

- [ ] **Step 1: Write the failing test**

Create `tests/dashboard/test_changes.py`:

```python
from datetime import datetime, timedelta

from dashboard.changes import read_change_feed
from evidence_engine.db.models import ChangeEvent, ChangeEventType, Paper, Topic


def _topic(db_session, label="Atrial fibrillation"):
    topic = Topic(canonical_label=label)
    db_session.add(topic)
    db_session.flush()
    return topic


def _paper(db_session, title, retracted=False):
    paper = Paper(title=title, is_retracted=retracted)
    db_session.add(paper)
    db_session.flush()
    return paper


def _event(db_session, topic_id, event_type, when, paper_id=None):
    db_session.add(
        ChangeEvent(topic_id=topic_id, paper_id=paper_id, event_type=event_type, detected_at=when)
    )
    db_session.flush()


def test_new_paper_event_for_retracted_paper_hidden_but_retraction_event_shown(db_session):
    # Paper P is retracted. Its earlier "new paper" event must disappear -- continuing to
    # advertise it as new evidence is the harm. Its retraction event must remain, and
    # prominently, because that is the thing a researcher needs to know.
    topic = _topic(db_session)
    paper = _paper(db_session, "Weight outcomes in a retrospective cohort", retracted=True)
    now = datetime.utcnow()
    _event(db_session, topic.id, ChangeEventType.NEW_PAPER, now - timedelta(days=3), paper.id)
    _event(db_session, topic.id, ChangeEventType.PAPER_RETRACTED, now - timedelta(days=1), paper.id)

    feed = read_change_feed(db_session, days=7, limit=50)
    types = [e["event_type"] for day in feed["days"] for e in day["events"]]

    assert types == ["paper_retracted"]
    assert feed["total_events"] == 1


def test_events_for_a_clean_paper_are_shown(db_session):
    topic = _topic(db_session)
    paper = _paper(db_session, "Anticoagulation in adults over 85", retracted=False)
    _event(db_session, topic.id, ChangeEventType.NEW_PAPER, datetime.utcnow() - timedelta(days=1),
           paper.id)

    feed = read_change_feed(db_session, days=7, limit=50)

    assert feed["total_events"] == 1
    assert feed["days"][0]["events"][0]["paper"]["title"] == "Anticoagulation in adults over 85"


def test_an_event_with_no_paper_is_always_included(db_session):
    # consensus_updated events have paper_id NULL (evidence_engine/db/models.py:116), so a
    # filter that joined Paper without accounting for null would drop them entirely.
    topic = _topic(db_session)
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED,
           datetime.utcnow() - timedelta(days=1))

    feed = read_change_feed(db_session, days=7, limit=50)

    assert feed["total_events"] == 1
    assert feed["days"][0]["events"][0]["paper"] is None


def test_events_are_grouped_by_day_newest_first(db_session):
    topic = _topic(db_session)
    now = datetime.utcnow()
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED, now - timedelta(days=3))
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED, now - timedelta(days=1))

    feed = read_change_feed(db_session, days=7, limit=50)

    dates = [day["date"] for day in feed["days"]]
    assert dates == sorted(dates, reverse=True)
    assert len(feed["days"]) == 2


def test_events_within_a_day_are_newest_first(db_session):
    topic = _topic(db_session)
    day = datetime.utcnow() - timedelta(days=1)
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED, day.replace(hour=3))
    _event(db_session, topic.id, ChangeEventType.CONTRADICTION_FLAGGED, day.replace(hour=9))

    events = read_change_feed(db_session, days=7, limit=50)["days"][0]["events"]

    assert events[0]["event_type"] == "contradiction_flagged"


def test_the_window_excludes_older_events(db_session):
    topic = _topic(db_session)
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED,
           datetime.utcnow() - timedelta(days=20))

    assert read_change_feed(db_session, days=7, limit=50)["total_events"] == 0


def test_limit_truncates_the_most_recent_events_overall(db_session):
    # The cap is on total events, not per day: the feed is a recency window, not a
    # browsable archive, so truncating per day would hide a busy day's newest items.
    topic = _topic(db_session)
    now = datetime.utcnow()
    for index in range(6):
        _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED,
               now - timedelta(days=1, minutes=index))

    feed = read_change_feed(db_session, days=7, limit=4)

    assert feed["total_events"] == 4


def test_an_empty_feed_is_not_an_error(db_session):
    assert read_change_feed(db_session, days=7, limit=50) == {"days": [], "total_events": 0}


def test_each_event_carries_its_topic_label(db_session):
    topic = _topic(db_session, "GLP-1 receptor agonists")
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED,
           datetime.utcnow() - timedelta(days=1))

    event = read_change_feed(db_session, days=7, limit=50)["days"][0]["events"][0]

    assert event["topic"]["canonical_label"] == "GLP-1 receptor agonists"
    assert event["topic"]["id"] == str(topic.id)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/dashboard/test_changes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.changes'`.

- [ ] **Step 3: Write `dashboard/changes.py`**

```python
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from dashboard.activity import _iso
from evidence_engine.db.models import ChangeEvent, ChangeEventType, Paper, Score, Topic


def read_change_feed(session: Session, days: int, limit: int) -> dict:
    """Recent change events, grouped by calendar day, newest first.

    Retraction filter (spec 14.3): an event is included when it is itself a retraction,
    or has no paper, or its paper is not retracted. The effect is that a paper later found
    to be retracted stops being advertised as new evidence, while the retraction itself
    stays visible -- which is the event a researcher most needs to see.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)

    rows = session.execute(
        select(ChangeEvent, Topic, Paper, Score)
        .join(Topic, Topic.id == ChangeEvent.topic_id)
        .outerjoin(Paper, Paper.id == ChangeEvent.paper_id)
        .outerjoin(Score, Score.paper_id == ChangeEvent.paper_id)
        .where(
            ChangeEvent.detected_at > cutoff,
            or_(
                ChangeEvent.event_type == ChangeEventType.PAPER_RETRACTED,
                ChangeEvent.paper_id.is_(None),
                Paper.is_retracted.is_(False),
            ),
        )
        .order_by(ChangeEvent.detected_at.desc())
        .limit(limit)
    ).all()

    days_out: list[dict] = []
    index_by_date: dict[str, int] = {}
    for event, topic, paper, score in rows:
        date_key = event.detected_at.date().isoformat()
        if date_key not in index_by_date:
            index_by_date[date_key] = len(days_out)
            days_out.append({"date": date_key, "events": []})
        days_out[index_by_date[date_key]]["events"].append(
            {
                "event_type": event.event_type.value,
                "detected_at": _iso(event.detected_at),
                "topic": {"id": str(topic.id), "canonical_label": topic.canonical_label},
                "paper": None
                if paper is None
                else {"id": str(paper.id), "title": paper.title},
                # A pending Score carries column defaults (evidence_tier='speculative'),
                # so surfacing it would label an unscored paper as speculative evidence --
                # the defect sub-project A shipped once. Treated as no tier instead.
                "evidence_tier": score.evidence_tier.value
                if score is not None and not score.is_pending and score.evidence_tier
                else None,
            }
        )

    return {"days": days_out, "total_events": len(rows)}
```

- [ ] **Step 4: Run the tests**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/dashboard/test_changes.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add dashboard/changes.py tests/dashboard/test_changes.py
git commit -m "feat: add dashboard change feed with retraction filtering"
```

---

## Task 6: Personal Summary, Blurb, and Interest Management

**Files:**
- Create: `dashboard/personal.py`, `dashboard/interests.py`
- Test: `tests/dashboard/test_personal.py`, `tests/dashboard/test_interests.py`

**Interfaces:**
- Consumes: `dashboard.windows.window_for` (Task 2), `dashboard.activity._iso` (Task 4), `dashboard.models.DashboardRateWindow` (Task 1), `digest.profiles.add_interest` / `remove_interest` (existing, unmodified).
- Produces: `personal_topic_summary(session, user_id: UUID, days: int) -> dict`; `render_blurb(summary: dict) -> str | None`; `RATE_LIMIT_PER_HOUR: int`; `add_user_interest(session, user_id: UUID, free_text: str, now: datetime | None = None) -> tuple[Topic, bool]`; `remove_user_interest(session, user_id: UUID, topic_id: UUID) -> None`; `RateLimitExceeded` exception. Task 7's endpoints call all of these.

Two hazards live here. The profile-resolution rule (§14.4) is the reason this package does not reuse `digest.aggregate`. The rate limit is the reason `POST /interests` cannot be a thin pass-through: it triggers an outbound PubMed call.

- [ ] **Step 1: Write the failing test for the summary**

Create `tests/dashboard/test_personal.py`:

```python
import uuid
from datetime import datetime, timedelta

import pytest

from dashboard.personal import personal_topic_summary, render_blurb
from digest.models import InterestProfile, ProfileTopic
from digest.profiles import create_anonymous_user
from evidence_engine.db.models import ChangeEvent, ChangeEventType, Topic


def _topic(db_session, label):
    topic = Topic(canonical_label=label)
    db_session.add(topic)
    db_session.flush()
    return topic


def _interested(db_session, user, *topics):
    profile = InterestProfile(user_id=user.id)
    db_session.add(profile)
    db_session.flush()
    for topic in topics:
        db_session.add(ProfileTopic(profile_id=profile.id, topic_id=topic.id))
    db_session.flush()
    return profile


def _event(db_session, topic_id, event_type, days_ago):
    db_session.add(
        ChangeEvent(
            topic_id=topic_id,
            event_type=event_type,
            detected_at=datetime.utcnow() - timedelta(days=days_ago),
        )
    )
    db_session.flush()


def test_personal_endpoint_returns_empty_for_user_without_profile(db_session):
    # Every user from create_anonymous_user lacks a profile, so this is the COMMON case
    # on this surface, not an edge case. digest.profiles.list_interests would raise
    # NoResultFound here via _get_profile's .scalar_one() (digest/profiles.py:34) --
    # which is exactly why this package resolves the profile itself.
    user = create_anonymous_user(db_session)

    summary = personal_topic_summary(db_session, user.id, days=7)

    assert summary == {
        "has_profile": False,
        "computed_at": None,
        "window_start": None,
        "window_end": None,
        "topics": [],
    }


def test_an_unknown_user_raises_rather_than_reporting_no_profile(db_session):
    # A typo'd user_id must not look identical to a real user who has not personalised;
    # the endpoint turns this into a 404.
    with pytest.raises(LookupError):
        personal_topic_summary(db_session, uuid.uuid4(), days=7)


def test_counts_cover_exactly_the_users_interest_topics(db_session):
    user = create_anonymous_user(db_session)
    mine = _topic(db_session, "Atrial fibrillation")
    theirs = _topic(db_session, "Someone else's topic")
    _interested(db_session, user, mine)
    _event(db_session, mine.id, ChangeEventType.NEW_PAPER, 1)
    _event(db_session, theirs.id, ChangeEventType.NEW_PAPER, 1)

    summary = personal_topic_summary(db_session, user.id, days=7)

    assert [t["topic"]["canonical_label"] for t in summary["topics"]] == ["Atrial fibrillation"]
    assert summary["topics"][0]["event_count"] == 1


def test_a_quiet_interest_topic_is_listed_with_a_zero_count(db_session):
    # FR-C-008. Dropping silent topics would make the widget look like the user has
    # fewer interests than they do, and "no change this week" is itself information.
    user = create_anonymous_user(db_session)
    quiet = _topic(db_session, "Sepsis biomarkers")
    _interested(db_session, user, quiet)

    summary = personal_topic_summary(db_session, user.id, days=7)

    assert summary["topics"][0]["event_count"] == 0
    assert summary["topics"][0]["latest_event_at"] is None
    assert summary["topics"][0]["breakdown"]["new_paper"] == 0


def test_the_breakdown_and_latest_event_are_reported(db_session):
    user = create_anonymous_user(db_session)
    topic = _topic(db_session, "Mixed")
    _interested(db_session, user, topic)
    _event(db_session, topic.id, ChangeEventType.NEW_PAPER, 3)
    _event(db_session, topic.id, ChangeEventType.CONSENSUS_UPDATED, 1)

    row = personal_topic_summary(db_session, user.id, days=7)["topics"][0]

    assert row["event_count"] == 2
    assert row["breakdown"] == {
        "new_paper": 1,
        "consensus_updated": 1,
        "contradiction_flagged": 0,
        "paper_retracted": 0,
    }
    assert row["latest_event_at"] is not None


def test_topics_are_ordered_by_when_the_user_added_them(db_session):
    # Matches list_interests' ordering (digest/profiles.py:67), so the dashboard and any
    # future interest list agree.
    user = create_anonymous_user(db_session)
    first = _topic(db_session, "Added first")
    second = _topic(db_session, "Added second")
    profile = InterestProfile(user_id=user.id)
    db_session.add(profile)
    db_session.flush()
    db_session.add(ProfileTopic(profile_id=profile.id, topic_id=first.id,
                                added_at=datetime(2026, 1, 1)))
    db_session.add(ProfileTopic(profile_id=profile.id, topic_id=second.id,
                                added_at=datetime(2026, 6, 1)))
    db_session.flush()

    labels = [t["topic"]["canonical_label"]
              for t in personal_topic_summary(db_session, user.id, days=7)["topics"]]

    assert labels == ["Added first", "Added second"]


def test_the_blurb_is_a_deterministic_sentence(db_session):
    # Deliberately NOT LLM-written (plan decision, OQ-C-002). A templated sentence is
    # honest in a way generated prose would not be, costs nothing, and cannot hallucinate.
    summary = {
        "has_profile": True,
        "topics": [
            {"event_count": 10, "breakdown": {"new_paper": 9, "consensus_updated": 1,
                                              "contradiction_flagged": 0, "paper_retracted": 0}},
            {"event_count": 2, "breakdown": {"new_paper": 1, "consensus_updated": 1,
                                             "contradiction_flagged": 0, "paper_retracted": 0}},
            {"event_count": 0, "breakdown": {"new_paper": 0, "consensus_updated": 0,
                                             "contradiction_flagged": 0, "paper_retracted": 0}},
        ],
    }

    assert render_blurb(summary) == (
        "10 new papers and 2 consensus updates across your 3 topics this week."
    )


def test_the_blurb_uses_singular_forms_where_appropriate(db_session):
    summary = {
        "has_profile": True,
        "topics": [
            {"event_count": 1, "breakdown": {"new_paper": 1, "consensus_updated": 0,
                                             "contradiction_flagged": 0, "paper_retracted": 0}},
        ],
    }

    assert render_blurb(summary) == "1 new paper across your 1 topic this week."


def test_the_blurb_says_nothing_changed_rather_than_listing_zeros(db_session):
    summary = {
        "has_profile": True,
        "topics": [
            {"event_count": 0, "breakdown": {"new_paper": 0, "consensus_updated": 0,
                                             "contradiction_flagged": 0, "paper_retracted": 0}},
        ],
    }

    assert render_blurb(summary) == "No change in your 1 topic this week."


def test_there_is_no_blurb_without_a_profile(db_session):
    assert render_blurb({"has_profile": False, "topics": []}) is None


def test_the_blurb_never_uses_forbidden_copy(db_session):
    forbidden = ["trending", "hot", "popular", "breakthrough", "important",
                 "momentum", "real-time", "live"]
    summary = {
        "has_profile": True,
        "topics": [
            {"event_count": 40, "breakdown": {"new_paper": 30, "consensus_updated": 4,
                                              "contradiction_flagged": 4, "paper_retracted": 2}},
        ],
    }

    text = render_blurb(summary).lower()

    for word in forbidden:
        assert word not in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/dashboard/test_personal.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.personal'`.

- [ ] **Step 3: Write `dashboard/personal.py`**

```python
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dashboard.activity import _iso
from digest.models import InterestProfile, ProfileTopic, User
from evidence_engine.db.models import ChangeEvent, ChangeEventType, Topic

_TYPE_FIELDS = {
    ChangeEventType.NEW_PAPER: "new_paper",
    ChangeEventType.CONSENSUS_UPDATED: "consensus_updated",
    ChangeEventType.CONTRADICTION_FLAGGED: "contradiction_flagged",
    ChangeEventType.PAPER_RETRACTED: "paper_retracted",
}


def _empty_breakdown() -> dict:
    return {field: 0 for field in _TYPE_FIELDS.values()}


def personal_topic_summary(session: Session, user_id: uuid.UUID, days: int) -> dict:
    """Per-topic change counts for exactly the user's interest topics.

    Resolves the profile with scalar_one_or_none rather than calling
    digest.profiles.list_interests, which reaches _get_profile's .scalar_one()
    (digest/profiles.py:34) and raises NoResultFound. Every user created by
    create_anonymous_user lacks a profile, so the raising path is the COMMON case on this
    surface -- a dashboard that 500s for every first-time visitor.

    Raises LookupError for a user_id that matches no User, which the endpoint turns into
    a 404: a typo'd id must not be indistinguishable from a real user who has simply not
    personalised yet.
    """
    user = session.get(User, user_id)
    if user is None:
        raise LookupError(f"User {user_id} not found")

    profile = session.execute(
        select(InterestProfile).where(InterestProfile.user_id == user_id)
    ).scalar_one_or_none()
    if profile is None:
        return {
            "has_profile": False,
            "computed_at": None,
            "window_start": None,
            "window_end": None,
            "topics": [],
        }

    links = session.execute(
        select(ProfileTopic, Topic)
        .join(Topic, Topic.id == ProfileTopic.topic_id)
        .where(ProfileTopic.profile_id == profile.id)
        # Matches list_interests' ordering (digest/profiles.py:67).
        .order_by(ProfileTopic.added_at)
    ).all()

    now = datetime.utcnow()
    window_start = now - timedelta(days=days)
    topic_ids = [topic.id for _, topic in links]

    counts: dict = {}
    latest: dict = {}
    if topic_ids:
        rows = session.execute(
            select(
                ChangeEvent.topic_id,
                ChangeEvent.event_type,
                func.count().label("n"),
                func.max(ChangeEvent.detected_at).label("latest"),
            )
            .where(
                ChangeEvent.topic_id.in_(topic_ids),
                ChangeEvent.detected_at > window_start,
                ChangeEvent.detected_at <= now,
            )
            .group_by(ChangeEvent.topic_id, ChangeEvent.event_type)
        ).all()
        for topic_id, event_type, n, most_recent in rows:
            bucket = counts.setdefault(topic_id, _empty_breakdown())
            field = _TYPE_FIELDS.get(event_type)
            if field is not None:
                bucket[field] += n
            if topic_id not in latest or most_recent > latest[topic_id]:
                latest[topic_id] = most_recent

    return {
        "has_profile": True,
        "computed_at": _iso(now),
        "window_start": _iso(window_start),
        "window_end": _iso(now),
        "topics": [
            {
                "topic": {"id": str(topic.id), "canonical_label": topic.canonical_label},
                # Topics with no events are listed with a zero count (FR-C-008): dropping
                # them would make the widget look like the user has fewer interests than
                # they do, and "no change this week" is itself information.
                "event_count": sum(counts.get(topic.id, _empty_breakdown()).values()),
                "breakdown": counts.get(topic.id, _empty_breakdown()),
                "latest_event_at": _iso(latest.get(topic.id)),
            }
            for _, topic in links
        ],
    }


def _plural(count: int, singular: str) -> str:
    return f"{count} {singular}" if count == 1 else f"{count} {singular}s"


def render_blurb(summary: dict) -> str | None:
    """A deterministic sentence summarising the window. Never LLM-written.

    Plan decision (OQ-C-002): this delivers most of the reference design's "blurb" value
    with zero model cost and no hallucination risk, and is honest in a way generated prose
    would not be. Sub-project B may later replace it with a real narrative.

    Built with an f-string rather than Jinja2: the template is one sentence with no
    control flow beyond pluralisation, and a template file would put the copy rules
    (FR-C-015) somewhere the tests asserting them do not look.
    """
    if not summary.get("has_profile"):
        return None

    topics = summary.get("topics", [])
    topic_phrase = _plural(len(topics), "topic")

    totals = {field: 0 for field in _TYPE_FIELDS.values()}
    for row in topics:
        for field, value in row.get("breakdown", {}).items():
            totals[field] = totals.get(field, 0) + value

    parts = []
    if totals["new_paper"]:
        parts.append(_plural(totals["new_paper"], "new paper"))
    if totals["consensus_updated"]:
        parts.append(_plural(totals["consensus_updated"], "consensus update"))
    if totals["contradiction_flagged"]:
        parts.append(_plural(totals["contradiction_flagged"], "flagged contradiction"))
    if totals["paper_retracted"]:
        parts.append(_plural(totals["paper_retracted"], "retraction"))

    if not parts:
        # "No change this week", never "nothing found" or "no results" (FR-C-015).
        return f"No change in your {topic_phrase} this week."

    if len(parts) == 1:
        subject = parts[0]
    else:
        subject = ", ".join(parts[:-1]) + f" and {parts[-1]}"
    return f"{subject} across your {topic_phrase} this week."
```

- [ ] **Step 4: Run the tests**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/dashboard/test_personal.py -v`
Expected: 11 passed.

- [ ] **Step 5: Write the failing test for interests**

Create `tests/dashboard/test_interests.py`:

```python
import uuid
from datetime import datetime, timedelta

import pytest

from dashboard.interests import (
    RATE_LIMIT_PER_HOUR,
    RateLimitExceeded,
    add_user_interest,
    remove_user_interest,
)
from digest.models import InterestProfile
from digest.profiles import create_anonymous_user
from evidence_engine.db.models import Topic
from sqlalchemy import select

NOW = datetime(2026, 8, 2, 9, 30)


@pytest.fixture(autouse=True)
def _no_pubmed(monkeypatch):
    """get_or_create_topic reaches PubMed. No test may make that call."""
    def fake_get_or_create_topic(session, free_text):
        existing = session.execute(
            select(Topic).where(Topic.canonical_label == free_text.title())
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        topic = Topic(canonical_label=free_text.title())
        session.add(topic)
        session.flush()
        return topic

    monkeypatch.setattr("digest.profiles.get_or_create_topic", fake_get_or_create_topic)


def test_the_first_interest_creates_the_profile(db_session):
    # FR-C-013. create_anonymous_user writes no profile (digest/profiles.py:23), and
    # digest's own add_interest would raise NoResultFound on that user.
    user = create_anonymous_user(db_session)

    topic, created = add_user_interest(db_session, user.id, "atrial fibrillation", now=NOW)

    assert created is True
    assert topic.canonical_label == "Atrial Fibrillation"
    profile = db_session.execute(
        select(InterestProfile).where(InterestProfile.user_id == user.id)
    ).scalar_one()
    assert profile is not None


def test_adding_the_same_interest_twice_is_idempotent(db_session):
    user = create_anonymous_user(db_session)
    add_user_interest(db_session, user.id, "sepsis biomarkers", now=NOW)

    _, created = add_user_interest(db_session, user.id, "sepsis biomarkers", now=NOW)

    assert created is False


def test_an_unknown_user_raises(db_session):
    with pytest.raises(LookupError):
        add_user_interest(db_session, uuid.uuid4(), "anything", now=NOW)


def test_blank_free_text_is_rejected(db_session):
    user = create_anonymous_user(db_session)

    with pytest.raises(ValueError):
        add_user_interest(db_session, user.id, "   ", now=NOW)


def test_the_rate_limit_blocks_the_call_that_exceeds_it(db_session):
    # This endpoint triggers an outbound PubMed call, so it is the one C route with an
    # external dependency and the only one that can be abused into hammering a provider.
    user = create_anonymous_user(db_session)
    for index in range(RATE_LIMIT_PER_HOUR):
        add_user_interest(db_session, user.id, f"topic {index}", now=NOW)

    with pytest.raises(RateLimitExceeded):
        add_user_interest(db_session, user.id, "one too many", now=NOW)


def test_the_counter_resets_in_the_next_hour(db_session):
    user = create_anonymous_user(db_session)
    for index in range(RATE_LIMIT_PER_HOUR):
        add_user_interest(db_session, user.id, f"topic {index}", now=NOW)

    topic, _ = add_user_interest(db_session, user.id, "next hour", now=NOW + timedelta(hours=1))

    assert topic is not None


def test_the_limit_is_per_user_not_global(db_session):
    first = create_anonymous_user(db_session)
    second = create_anonymous_user(db_session)
    for index in range(RATE_LIMIT_PER_HOUR):
        add_user_interest(db_session, first.id, f"topic {index}", now=NOW)

    topic, _ = add_user_interest(db_session, second.id, "mine", now=NOW)

    assert topic is not None


def test_a_rejected_request_does_not_consume_quota_from_the_next_hour(db_session):
    # The counter increments before the outbound call, so a blocked request must not also
    # poison the following window.
    user = create_anonymous_user(db_session)
    for index in range(RATE_LIMIT_PER_HOUR):
        add_user_interest(db_session, user.id, f"topic {index}", now=NOW)
    with pytest.raises(RateLimitExceeded):
        add_user_interest(db_session, user.id, "blocked", now=NOW)

    topic, _ = add_user_interest(db_session, user.id, "allowed", now=NOW + timedelta(hours=1))

    assert topic is not None


def test_removing_an_interest_leaves_the_profile(db_session):
    user = create_anonymous_user(db_session)
    topic, _ = add_user_interest(db_session, user.id, "removable", now=NOW)

    remove_user_interest(db_session, user.id, topic.id)

    profile = db_session.execute(
        select(InterestProfile).where(InterestProfile.user_id == user.id)
    ).scalar_one()
    assert profile is not None


def test_removing_an_interest_the_user_does_not_have_raises(db_session):
    user = create_anonymous_user(db_session)
    add_user_interest(db_session, user.id, "kept", now=NOW)

    with pytest.raises(LookupError):
        remove_user_interest(db_session, user.id, uuid.uuid4())


def test_removing_from_a_user_with_no_profile_raises(db_session):
    user = create_anonymous_user(db_session)

    with pytest.raises(LookupError):
        remove_user_interest(db_session, user.id, uuid.uuid4())
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/dashboard/test_interests.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.interests'`.

- [ ] **Step 7: Write `dashboard/interests.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from dashboard.models import DashboardRateWindow
from digest.models import InterestProfile, ProfileTopic, User
from digest.profiles import add_interest, remove_interest
from evidence_engine.db.models import Topic

# POST /interests triggers an outbound PubMed term resolution inside get_or_create_topic,
# so it is the one C endpoint with an external dependency. Read endpoints are single
# indexed queries and are not limited.
RATE_LIMIT_PER_HOUR = 30
MAX_FREE_TEXT = 200


class RateLimitExceeded(Exception):
    """Raised when a user exceeds RATE_LIMIT_PER_HOUR adds in one clock hour."""


def _hour_start(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0)


def _consume_quota(session: Session, user_id: uuid.UUID, now: datetime) -> None:
    """Increment this user's counter for the current hour, or refuse.

    Fixed clock-hour windows rather than a rolling window: one row per user per hour,
    countable with an index, and the imprecision at a boundary is irrelevant for a limit
    whose job is to stop abuse rather than to meter fairly.
    """
    window_start = _hour_start(now)
    subject = f"user:{user_id}"
    counter = session.execute(
        select(DashboardRateWindow).where(
            DashboardRateWindow.subject == subject,
            DashboardRateWindow.window_start == window_start,
        )
    ).scalar_one_or_none()

    if counter is None:
        counter = DashboardRateWindow(subject=subject, window_start=window_start, request_count=0)
        session.add(counter)
        session.flush()

    if counter.request_count >= RATE_LIMIT_PER_HOUR:
        raise RateLimitExceeded(
            f"Limit of {RATE_LIMIT_PER_HOUR} interest additions per hour reached"
        )

    counter.request_count += 1
    session.flush()


def _require_user(session: Session, user_id: uuid.UUID) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise LookupError(f"User {user_id} not found")
    return user


def add_user_interest(
    session: Session, user_id: uuid.UUID, free_text: str, now: datetime | None = None
) -> tuple[Topic, bool]:
    """Add an interest topic, creating the InterestProfile on first use (FR-C-013).

    digest.profiles.add_interest cannot be called directly for a fresh user: it goes
    through _get_profile's .scalar_one() (digest/profiles.py:34), which raises for every
    user create_anonymous_user made. Creating the profile here is safe -- commit a5a4117
    guarded select_due_users against a profile without a DeliveryPreference, which is
    exactly the shape this creates (OQ-C-001).

    Returns (topic, created) where created is False if the user already had this interest.
    """
    user = _require_user(session, user_id)

    text = (free_text or "").strip()
    if not text:
        raise ValueError("free_text must not be empty")
    if len(text) > MAX_FREE_TEXT:
        raise ValueError(f"free_text must be {MAX_FREE_TEXT} characters or fewer")

    # Charged before the outbound call, so a burst cannot slip through while requests are
    # in flight.
    _consume_quota(session, user_id, now or datetime.utcnow())

    profile = session.execute(
        select(InterestProfile).where(InterestProfile.user_id == user_id)
    ).scalar_one_or_none()
    if profile is None:
        profile = InterestProfile(user_id=user_id)
        session.add(profile)
        session.flush()

    before = session.execute(
        select(ProfileTopic).where(ProfileTopic.profile_id == profile.id)
    ).scalars().all()
    existing_ids = {link.topic_id for link in before}

    topic = add_interest(session, user, text)
    return topic, topic.id not in existing_ids


def remove_user_interest(session: Session, user_id: uuid.UUID, topic_id: uuid.UUID) -> None:
    """Remove an interest. Raises LookupError if the user or the interest is absent.

    Not idempotent on repeat, matching DELETE /saved-searches/{id}'s existing contract.
    """
    user = _require_user(session, user_id)

    profile = session.execute(
        select(InterestProfile).where(InterestProfile.user_id == user_id)
    ).scalar_one_or_none()
    if profile is None:
        raise LookupError("User has no interest profile")

    link = session.execute(
        select(ProfileTopic).where(
            ProfileTopic.profile_id == profile.id, ProfileTopic.topic_id == topic_id
        )
    ).scalar_one_or_none()
    if link is None:
        raise LookupError(f"Interest {topic_id} not found for this user")

    remove_interest(session, user, topic_id)
```

- [ ] **Step 8: Run the tests**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/dashboard/ -v`
Expected: all pass.

- [ ] **Step 9: Run the full suite**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest -q`
Expected: no regressions. In particular `tests/digest/` must be unchanged — this task calls `digest.profiles` but modifies nothing in it.

- [ ] **Step 10: Commit**

```bash
git add dashboard/personal.py dashboard/interests.py tests/dashboard/test_personal.py tests/dashboard/test_interests.py
git commit -m "feat: add personal dashboard summary, blurb, and interest management"
```

---

## Task 7: HTTP Endpoints

**Files:**
- Modify: `webapp/api.py` (add five routes **above** the `StaticFiles` mount at line 333)
- Test: `tests/webapp/test_api.py` (append)

**Interfaces:**
- Consumes: `dashboard.activity.read_current_activity`, `dashboard.changes.read_change_feed`, `dashboard.personal.personal_topic_summary` / `render_blurb`, `dashboard.interests.add_user_interest` / `remove_user_interest` / `RateLimitExceeded`.
- Produces: `GET /dashboard/activity`, `GET /dashboard/changes`, `GET /dashboard/personal`, `POST /interests`, `DELETE /interests/{topic_id}`. Task 8's hooks call all five.

- [ ] **Step 1: Write the failing tests**

Append to `tests/webapp/test_api.py`:

```python
def test_dashboard_activity_is_empty_before_the_job_has_run(db_session):
    client = _client(db_session)

    body = client.get("/dashboard/activity").json()

    assert body == {"computed_at": None, "window_start": None, "window_end": None, "topics": []}


def test_dashboard_activity_rejects_an_out_of_range_limit(db_session):
    client = _client(db_session)

    assert client.get("/dashboard/activity?limit=0").status_code == 422
    assert client.get("/dashboard/activity?limit=26").status_code == 422
    assert client.get("/dashboard/activity?limit=25").status_code == 200
    assert client.get("/dashboard/activity?limit=1").status_code == 200


def test_dashboard_changes_rejects_out_of_range_parameters(db_session):
    client = _client(db_session)

    assert client.get("/dashboard/changes?days=0").status_code == 422
    assert client.get("/dashboard/changes?days=31").status_code == 422
    assert client.get("/dashboard/changes?limit=51").status_code == 422
    assert client.get("/dashboard/changes?days=30&limit=50").status_code == 200


def test_dashboard_personal_returns_200_and_no_profile_for_a_fresh_user(db_session):
    # The cold-start case, and the one that must never 500: every anonymous user starts
    # without an InterestProfile.
    from digest.profiles import create_anonymous_user

    user = create_anonymous_user(db_session)
    client = _client(db_session)

    response = client.get(f"/dashboard/personal?user_id={user.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["has_profile"] is False
    assert body["topics"] == []
    assert body["blurb"] is None


def test_dashboard_personal_404s_for_an_unknown_user(db_session):
    client = _client(db_session)

    assert client.get(f"/dashboard/personal?user_id={uuid.uuid4()}").status_code == 404


def test_dashboard_personal_422s_for_a_malformed_user_id(db_session):
    client = _client(db_session)

    assert client.get("/dashboard/personal?user_id=not-a-uuid").status_code == 422


def test_post_interests_creates_and_is_idempotent(db_session, monkeypatch):
    from digest.profiles import create_anonymous_user
    from evidence_engine.db.models import Topic

    def fake_get_or_create_topic(session, free_text):
        from sqlalchemy import select as _select

        existing = session.execute(
            _select(Topic).where(Topic.canonical_label == free_text)
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        topic = Topic(canonical_label=free_text)
        session.add(topic)
        session.flush()
        return topic

    monkeypatch.setattr("digest.profiles.get_or_create_topic", fake_get_or_create_topic)
    user = create_anonymous_user(db_session)
    client = _client(db_session)

    first = client.post("/interests", json={"user_id": str(user.id), "free_text": "sepsis"})
    assert first.status_code == 201
    assert first.json()["created"] is True

    second = client.post("/interests", json={"user_id": str(user.id), "free_text": "sepsis"})
    assert second.status_code == 200
    assert second.json()["created"] is False


def test_post_interests_422s_on_empty_text(db_session):
    from digest.profiles import create_anonymous_user

    user = create_anonymous_user(db_session)
    client = _client(db_session)

    response = client.post("/interests", json={"user_id": str(user.id), "free_text": "  "})

    assert response.status_code == 422


def test_post_interests_404s_for_an_unknown_user(db_session):
    client = _client(db_session)

    response = client.post(
        "/interests", json={"user_id": str(uuid.uuid4()), "free_text": "sepsis"}
    )

    assert response.status_code == 404


def test_post_interests_429s_when_rate_limited(db_session, monkeypatch):
    # 429, not 422: the request is well-formed and will succeed later. Sending 422 would
    # tell the client its input was wrong and invite it to retry immediately.
    from dashboard.interests import RateLimitExceeded

    def raising(*args, **kwargs):
        raise RateLimitExceeded("too many")

    monkeypatch.setattr("webapp.api.add_user_interest", raising)
    client = _client(db_session)

    response = client.post(
        "/interests", json={"user_id": str(uuid.uuid4()), "free_text": "sepsis"}
    )

    assert response.status_code == 429


def test_delete_interests_returns_204_then_404(db_session, monkeypatch):
    from digest.profiles import create_anonymous_user
    from evidence_engine.db.models import Topic

    def fake_get_or_create_topic(session, free_text):
        topic = Topic(canonical_label=free_text)
        session.add(topic)
        session.flush()
        return topic

    monkeypatch.setattr("digest.profiles.get_or_create_topic", fake_get_or_create_topic)
    user = create_anonymous_user(db_session)
    client = _client(db_session)
    topic_id = client.post(
        "/interests", json={"user_id": str(user.id), "free_text": "removable"}
    ).json()["topic"]["id"]

    assert client.delete(f"/interests/{topic_id}?user_id={user.id}").status_code == 204
    # Not idempotent on repeat, matching DELETE /saved-searches/{id}.
    assert client.delete(f"/interests/{topic_id}?user_id={user.id}").status_code == 404


def test_dashboard_routes_do_not_shadow_the_static_mount(db_session):
    # The StaticFiles mount catches every unmatched path, so a route declared after it is
    # unreachable. This asserts the file's structure, which no functional test would catch.
    import inspect

    import webapp.api as api_module

    source = inspect.getsource(api_module)
    mount_at = source.index('app.mount("/"')
    for route in ["/dashboard/activity", "/dashboard/changes", "/dashboard/personal"]:
        assert source.index(route) < mount_at, f"{route} is declared after the static mount"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/webapp/test_api.py -v -k "dashboard or interests"`
Expected: FAIL — 404s, because the routes do not exist.

- [ ] **Step 3: Add the imports**

Near the other package imports at the top of `webapp/api.py`:

```python
from dashboard.activity import read_current_activity
from dashboard.changes import read_change_feed
from dashboard.interests import RateLimitExceeded, add_user_interest, remove_user_interest
from dashboard.personal import personal_topic_summary, render_blurb
```

- [ ] **Step 4: Add the routes, above the `StaticFiles` mount**

```python
@app.get("/dashboard/activity")
def dashboard_activity_endpoint(
    limit: int = Query(default=10), db: Session = Depends(get_db)
) -> dict:
    if not 1 <= limit <= 25:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 25")
    return read_current_activity(db, limit=limit)


@app.get("/dashboard/changes")
def dashboard_changes_endpoint(
    days: int = Query(default=7), limit: int = Query(default=20), db: Session = Depends(get_db)
) -> dict:
    if not 1 <= days <= 30:
        raise HTTPException(status_code=422, detail="days must be between 1 and 30")
    if not 1 <= limit <= 50:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 50")
    return read_change_feed(db, days=days, limit=limit)


@app.get("/dashboard/personal")
def dashboard_personal_endpoint(
    user_id: uuid.UUID, days: int = Query(default=7), db: Session = Depends(get_db)
) -> dict:
    if not 1 <= days <= 30:
        raise HTTPException(status_code=422, detail="days must be between 1 and 30")
    try:
        summary = personal_topic_summary(db, user_id, days=days)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # The blurb is deterministic and computed here rather than client-side, so the copy
    # rules live in one tested place.
    summary["blurb"] = render_blurb(summary)
    return summary


@app.post("/interests", status_code=201)
def add_interest_endpoint(payload: dict, response: Response, db: Session = Depends(get_db)) -> dict:
    raw_user_id = payload.get("user_id")
    try:
        user_id = uuid.UUID(str(raw_user_id))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="user_id must be a UUID") from exc

    try:
        topic, created = add_user_interest(db, user_id, payload.get("free_text") or "")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RateLimitExceeded as exc:
        # 429, not 422: the request is well-formed and will succeed later.
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not created:
        response.status_code = 200
    return {
        "topic": {"id": str(topic.id), "canonical_label": topic.canonical_label},
        "created": created,
    }


@app.delete("/interests/{topic_id}", status_code=204)
def remove_interest_endpoint(
    topic_id: uuid.UUID, user_id: uuid.UUID, db: Session = Depends(get_db)
) -> Response:
    try:
        remove_user_interest(db, user_id, topic_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)
```

Add `Response` to the FastAPI imports if it is not already there.

- [ ] **Step 5: Run the tests**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/webapp/ -v`
Expected: all pass, including the pre-existing endpoint tests.

- [ ] **Step 6: Confirm the mount is still last**

```bash
tail -6 webapp/api.py
```

Expected: the `app.mount("/", StaticFiles(...))` block is the final statement.

- [ ] **Step 7: Commit**

```bash
git add webapp/api.py tests/webapp/test_api.py
git commit -m "feat: add dashboard and interest HTTP endpoints"
```

---

## Task 8: Frontend — Types, Hooks, Widgets, and the Dashboard Page

**Files:**
- Modify: `webapp/frontend/src/api/types.ts`, `webapp/frontend/src/api/hooks.ts`
- Create: `webapp/frontend/src/pages/DashboardPage.tsx`, `webapp/frontend/src/components/ActivityWidget.tsx`, `ChangeFeedWidget.tsx`, `PersonalTopicsWidget.tsx`, `StalenessBanner.tsx`
- Test: `webapp/frontend/src/pages/DashboardPage.test.tsx`, `webapp/frontend/src/components/ActivityWidget.test.tsx`

**Interfaces:**
- Consumes: the five endpoints from Task 7; the existing `apiGet`/`apiPost` helpers in `src/api/client.ts`; `useIdentity` from `src/identity/identity`.
- Produces: `ActivityResponse`, `ChangeFeedResponse`, `PersonalDashboardResponse` types; `useActivityRanking`, `useChangeFeed`, `usePersonalDashboard`, `useAddInterest`, `useRemoveInterest` hooks; `<DashboardPage />`.

Read `src/api/hooks.ts`, `src/api/client.ts`, `src/pages/SearchPage.tsx` and `src/components/TierSection.tsx` before writing, and match their conventions. Colours come from design tokens only — no raw hex. Every `material-symbols-outlined` span carries `aria-hidden="true"`.

- [ ] **Step 1: Add the types**

In `src/api/types.ts`:

```ts
export interface ActivityBreakdown {
  new_paper: number;
  consensus_updated: number;
  contradiction_flagged: number;
  paper_retracted: number;
}

export interface ActivityRow {
  topic: TopicRef;
  rank: number;
  event_count: number;
  breakdown: ActivityBreakdown;
  baseline_mean: number | null;
  baseline_weeks: number;
  trend_score: number | null;
  is_newly_tracked: boolean;
}

export interface ActivityResponse {
  computed_at: string | null;
  window_start: string | null;
  window_end: string | null;
  topics: ActivityRow[];
}

export interface ChangeFeedEvent {
  event_type: "new_paper" | "consensus_updated" | "contradiction_flagged" | "paper_retracted";
  detected_at: string;
  topic: TopicRef;
  paper: { id: string; title: string } | null;
  evidence_tier: string | null;
}

export interface ChangeFeedResponse {
  days: { date: string; events: ChangeFeedEvent[] }[];
  total_events: number;
}

export interface PersonalTopicRow {
  topic: TopicRef;
  event_count: number;
  breakdown: ActivityBreakdown;
  latest_event_at: string | null;
}

export interface PersonalDashboardResponse {
  has_profile: boolean;
  computed_at: string | null;
  window_start: string | null;
  window_end: string | null;
  topics: PersonalTopicRow[];
  blurb: string | null;
}
```

- [ ] **Step 2: Add the hooks**

In `src/api/hooks.ts`, matching the surrounding style:

```ts
export function useActivityRanking(limit = 10) {
  return useQuery({
    queryKey: ["dashboard", "activity", limit],
    queryFn: () => apiGet<ActivityResponse>(`/dashboard/activity?limit=${limit}`),
  });
}

export function useChangeFeed(days = 7, limit = 20) {
  return useQuery({
    queryKey: ["dashboard", "changes", days, limit],
    queryFn: () => apiGet<ChangeFeedResponse>(`/dashboard/changes?days=${days}&limit=${limit}`),
  });
}

export function usePersonalDashboard(userId: string | null) {
  return useQuery({
    queryKey: ["dashboard", "personal", userId],
    // Disabled rather than called with a null id: the endpoint requires user_id and
    // would 422, turning the ordinary pre-identity render into an error state.
    enabled: Boolean(userId),
    queryFn: () => apiGet<PersonalDashboardResponse>(`/dashboard/personal?user_id=${userId}`),
  });
}

export function useAddInterest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { userId: string; freeText: string }) =>
      apiPost<{ topic: TopicRef; created: boolean }>("/interests", {
        user_id: input.userId,
        free_text: input.freeText,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["dashboard", "personal"] }),
  });
}

export function useRemoveInterest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { userId: string; topicId: string }) =>
      apiDelete(`/interests/${input.topicId}?user_id=${input.userId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["dashboard", "personal"] }),
  });
}
```

If `apiDelete` does not exist in `src/api/client.ts`, add it in the same shape as `apiPost`, returning `void` for a 204.

- [ ] **Step 3: Write the failing widget test**

Create `src/components/ActivityWidget.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ActivityResponse } from "../api/types";
import { ActivityWidget } from "./ActivityWidget";

function row(overrides = {}) {
  return {
    topic: { id: "t1", canonical_label: "Atrial fibrillation" },
    rank: 1,
    event_count: 24,
    breakdown: { new_paper: 19, consensus_updated: 2, contradiction_flagged: 2, paper_retracted: 1 },
    baseline_mean: 7.375,
    baseline_weeks: 8,
    trend_score: 4.173,
    is_newly_tracked: false,
    ...overrides,
  };
}

function renderWidget(data: Partial<ActivityResponse> = {}) {
  const payload: ActivityResponse = {
    computed_at: "2026-08-02T04:10:22Z",
    window_start: "2026-07-26T00:00:00Z",
    window_end: "2026-08-02T00:00:00Z",
    topics: [row()],
    ...data,
  };
  return render(
    <MemoryRouter>
      <ActivityWidget data={payload} isLoading={false} isError={false} />
    </MemoryRouter>,
  );
}

test("shows each topic's raw event count, not only a score", () => {
  // FR-C-004. A derived score alone is unauditable -- the reader cannot tell whether
  // "4.173" came from 24 events or from 5.
  renderWidget();

  expect(screen.getByText(/24/)).toBeInTheDocument();
});

test("a newly tracked topic shows no change-versus-baseline figure", () => {
  // FR-C-003/004: with fewer than 8 weeks there is no honest baseline to compare against,
  // so showing a percentage would invent one.
  renderWidget({
    topics: [row({ is_newly_tracked: true, trend_score: null, baseline_mean: null, baseline_weeks: 3 })],
  });

  expect(screen.getByText(/newly tracked/i)).toBeInTheDocument();
  expect(screen.queryByText(/%/)).not.toBeInTheDocument();
});

test("every topic row links to its topic detail page", () => {
  // FR-C-012: the dashboard must add no dead ends.
  renderWidget();

  expect(screen.getByRole("link", { name: /atrial fibrillation/i })).toHaveAttribute(
    "href",
    "/topics/t1",
  );
});

test("explains that the ranking measures volume, not significance", () => {
  // FR-C-016. Without this the ranking reads as an editorial judgement about which
  // science matters, which is exactly what it is not.
  renderWidget();

  expect(
    screen.getByTitle(/volume of newly indexed and changed evidence/i),
  ).toBeInTheDocument();
});

const FORBIDDEN = /trending|hot|popular|breakthrough|important|momentum|real-time|\blive\b/i;

test("never uses quality or hype language", () => {
  // FR-C-015. The ranking is volume-based; any of these words claims something about
  // the science itself that the metric cannot support.
  const { container } = renderWidget();

  expect(container.textContent).not.toMatch(FORBIDDEN);
});

test("the empty state says no change rather than no results", () => {
  const { container } = renderWidget({ topics: [], computed_at: null });

  expect(container.textContent).not.toMatch(/no results|nothing found/i);
});
```

- [ ] **Step 4: Run the test to verify it fails**

Run from `webapp/frontend`: `npx vitest run src/components/ActivityWidget.test.tsx`
Expected: FAIL — cannot resolve `./ActivityWidget`.

- [ ] **Step 5: Write `src/components/ActivityWidget.tsx`**

```tsx
import { Link } from "react-router-dom";
import type { ActivityResponse } from "../api/types";

// FR-C-016: the ranking measures how much new evidence was indexed, which is not a claim
// about whether that evidence matters. The tooltip is the only thing standing between the
// list and being read as an editorial judgement.
const EXPLANATION =
  "Ranked by volume of newly indexed and changed evidence in the last 7 days, not by scientific significance.";

export function ActivityWidget({
  data,
  isLoading,
  isError,
}: {
  data: ActivityResponse | undefined;
  isLoading: boolean;
  isError: boolean;
}) {
  return (
    <section className="rounded-lg border border-hairline bg-surface-container-lowest p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-on-surface">Most active topics</h2>
        <span
          tabIndex={0}
          title={EXPLANATION}
          className="text-xs text-on-surface-variant underline decoration-dotted"
        >
          What does this mean?
        </span>
      </div>

      {isLoading && <p className="text-xs text-on-surface-variant">Loading…</p>}
      {isError && (
        <p className="text-xs text-error">
          Couldn&apos;t load topic activity. The rest of the dashboard is unaffected.
        </p>
      )}

      {data && data.topics.length === 0 && !isLoading && (
        <p className="text-xs text-on-surface-variant">
          No topic reached the activity threshold this week.
        </p>
      )}

      <ol className="space-y-2">
        {data?.topics.map((row) => (
          <li key={row.topic.id} className="flex items-baseline gap-2 text-xs">
            <span className="w-5 text-on-surface-variant">{row.rank}.</span>
            <Link
              to={`/topics/${row.topic.id}`}
              className="font-medium text-primary-container hover:underline"
            >
              {row.topic.canonical_label}
            </Link>
            {/* The raw count is always shown (FR-C-004): a derived score alone is
                unauditable, since the reader cannot tell 24 events from 5. */}
            <span className="text-on-surface-variant">
              {row.event_count} {row.event_count === 1 ? "change" : "changes"}
            </span>
            {row.is_newly_tracked && (
              // "Newly tracked", never "new topic" -- the topic may be decades old; it is
              // our tracking of it that is new.
              <span className="rounded bg-surface-container px-1.5 text-on-surface-variant">
                Newly tracked
              </span>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
```

- [ ] **Step 6: Run the widget test**

Run: `npx vitest run src/components/ActivityWidget.test.tsx`
Expected: 6 passed.

- [ ] **Step 7: Write `StalenessBanner.tsx`**

```tsx
const STALE_AFTER_HOURS = 36;

export function StalenessBanner({ computedAt }: { computedAt: string | null }) {
  if (!computedAt) return null;
  const ageHours = (Date.now() - new Date(computedAt).getTime()) / 3_600_000;
  if (ageHours <= STALE_AFTER_HOURS) return null;

  // FR-C-011. The job runs daily, so 36 hours means at least one run was missed. Saying
  // so is the difference between a user distrusting the numbers and distrusting the app.
  return (
    <p role="status" className="mb-4 rounded border border-outline-variant bg-surface-container-low p-2 text-xs text-on-surface-variant">
      Data as of {new Date(computedAt).toLocaleString()} — the daily refresh has not run since.
    </p>
  );
}
```

- [ ] **Step 8: Write `src/components/ChangeFeedWidget.tsx`**

```tsx
import { Link } from "react-router-dom";
import type { ChangeFeedEvent, ChangeFeedResponse } from "../api/types";

// Retractions and contradictions are the highest-signal events and the ones that would
// otherwise be buried: in a typical window `new_paper` outnumbers the other three types
// combined. There is deliberately no type filter in v1 (OQ-C-005) -- this visual
// distinction is what does the work a filter would.
const WARNING_TYPES = new Set(["paper_retracted", "contradiction_flagged"]);

const LABELS: Record<ChangeFeedEvent["event_type"], string> = {
  new_paper: "New paper",
  consensus_updated: "Consensus updated",
  contradiction_flagged: "Contradiction flagged",
  paper_retracted: "Retracted",
};

function EventRow({ event }: { event: ChangeFeedEvent }) {
  const isWarning = WARNING_TYPES.has(event.event_type);
  return (
    <li className="flex items-baseline gap-2 text-xs">
      <span
        className={
          isWarning
            ? "shrink-0 rounded border border-error/40 px-1.5 font-semibold text-error"
            : "shrink-0 rounded bg-surface-container px-1.5 text-on-surface-variant"
        }
      >
        {LABELS[event.event_type]}
      </span>
      {/* Links to the TOPIC, not the paper: sub-project A gives papers no detail route,
          and FR-C-012 requires every row to reach a real destination. */}
      <Link to={`/topics/${event.topic.id}`} className="text-primary-container hover:underline">
        {event.topic.canonical_label}
      </Link>
      {event.paper && <span className="text-on-surface-variant">{event.paper.title}</span>}
    </li>
  );
}

export function ChangeFeedWidget({
  data,
  isLoading,
  isError,
}: {
  data: ChangeFeedResponse | undefined;
  isLoading: boolean;
  isError: boolean;
}) {
  return (
    <section className="rounded-lg border border-hairline bg-surface-container-lowest p-4">
      <h2 className="mb-3 text-sm font-semibold text-on-surface">What changed</h2>

      {isLoading && <p className="text-xs text-on-surface-variant">Loading…</p>}
      {/* Rendered here rather than thrown: one endpoint failing must not blank the
          dashboard, so every widget owns its own error surface. */}
      {isError && (
        <p className="text-xs text-error">
          Couldn&apos;t load recent changes. The rest of the dashboard is unaffected.
        </p>
      )}

      {data && data.total_events === 0 && !isLoading && (
        // "No change", never "no results" (FR-C-015).
        <p className="text-xs text-on-surface-variant">No change recorded in this period.</p>
      )}

      <div className="space-y-3">
        {data?.days.map((day) => (
          <div key={day.date}>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
              {new Date(`${day.date}T00:00:00Z`).toLocaleDateString(undefined, {
                day: "numeric",
                month: "short",
                timeZone: "UTC",
              })}
            </p>
            <ul className="space-y-1">
              {day.events.map((event, index) => (
                <EventRow key={`${event.detected_at}-${index}`} event={event} />
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
```

The date is formatted with `timeZone: "UTC"` deliberately. `day.date` is a calendar date the backend already grouped in UTC; letting the browser reinterpret it in local time would shift the heading by a day for anyone west of UTC, so a viewer in Los Angeles would see events filed under the wrong date.

- [ ] **Step 9: Write `src/components/PersonalTopicsWidget.tsx`**

```tsx
import { Link } from "react-router-dom";
import type { PersonalDashboardResponse } from "../api/types";

export function PersonalTopicsWidget({
  data,
  isLoading,
  isError,
}: {
  data: PersonalDashboardResponse | undefined;
  isLoading: boolean;
  isError: boolean;
}) {
  return (
    <section className="rounded-lg border border-hairline bg-surface-container-lowest p-4">
      <h2 className="mb-3 text-sm font-semibold text-on-surface">Your topics</h2>

      {isLoading && <p className="text-xs text-on-surface-variant">Loading…</p>}
      {isError && (
        <p className="text-xs text-error">
          Couldn&apos;t load your topics. The rest of the dashboard is unaffected.
        </p>
      )}

      {/* Deterministic, not model-written (OQ-C-002). Rendered as plain text with no
          "AI" framing, because it is not AI -- claiming otherwise in either direction
          would misrepresent it. */}
      {data?.blurb && (
        <p className="mb-3 font-serif text-sm leading-relaxed text-on-surface">{data.blurb}</p>
      )}

      <ul className="space-y-1">
        {data?.topics.map((row) => (
          <li key={row.topic.id} className="flex items-baseline justify-between gap-2 text-xs">
            <Link
              to={`/topics/${row.topic.id}`}
              className="text-primary-container hover:underline"
            >
              {row.topic.canonical_label}
            </Link>
            <span className="text-on-surface-variant">
              {/* A quiet topic is listed with a zero count (FR-C-008), not dropped:
                  dropping it would make the widget look like the user has fewer
                  interests than they do, and "no change" is itself information. */}
              {row.event_count === 0
                ? "No change this week"
                : `${row.event_count} ${row.event_count === 1 ? "change" : "changes"}`}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 10: Write `src/pages/DashboardPage.tsx`**

```tsx
import { useActivityRanking, useChangeFeed, usePersonalDashboard } from "../api/hooks";
import { ActivityWidget } from "../components/ActivityWidget";
import { ChangeFeedWidget } from "../components/ChangeFeedWidget";
import { PersonalTopicsWidget } from "../components/PersonalTopicsWidget";
import { StalenessBanner } from "../components/StalenessBanner";
import { useIdentity } from "../identity/identity";

export function DashboardPage() {
  const { userId } = useIdentity();
  const activity = useActivityRanking();
  const changes = useChangeFeed();
  const personal = usePersonalDashboard(userId);

  return (
    <div>
      <h1 className="mb-4 text-2xl font-semibold">Dashboard</h1>

      <StalenessBanner computedAt={activity.data?.computed_at ?? null} />

      <div className="grid gap-4 lg:grid-cols-2">
        <ActivityWidget
          data={activity.data}
          isLoading={activity.isLoading}
          isError={activity.isError}
        />
        <ChangeFeedWidget
          data={changes.data}
          isLoading={changes.isLoading}
          isError={changes.isError}
        />
      </div>

      {/* Mounted only once the user has actually declared interests. Rendering an empty
          "your topics" panel for every first-time visitor would occupy the primary
          content area with a placeholder, which G-C-1 exists to prevent. */}
      {personal.data?.has_profile && (
        <div className="mt-4">
          <PersonalTopicsWidget
            data={personal.data}
            isLoading={personal.isLoading}
            isError={personal.isError}
          />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 11: Write `src/pages/DashboardPage.test.tsx`**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { IdentityProvider } from "../identity/identity";
import { server } from "../test/server";
import { DashboardPage } from "./DashboardPage";

const EMPTY_ACTIVITY = { computed_at: null, window_start: null, window_end: null, topics: [] };
const EMPTY_CHANGES = { days: [], total_events: 0 };
const NO_PROFILE = {
  has_profile: false,
  computed_at: null,
  window_start: null,
  window_end: null,
  topics: [],
  blurb: null,
};

function handlers({ activity = EMPTY_ACTIVITY, changes = EMPTY_CHANGES, personal = NO_PROFILE } = {}) {
  // MSW is configured with onUnhandledRequest: "error", so all three endpoints need a
  // handler even when a test only cares about one of them.
  server.use(
    http.get("/dashboard/activity", () => HttpResponse.json(activity)),
    http.get("/dashboard/changes", () => HttpResponse.json(changes)),
    http.get("/dashboard/personal", () => HttpResponse.json(personal)),
  );
}

function renderPage() {
  localStorage.setItem("athena_user_id", "00000000-0000-0000-0000-000000000001");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IdentityProvider>
        <MemoryRouter initialEntries={["/dashboard"]}>
          <DashboardPage />
        </MemoryRouter>
      </IdentityProvider>
    </QueryClientProvider>,
  );
}

test("cold start renders both global widgets rather than a placeholder", async () => {
  // G-C-1: a first-time visitor with no interests and no data must still get a populated
  // dashboard, not an empty-state panel occupying the primary content area.
  handlers();
  renderPage();

  await waitFor(() => expect(screen.getByText(/most active topics/i)).toBeInTheDocument());
  expect(screen.getByText(/what changed/i)).toBeInTheDocument();
});

test("a user without a profile sees no personal widget and no error", async () => {
  handlers();
  renderPage();

  await waitFor(() => expect(screen.getByText(/most active topics/i)).toBeInTheDocument());
  expect(screen.queryByText(/your topics/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/couldn't load/i)).not.toBeInTheDocument();
});

test("a user with a profile sees the personal widget and its blurb", async () => {
  handlers({
    personal: {
      ...NO_PROFILE,
      has_profile: true,
      blurb: "10 new papers and 2 consensus updates across your 3 topics this week.",
      topics: [
        {
          topic: { id: "t1", canonical_label: "Atrial fibrillation" },
          event_count: 0,
          breakdown: { new_paper: 0, consensus_updated: 0, contradiction_flagged: 0, paper_retracted: 0 },
          latest_event_at: null,
        },
      ],
    },
  });
  renderPage();

  await waitFor(() => expect(screen.getByText(/your topics/i)).toBeInTheDocument());
  expect(screen.getByText(/10 new papers and 2 consensus updates/i)).toBeInTheDocument();
  // FR-C-008: a quiet interest topic is listed with a zero count, not dropped.
  expect(screen.getByText(/no change this week/i)).toBeInTheDocument();
});

test("one failing endpoint does not blank the other widgets", async () => {
  // The load-bearing property of this page. Three independent queries feed it, and a
  // single 500 must degrade one panel rather than the whole landing surface.
  server.use(
    http.get("/dashboard/activity", () => HttpResponse.text("boom", { status: 500 })),
    http.get("/dashboard/changes", () =>
      HttpResponse.json({
        days: [
          {
            date: "2026-08-01",
            events: [
              {
                event_type: "paper_retracted",
                detected_at: "2026-08-01T06:12:44Z",
                topic: { id: "t9", canonical_label: "GLP-1 receptor agonists" },
                paper: { id: "p9", title: "Weight outcomes in a retrospective cohort" },
                evidence_tier: null,
              },
            ],
          },
        ],
        total_events: 1,
      }),
    ),
    http.get("/dashboard/personal", () => HttpResponse.json(NO_PROFILE)),
  );
  renderPage();

  await waitFor(() =>
    expect(screen.getByText(/couldn't load topic activity/i)).toBeInTheDocument(),
  );
  expect(screen.getByText(/glp-1 receptor agonists/i)).toBeInTheDocument();
});

test("a retraction is visually distinguished from ordinary activity", async () => {
  // OQ-C-005 chose no type filter for v1 on the grounds that this treatment does the
  // work a filter would. If it stops happening, that decision is silently undone.
  handlers({
    changes: {
      days: [
        {
          date: "2026-08-01",
          events: [
            {
              event_type: "paper_retracted",
              detected_at: "2026-08-01T06:12:44Z",
              topic: { id: "t9", canonical_label: "GLP-1 receptor agonists" },
              paper: { id: "p9", title: "Weight outcomes" },
              evidence_tier: null,
            },
            {
              event_type: "new_paper",
              detected_at: "2026-08-01T06:12:03Z",
              topic: { id: "t1", canonical_label: "Atrial fibrillation" },
              paper: { id: "p1", title: "Anticoagulation in adults over 85" },
              evidence_tier: "established",
            },
          ],
        },
      ],
      total_events: 2,
    },
  });
  renderPage();

  await waitFor(() => expect(screen.getByText("Retracted")).toBeInTheDocument());
  expect(screen.getByText("Retracted").className).toContain("text-error");
  expect(screen.getByText("New paper").className).not.toContain("text-error");
});

test("the staleness banner appears when the data is older than 36 hours", async () => {
  // FR-C-011. The job runs daily, so 36 hours means a run was missed; saying so is the
  // difference between a user distrusting the numbers and distrusting the app.
  const twoDaysAgo = new Date(Date.now() - 48 * 3_600_000).toISOString();
  handlers({ activity: { ...EMPTY_ACTIVITY, computed_at: twoDaysAgo } });
  renderPage();

  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/data as of/i));
});

test("no staleness banner for fresh data", async () => {
  handlers({ activity: { ...EMPTY_ACTIVITY, computed_at: new Date().toISOString() } });
  renderPage();

  await waitFor(() => expect(screen.getByText(/most active topics/i)).toBeInTheDocument());
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

const FORBIDDEN = /trending|hot|popular|breakthrough|important|momentum|real-time|\blive\b|no results|nothing found/i;

test("the assembled page never uses forbidden copy", async () => {
  // Asserted on the whole page, not per component: the copy rules bind the surface a
  // reader actually sees, and a widget could satisfy them alone while the composition
  // does not.
  handlers({
    personal: { ...NO_PROFILE, has_profile: true, blurb: "No change in your 1 topic this week." },
  });
  const { container } = renderPage();

  await waitFor(() => expect(screen.getByText(/your topics/i)).toBeInTheDocument());
  expect(container.textContent).not.toMatch(FORBIDDEN);
});
```

- [ ] **Step 12: Run the frontend suite and build**

Run: `npx vitest run && npm run build`
Expected: all pass, build clean.

- [ ] **Step 13: Commit**

```bash
git add webapp/frontend/src
git commit -m "feat: add dashboard page, widgets, types and hooks"
```

---

## Task 9: Make the Dashboard the Landing Route

**Files:**
- Modify: `webapp/frontend/src/App.tsx`, `webapp/frontend/src/components/IconSidebar.tsx`, `webapp/frontend/e2e/smoke.spec.ts`, `scripts/seed_demo_data.py`, `webapp/frontend/README.md`
- Create: `docs/dashboard-metrics.md`

**Interfaces:**
- Consumes: `<DashboardPage />` (Task 8).
- Produces: the `/dashboard` route and the redirect change.

This task is last because it changes the application's front door. Everything before it is additive and invisible; this is the commit that makes the dashboard the first thing anyone sees.

- [ ] **Step 1: Add the route**

In `src/App.tsx`, change line 21's redirect target and add the route:

```tsx
                <Route path="/" element={<Navigate to="/dashboard" replace />} />
                <Route path="/dashboard" element={<DashboardPage />} />
```

`/#/search` remains permanently valid — the redirect changes where `/` lands, not whether the search route works.

- [ ] **Step 2: Add the nav entry**

In `src/components/IconSidebar.tsx`, add Dashboard as the **first** entry:

```tsx
  { to: "/dashboard", icon: "dashboard", label: "Dashboard" },
```

- [ ] **Step 3: Fix the Playwright smoke test before it breaks**

`e2e/smoke.spec.ts` relies on the root redirect landing on Search. Change it to navigate to `/#/search` explicitly. This is a certainty, not a risk: the redirect target changed in Step 1.

- [ ] **Step 4: Run the smoke test**

Run from `webapp/frontend`: `npx playwright test`
Expected: pass. If Playwright is not installed in this environment, note it in the task report rather than skipping the edit — the edit is still required.

- [ ] **Step 5: Extend the demo seed**

In `scripts/seed_demo_data.py`, emit **9 weeks** of `ChangeEvent` history spread across the seeded topics — 8 complete baseline weeks plus the current window — so a freshly seeded database produces at least one topic with `is_newly_tracked: false` and a real `trend_score`. Without this the dashboard demos as entirely "newly tracked", which reads as broken. Add a `--run-dashboard-job` flag that calls `refresh_activity_snapshots` after seeding, so the demo needs one command rather than two.

- [ ] **Step 6: Write `docs/dashboard-metrics.md`**

Document, for an operator: what the trend score measures and explicitly what it does not; the eligibility and baseline thresholds and why they exist; the daily job, how to run it, and how to tell a failed run from a quiet week (`dashboard_job_state.status` and `last_error`); the 180-day retention and that the current generation is exempt; and the `DASHBOARD_ENABLED` flag.

- [ ] **Step 7: Update the frontend README**

Document `DASHBOARD_ENABLED` and state that the dashboard shows an empty ranking until `scripts/refresh_dashboard_activity.py` has run at least once — an operator seeing an empty widget should not have to read source to find out why.

- [ ] **Step 8: Run everything**

```bash
arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest -q
cd webapp/frontend && npx vitest run && npm run build
```

Expected: all pass, build clean.

- [ ] **Step 9: Commit**

```bash
git add webapp/frontend/src webapp/frontend/e2e webapp/frontend/README.md scripts/seed_demo_data.py docs/dashboard-metrics.md
git commit -m "feat: make the dashboard the landing route"
```

---

## Task 10: Wire DASHBOARD_ENABLED

**Added 2026-09-25 after Task 9.** The Global Constraints say "Everything is gated behind
`DASHBOARD_ENABLED`, default `false`", but no task ever allocated work to implement it:
`dashboard_enabled` exists in `evidence_engine/config.py` and is read by nothing. Task 9's
implementer found this and documented it honestly rather than quietly leaving it.

That is a defect in this plan, not in any task's execution. Without it, merging makes the
dashboard the landing route for every user immediately, and it shows an empty ranking
until the daily job has run at least once. User decision: wire it before merge.

**Files:**
- Modify: `dashboard/flags.py` (create), `webapp/api.py`, `webapp/frontend/src/api/types.ts`, `src/api/hooks.ts`, `src/App.tsx`, `src/components/IconSidebar.tsx`
- Test: `tests/dashboard/test_flags.py` (create), `tests/webapp/test_api.py`, `src/App.test.tsx`

**Interfaces:**
- Produces: `dashboard.flags.dashboard_enabled() -> bool`; `GET /features`; `useFeatures()`.

The backend half is the real gate — it protects the API regardless of what any client
does. The frontend half is presentation: it stops the app advertising a feature whose
endpoints will refuse.

- [ ] **Step 1: Write `dashboard/flags.py`**

```python
from evidence_engine.config import get_settings


def dashboard_enabled() -> bool:
    """Read at call time, not import time, so a test can monkeypatch the setting.

    Mirrors synthesis/service.py's _synthesis_enabled, which is the established pattern
    for a feature gate in this codebase.
    """
    return get_settings().dashboard_enabled
```

- [ ] **Step 2: Gate all five routes**

Each of `GET /dashboard/activity`, `/dashboard/changes`, `/dashboard/personal`,
`POST /interests` and `DELETE /interests/{topic_id}` returns **503** when the flag is off,
before any other validation:

```python
    if not dashboard_enabled():
        raise HTTPException(status_code=503, detail="Dashboard is not enabled")
```

503 rather than 404: the routes exist and will work once enabled, which is what the
synthesis endpoint already returns for the same situation.

**The check goes first.** Placing it after parameter validation would leak the routes'
input contract to a caller who cannot use them, and would make a disabled endpoint return
422 for bad input — two different answers to "is this available".

- [ ] **Step 3: Add `GET /features`**

```python
@app.get("/features")
def features_endpoint() -> dict:
    """Flags the client needs in order to decide what to render.

    Not gated: a client must be able to ask whether a feature is on. Returns only
    booleans that are already public in effect -- never secrets, and never anything
    user-specific, so it stays cacheable and needs no auth.
    """
    return {"dashboard_enabled": dashboard_enabled()}
```

- [ ] **Step 4: Frontend — the type and hook**

`FeatureFlags { dashboard_enabled: boolean }` in `types.ts`; `useFeatures()` in `hooks.ts`
following the existing `useQuery` conventions.

- [ ] **Step 5: Gate the redirect and the nav**

The root redirect must **fail closed**: while the flag is unknown, do not redirect to the
dashboard. Render nothing at `/` until it resolves, then navigate. Redirecting to
`/search` first and correcting afterwards would flash the wrong page for every enabled
user, and defaulting to the dashboard would show it to disabled ones.

`IconSidebar` omits the Dashboard entry entirely when the flag is off — a nav item leading
to a page whose data all 503s is worse than no nav item.

`/#/dashboard` itself stays routable either way. Someone with the link gets the page and
its widgets' error states, which is honest; hiding the route would make the flag look like
a bug to whoever is testing it.

- [ ] **Step 6: Tests**

Backend: each of the five routes returns 503 with the flag off and its normal status with
it on; `/features` reports both states. Monkeypatch `dashboard.flags.dashboard_enabled`,
matching how `tests/synthesis/test_service.py` patches `_synthesis_enabled`.

Frontend: with the flag off, `/` lands on search and no Dashboard nav entry renders; with
it on, `/` lands on the dashboard and the entry is first. **Assert the disabled case after
the features query resolves** — this file has produced three racing negative assertions
already, all of which passed because they checked absence before the state that would
create it had arrived.

- [ ] **Step 7: Verify and commit**

```bash
source .superpowers/sdd/c-env.sh && arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest -q
cd webapp/frontend && npx vitest run && npm run build && npx playwright test
```

---

## Task 11: Interest Management UI

**Added 2026-09-26 after the whole-branch review.** `dashboard/interests.py`, both
`/interests` endpoints and the `useAddInterest`/`useRemoveInterest` hooks are implemented
and tested, but **no component imports either hook**. There is no affordance anywhere that
lets a real user add an interest topic, and no other UI path to create an
`InterestProfile` existed before this sub-project. So `has_profile` is always false,
and `PersonalTopicsWidget`, the blurb and `personal_topic_summary`'s populated branch can
never render outside tests.

That is roughly half of C built and unreachable. The spec's component list already names
`InterestTopicPicker` (section 8), so this is a step the plan omitted rather than new
scope. User decision: build it before merge.

**Files:**
- Create: `webapp/frontend/src/components/InterestTopicPicker.tsx`, `InterestTopicPicker.test.tsx`
- Modify: `src/components/PersonalTopicsWidget.tsx`, `src/pages/DashboardPage.tsx`, `src/pages/DashboardPage.test.tsx`

**Interfaces:**
- Consumes: `useAddInterest`, `useRemoveInterest`, `useIdentity` (all existing).

- [ ] **Step 1: `InterestTopicPicker`**

A labelled text input and a submit button calling `useAddInterest`. It must handle the
four states the endpoint can return, because each means something different to the user:

- **201** — added. Clear the input.
- **200** — already an interest. Say so plainly; do not present it as an error, because
  nothing went wrong.
- **404** — unknown user. This is the identity being stale, not the input being bad.
- **429** — rate limited. Say when to try again. Never reword this as a validation
  failure; the request was fine and will work later.
- **422** — the term could not be resolved to a research topic. This is the only one that
  is about what the user typed.

Disable the control while `isPending`: each submit is an outbound PubMed call, so a
double-click costs a second one.

- [ ] **Step 2: A remove control on each `PersonalTopicsWidget` row**

Calling `useRemoveInterest`. It must carry an accessible name identifying WHICH topic it
removes — `aria-label={`Remove ${topic.canonical_label}`}` — or a screen-reader user hears
a list of identical "Remove" buttons.

- [ ] **Step 3: Mount the picker**

On `DashboardPage`, visible whether or not `has_profile` is true — it is the only way to
go from no profile to having one, so hiding it behind `has_profile` would make the
personal dashboard unreachable exactly as it is today.

- [ ] **Step 4: Tests**

Each of the five response states renders its own distinct message; the control is disabled
while pending; removal calls the hook with the right topic id; the picker is present for a
user with no profile.

**Every negative assertion must wait for the state that would make the thing appear.**
This file has produced five racing assertions across Tasks 8 and 10, each found only after
the previous fix looked complete. `expect(queryBy(...)).not.toHaveAttribute(...)` passes
vacuously when the query returns null — assert absence directly.

- [ ] **Step 5: Verify and commit**

```bash
cd webapp/frontend && npx vitest run && npm run build
source .superpowers/sdd/c-env.sh && arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest -q
```

---

## Task 12: Build the change_events index concurrently — DONE (`757b3e1`)

Whole-branch review finding, applied inline. `ix_change_events_detected_at` is on
`change_events`, an existing engine-owned table written continuously by ingestion; a plain
`CREATE INDEX` locks it for the whole build. Split into its own non-transactional
migration (`c41f8a20b7de`) using `CREATE INDEX CONCURRENTLY IF NOT EXISTS`, verified by
building a scratch database from zero — moving an index between migrations risks fresh
installs silently losing it, which applying to an already-indexed database cannot detect.

---

## Self-Review

**Spec coverage.** FR-C-001 → Tasks 4, 7. FR-C-002, FR-C-003 → Task 3, enforced in `trend.py` and asserted there. FR-C-004 → Tasks 3, 8. FR-C-005 → Tasks 5, 7. FR-C-006 → Task 5 (§14.3's exact predicate). FR-C-007 → Task 6 (§14.4's `scalar_one_or_none` rule). FR-C-008 → Task 6. FR-C-009 → Task 4. FR-C-010 → Task 4, with a test that plants an orphan generation. FR-C-011 → Tasks 4, 8 (`StalenessBanner`). FR-C-012 → Task 8. FR-C-013 → Task 6. FR-C-014 → Task 9. FR-C-015, FR-C-016 → Task 8, with a forbidden-copy regex and a tooltip test. FR-C-017 → **not** satisfied by construction; that claim was false and survived two reviews. It reads true if you grep `dashboard/` for `session.add(Topic`, and is wrong two hops down the call chain: `POST /interests` → `add_user_interest` → `digest.profiles.add_interest` → `get_or_create_topic`, which inserts into `topics` and mutates `Topic.aliases` on an existing row. Confirmed by execution (topics count 2 → 3 on a single add). The constraint has been amended above to carve this out explicitly, since the write is unavoidable. Two safety consequences were fixed rather than documented: `Topic.aliases` had no size bound and was reachable from an unauthenticated endpoint whose rate limit is keyed on a freely-mintable `user_id`, so it is now capped at `MAX_ALIASES = 50` and deduplicated case- and whitespace-insensitively (`evidence_engine/topics/registry.py`). Engine-side schema changes remain additive: two indexes, Tasks 1 and 13.

**Deliberately excluded, with reasons.** Per the decisions recorded above: no daily window toggle (OQ-C-003), no change-feed type filter (OQ-C-005), no LLM narrative (OQ-C-002 — a deterministic sentence instead). Sub-project B's synthesis engine is not called, even though it has landed. `digest/runner.py` is not modified — OQ-C-001 was resolved in `a5a4117` and the spec's §24 note about it is obsolete.

**Known gap to watch during execution.** `refresh_activity_snapshots` computes nine windows with one grouped query each, which is fine at current corpus size but is O(windows) full-range scans over `change_events`. The `ix_change_events_detected_at` index added in Task 1 is what keeps that bounded; if the job gets slow, that index is the first thing to check, not the query count.

**Placeholder scan.** No TBD/TODO markers. Every task carries complete code for every code step.

Task 8's Steps 8 and 9 originally described two widgets and a page test in prose, justified as "compositions of components fully specified earlier". Pre-flight review rejected that: the writing-plans rubric calls a step that describes what to do without showing how a plan failure, and the justification did not make it compliant — it meant an implementer opening Task 8 got materially less than Tasks 1–7 give, while being reviewed to the same bar. Expanded 2026-09-17 into Steps 8–11 with full code for `ChangeFeedWidget`, `PersonalTopicsWidget`, `DashboardPage` and `DashboardPage.test.tsx`.

**Type consistency.** `TopicCounts` and `ScoredTopic` field names match between Task 3's definition and Task 4's construction. `Window.start`/`.end` match between Tasks 2 and 4. `read_current_activity`, `read_change_feed`, `personal_topic_summary`, `render_blurb`, `add_user_interest`, `remove_user_interest` and `RateLimitExceeded` are called in Task 7 with exactly the signatures Tasks 4–6 define. The TypeScript interfaces in Task 8 mirror the JSON shapes Task 7 returns field for field, including the `blurb` key the endpoint adds to the personal summary.
