# Citation Velocity UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the citation history already being collected — a per-paper velocity figure on search results, a citation-history chart on Topic Detail, and a coverage-aware trend line on Saved Searches.

**Architecture:** Three read-only endpoints on `webapp/api.py` backed by a new `citations/read.py`, consumed by three TanStack Query hooks and two new components. Nothing writes; nothing touches the collection path. Every surface is designed so that *absence of data is the normal case* — the collection job started 2026-09-08, so most papers will show "Not enough history yet" for weeks.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, FastAPI, React 18 + TypeScript, TanStack Query, Recharts, Vitest + Testing Library + MSW.

## Prerequisite: this plan needs data before it can be *verified*

Velocity requires two observations ≥14 days apart. Collection began 2026-09-08, so:

- Before ~2026-09-22, **every** paper returns `insufficient_history`. That is correct behavior, not a bug, and the empty states are the only thing testable end-to-end.
- Percentiles additionally need a cohort of ≥10 ready papers sharing a topic and 4-year band, which realistically means ~6 weeks.

The plan is written so this does not block: all tests seed their own snapshots directly, so they pass on day zero. But **manual** verification against the dev database will show empty states until real history accrues, and the reviewer should not treat that as a defect. Check `citation_velocity_cache` for rows with `status='ready'` before doing any manual pass.

## Global Constraints

- **Read-only.** No task writes to `citation_snapshots`, `citation_velocity_cache`, or `citation_refresh_state`. The collection path (`citations/refresh.py`, `citations/velocity.py`, `citations/runner.py`) is not modified — only imported from.
- **Velocity is supplementary.** A failed velocity request MUST collapse its region silently and leave the surrounding card fully functional (spec §13). It must never surface an error banner or block content.
- **No layout shift.** `CitationVelocityBadge` returns an element in every state, never `null`, so its height is reserved from first paint (spec §13).
- **Loading shows a fixed-height empty region, not a shimmer.** Most papers legitimately have no data, and a shimmer implies pending data that will never arrive (spec §8).
- **Exact user-facing copy** (spec §8). Use: "Not enough history yet", "Tracking since {date}", "Citations in the last 30 days", "Top N% for its age in this topic", "Citations after retraction", "Citation trend unavailable". Never use: "Impact", "Influence", "Importance", "Momentum", "Buzz", "Trending", "No citations", "0 citations", "Highly cited", "Since publication".
- **Never imply quality.** Velocity measures growth as reported by one provider. A paper can accumulate citations rapidly because it is being refuted.
- **Accessibility:** sparklines are decorative and carry `aria-hidden="true"`; the accessible content is the figure and percentile as text, with full units in a visually-hidden span; direction is never conveyed by color or arrow alone; percentile tooltips are keyboard-reachable; the cold-start notice uses `role="status"`, not `role="alert"`. Every `material-symbols-outlined` span carries `aria-hidden="true"` — enforced in sub-project A's review.
- **Staleness:** `computed_at` 3–21 days old renders the figure with "as of N days ago"; over 21 days renders "Citation trend unavailable" (spec §8).
- The `StaticFiles` mount must remain the **last** statement in `webapp/api.py`; every new route goes above it.
- Backend tests: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest` from the repo root (the venv's `pydantic_core` is x86_64-only; Postgres runs in docker container `evidence-engine-postgres-1`). Frontend: `npx vitest run` and `npm run build` from `webapp/frontend/`.

---

## Task 1: Velocity & History Read Service

**Files:**
- Create: `citations/read.py`
- Test: `tests/citations/test_read.py`

**Interfaces:**
- Consumes: `citations.models.CitationSnapshot`, `CitationVelocityCache` (read-only); `evidence_engine.db.models.Paper`.
- Produces: `get_paper_velocities(session, paper_ids: list[UUID]) -> dict[UUID, dict]` returning one block per requested id — including ids with no cache row, as `insufficient_history` — and `get_citation_history(session, paper_id: UUID, days: int) -> dict`. Task 3's endpoints call both.

- [ ] **Step 1: Write the failing test**

Create `tests/citations/test_read.py`:

```python
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from citations.models import CitationSnapshot, CitationVelocityCache
from citations.read import get_citation_history, get_paper_velocities
from evidence_engine.db.models import Paper


def _paper(db_session, title="Read paper", retracted=False):
    paper = Paper(title=title, is_retracted=retracted)
    db_session.add(paper)
    db_session.flush()
    return paper


def _snap(db_session, paper_id, day_offset, count, anomalous=False):
    moment = datetime(2026, 6, 1) + timedelta(days=day_offset)
    db_session.add(
        CitationSnapshot(
            paper_id=paper_id,
            observed_at=moment,
            observed_on=moment.date(),
            citation_count=count,
            is_anomalous=anomalous,
        )
    )
    db_session.flush()


def test_returns_a_ready_block_from_the_cache(db_session):
    paper = _paper(db_session)
    db_session.add(
        CitationVelocityCache(
            paper_id=paper.id,
            status="ready",
            velocity_per_30d=Decimal("24.00"),
            observation_count=6,
            percentile=88,
            cohort_size=34,
            computed_at=datetime(2026, 8, 2, 5, 0),
        )
    )
    db_session.flush()

    result = get_paper_velocities(db_session, [paper.id])

    block = result[paper.id]
    assert block["status"] == "ready"
    assert block["velocity_per_30d"] == 24.0
    assert block["percentile"] == 88
    assert block["cohort_size"] == 34
    assert block["is_retracted"] is False


def test_velocity_is_a_float_not_a_decimal(db_session):
    # The endpoint serializes to JSON; a Decimal would raise or stringify.
    paper = _paper(db_session, "Float paper")
    db_session.add(
        CitationVelocityCache(paper_id=paper.id, status="ready", velocity_per_30d=Decimal("3.50"))
    )
    db_session.flush()

    block = get_paper_velocities(db_session, [paper.id])[paper.id]

    assert isinstance(block["velocity_per_30d"], float)


def test_paper_with_no_cache_row_reads_as_insufficient_history(db_session):
    paper = _paper(db_session, "Untracked paper")

    block = get_paper_velocities(db_session, [paper.id])[paper.id]

    assert block["status"] == "insufficient_history"
    assert block["velocity_per_30d"] is None
    assert block["observation_count"] == 0
    assert block["first_observed_at"] is None


def test_unknown_paper_id_is_still_present_in_the_map(db_session):
    # The frontend keys off the requested ids; a missing key would look like a bug.
    missing = uuid.uuid4()

    result = get_paper_velocities(db_session, [missing])

    assert result[missing]["status"] == "insufficient_history"


def test_retraction_is_reported_from_the_paper_not_the_cache(db_session):
    paper = _paper(db_session, "Retracted paper", retracted=True)
    db_session.add(CitationVelocityCache(paper_id=paper.id, status="ready", velocity_per_30d=Decimal("5.00")))
    db_session.flush()

    assert get_paper_velocities(db_session, [paper.id])[paper.id]["is_retracted"] is True


def test_history_returns_observations_ascending(db_session):
    paper = _paper(db_session, "History paper")
    for offset, count in ((14, 112), (0, 104), (7, 109)):
        _snap(db_session, paper.id, offset, count)

    result = get_citation_history(db_session, paper.id, days=365)

    assert [o["citation_count"] for o in result["observations"]] == [104, 109, 112]
    assert result["observations"][0]["observed_on"] == date(2026, 6, 1).isoformat()
    assert result["first_observed_at"] is not None
    assert result["source"] == "semantic_scholar"


def test_history_respects_the_days_window(db_session):
    paper = _paper(db_session, "Windowed paper")
    _snap(db_session, paper.id, 0, 100)
    _snap(db_session, paper.id, 400, 200)

    # Anchor the window on the newest observation so the test is not time-dependent.
    result = get_citation_history(db_session, paper.id, days=30)

    assert [o["citation_count"] for o in result["observations"]] == [200]


def test_history_exposes_anomalous_flags(db_session):
    paper = _paper(db_session, "Anomalous history")
    _snap(db_session, paper.id, 0, 240)
    _snap(db_session, paper.id, 20, 190, anomalous=True)

    result = get_citation_history(db_session, paper.id, days=365)

    assert [o["is_anomalous"] for o in result["observations"]] == [False, True]


def test_history_for_a_paper_with_no_snapshots_is_empty_not_an_error(db_session):
    paper = _paper(db_session, "No history")

    result = get_citation_history(db_session, paper.id, days=365)

    assert result["observations"] == []
    assert result["first_observed_at"] is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/citations/test_read.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'citations.read'`.

- [ ] **Step 3: Write `citations/read.py`**

```python
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from citations.models import CitationSnapshot, CitationVelocityCache
from evidence_engine.db.models import Paper


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _empty_block(is_retracted: bool) -> dict:
    # A paper the collection job has never reached is indistinguishable, from the
    # reader's point of view, from one with a single observation: neither can
    # produce a velocity. Both read as insufficient_history rather than as an error.
    return {
        "status": "insufficient_history",
        "velocity_per_30d": None,
        "window_start_observed_at": None,
        "window_end_observed_at": None,
        "observation_count": 0,
        "first_observed_at": None,
        "percentile": None,
        "cohort_size": 0,
        "is_retracted": is_retracted,
        "computed_at": None,
    }


def get_paper_velocities(session: Session, paper_ids: list[uuid.UUID]) -> dict:
    """One block per requested id. Ids with no cache row are included, not omitted --
    the caller keys off what it asked for, and a missing key reads as a bug."""
    if not paper_ids:
        return {}

    retracted = {
        row.id: bool(row.is_retracted)
        for row in session.execute(select(Paper).where(Paper.id.in_(paper_ids))).scalars().all()
    }
    caches = {
        row.paper_id: row
        for row in session.execute(
            select(CitationVelocityCache).where(CitationVelocityCache.paper_id.in_(paper_ids))
        )
        .scalars()
        .all()
    }

    out: dict = {}
    for paper_id in paper_ids:
        is_retracted = retracted.get(paper_id, False)
        cache = caches.get(paper_id)
        if cache is None:
            out[paper_id] = _empty_block(is_retracted)
            continue
        out[paper_id] = {
            "status": cache.status,
            # float(), not Decimal: this is serialized straight to JSON.
            "velocity_per_30d": float(cache.velocity_per_30d)
            if cache.velocity_per_30d is not None
            else None,
            "window_start_observed_at": _iso(cache.window_start_observed_at),
            "window_end_observed_at": _iso(cache.window_end_observed_at),
            "observation_count": cache.observation_count,
            "first_observed_at": _iso(cache.first_observed_at),
            "percentile": cache.percentile,
            "cohort_size": cache.cohort_size,
            "is_retracted": is_retracted,
            "computed_at": _iso(cache.computed_at),
        }
    return out


def get_citation_history(session: Session, paper_id: uuid.UUID, days: int) -> dict:
    """Observations ascending by date, which is what a chart consumes directly."""
    snapshots = (
        session.execute(
            select(CitationSnapshot)
            .where(CitationSnapshot.paper_id == paper_id)
            .order_by(CitationSnapshot.observed_at)
        )
        .scalars()
        .all()
    )

    windowed = snapshots
    if snapshots:
        # Anchor on the newest observation rather than on wall-clock now, so a paper
        # whose tracking stopped still renders the history it has instead of an
        # empty chart.
        cutoff = snapshots[-1].observed_at - timedelta(days=days)
        windowed = [s for s in snapshots if s.observed_at >= cutoff]

    return {
        "paper_id": str(paper_id),
        "observations": [
            {
                "observed_on": s.observed_on.isoformat(),
                "citation_count": s.citation_count,
                "is_anomalous": s.is_anomalous,
            }
            for s in windowed
        ],
        "first_observed_at": _iso(snapshots[0].observed_at) if snapshots else None,
        "source": snapshots[0].source if snapshots else "semantic_scholar",
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/citations/test_read.py -v`
Expected: 9 passed.

- [ ] **Step 5: Run the full suite**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest -q`
Expected: all pass. This task adds only a new module.

- [ ] **Step 6: Commit**

```bash
git add citations/read.py tests/citations/test_read.py
git commit -m "feat: add citation velocity and history read service"
```

---

## Task 2: Saved-Search Velocity Aggregate

**Files:**
- Create: `citations/aggregate.py`
- Test: `tests/citations/test_aggregate.py`

**Interfaces:**
- Consumes: `citations.models.CitationVelocityCache`; `webapp.search.search_papers` and `SearchFilters` (existing, read-only); `webapp.models.SavedSearch`.
- Produces: `MAX_AGGREGATE_PAPERS: int` (200), `MIN_COVERAGE_RATIO: float` (0.25), and `saved_search_velocity(session, saved_search, weeks: int) -> dict`. Task 3's endpoint calls it.

Median, not mean: citation velocities are heavily right-skewed, and one landmark paper would otherwise dominate the line (spec §14.4).

- [ ] **Step 1: Write the failing test**

Create `tests/citations/test_aggregate.py`:

```python
from datetime import datetime, timedelta
from decimal import Decimal

from citations.aggregate import MIN_COVERAGE_RATIO, median, saved_search_velocity
from citations.models import CitationVelocityCache
from digest.profiles import create_user
from evidence_engine.db.models import EvidenceTier, Paper, PaperTopic, Score, StudyType, Topic
from webapp.models import SavedSearch
from webapp.search_index import sync_search_index


def test_median_of_odd_and_even_counts():
    assert median([3.0, 1.0, 2.0]) == 2.0
    assert median([1.0, 2.0, 3.0, 4.0]) == 2.5


def test_median_of_empty_is_none():
    assert median([]) is None


def _topic_with_papers(db_session, label, count, velocity, weeks_ago=1):
    topic = Topic(canonical_label=label, mesh_id=f"D_AGG_{label[:6]}")
    db_session.add(topic)
    db_session.flush()
    window_end = datetime(2026, 8, 1) - timedelta(weeks=weeks_ago)
    for i in range(count):
        paper = Paper(title=f"{label} paper {i}", abstract="Aggregate fixture.")
        db_session.add(paper)
        db_session.flush()
        db_session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
        db_session.add(
            Score(
                paper_id=paper.id,
                evidence_tier=EvidenceTier.ESTABLISHED,
                study_type=StudyType.RCT,
                final_score=70.0,
                model_version="v1",
            )
        )
        db_session.add(
            CitationVelocityCache(
                paper_id=paper.id,
                status="ready",
                velocity_per_30d=Decimal(str(velocity)),
                window_end_observed_at=window_end,
            )
        )
    db_session.flush()
    sync_search_index(db_session)
    return topic


def _saved_search(db_session, topic):
    user = create_user(db_session, f"agg-{topic.mesh_id}@example.com")
    saved = SavedSearch(
        user_id=user.id, name="Aggregate search", query_params={"topic_id": str(topic.id)}
    )
    db_session.add(saved)
    db_session.flush()
    return saved


def test_ready_when_coverage_is_sufficient(db_session):
    topic = _topic_with_papers(db_session, "Covered topic", count=12, velocity=4.0)
    saved = _saved_search(db_session, topic)

    result = saved_search_velocity(db_session, saved, weeks=12)

    assert result["status"] == "ready"
    assert result["papers_total"] == 12
    assert result["papers_with_history"] == 12
    assert result["series"], "expected at least one weekly point"
    assert all(p["median_velocity_per_30d"] == 4.0 for p in result["series"])


def test_insufficient_coverage_returns_no_series(db_session):
    # 1 of 12 papers has history: below the MIN_COVERAGE_RATIO floor, so a median
    # would describe one paper while appearing to describe the whole search.
    topic = Topic(canonical_label="Sparse topic", mesh_id="D_AGG_SPARSE")
    db_session.add(topic)
    db_session.flush()
    for i in range(12):
        paper = Paper(title=f"Sparse paper {i}")
        db_session.add(paper)
        db_session.flush()
        db_session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
        db_session.add(
            Score(
                paper_id=paper.id,
                evidence_tier=EvidenceTier.ESTABLISHED,
                study_type=StudyType.RCT,
                final_score=70.0,
                model_version="v1",
            )
        )
        if i == 0:
            db_session.add(
                CitationVelocityCache(
                    paper_id=paper.id,
                    status="ready",
                    velocity_per_30d=Decimal("9.00"),
                    window_end_observed_at=datetime(2026, 7, 25),
                )
            )
    db_session.flush()
    sync_search_index(db_session)
    saved = _saved_search(db_session, topic)

    result = saved_search_velocity(db_session, saved, weeks=12)

    assert result["status"] == "insufficient_coverage"
    assert result["series"] == []
    assert result["papers_total"] == 12
    assert result["papers_with_history"] == 1


def test_uses_median_not_mean(db_session):
    # One landmark paper must not drag the line.
    topic = Topic(canonical_label="Skewed topic", mesh_id="D_AGG_SKEW")
    db_session.add(topic)
    db_session.flush()
    velocities = [1.0] * 10 + [1000.0]
    for i, v in enumerate(velocities):
        paper = Paper(title=f"Skewed paper {i}")
        db_session.add(paper)
        db_session.flush()
        db_session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
        db_session.add(
            Score(
                paper_id=paper.id,
                evidence_tier=EvidenceTier.ESTABLISHED,
                study_type=StudyType.RCT,
                final_score=70.0,
                model_version="v1",
            )
        )
        db_session.add(
            CitationVelocityCache(
                paper_id=paper.id,
                status="ready",
                velocity_per_30d=Decimal(str(v)),
                window_end_observed_at=datetime(2026, 7, 25),
            )
        )
    db_session.flush()
    sync_search_index(db_session)
    saved = _saved_search(db_session, topic)

    result = saved_search_velocity(db_session, saved, weeks=12)

    # Mean would be ~91.8; median is 1.0.
    assert all(p["median_velocity_per_30d"] == 1.0 for p in result["series"])


def test_does_not_update_last_run_at(db_session):
    topic = _topic_with_papers(db_session, "Untouched topic", count=12, velocity=2.0)
    saved = _saved_search(db_session, topic)
    assert saved.last_run_at is None

    saved_search_velocity(db_session, saved, weeks=12)

    # This is a pure read; the saved search's own run history must be unaffected.
    assert saved.last_run_at is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/citations/test_aggregate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'citations.aggregate'`.

- [ ] **Step 3: Write `citations/aggregate.py`**

```python
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from citations.models import CitationVelocityCache
from webapp.search import SearchFilters, search_papers

MAX_AGGREGATE_PAPERS = 200
# Below this share of papers having history, a median describes a handful of papers
# while appearing to describe the whole saved search. Report coverage instead.
MIN_COVERAGE_RATIO = 0.25


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _week_starts(now: datetime, weeks: int) -> list[datetime]:
    # Monday-anchored week boundaries, oldest first.
    this_week = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return [this_week - timedelta(weeks=offset) for offset in range(weeks - 1, -1, -1)]


def saved_search_velocity(
    session: Session, saved_search, weeks: int, now: datetime | None = None
) -> dict:
    """Median velocity across a saved search's papers, per trailing week boundary.

    Median rather than mean: citation velocities are heavily right-skewed, and one
    landmark paper would otherwise dominate the line. Pure read -- it deliberately
    does NOT update the saved search's last_run_at.
    """
    now = now or datetime.utcnow()
    params = saved_search.query_params or {}
    filters = SearchFilters(
        topic_id=params.get("topic_id"),
        tier=params.get("tier"),
        study_type=params.get("study_type"),
        date_from=params.get("date_from"),
        date_to=params.get("date_to"),
    )
    page = search_papers(
        session, query=params.get("q"), filters=filters, page=1, page_size=MAX_AGGREGATE_PAPERS
    )
    paper_ids = [row.paper.id for row in page.rows]
    papers_total = len(paper_ids)

    caches = []
    if paper_ids:
        caches = (
            session.execute(
                select(CitationVelocityCache).where(
                    CitationVelocityCache.paper_id.in_(paper_ids),
                    CitationVelocityCache.status == "ready",
                )
            )
            .scalars()
            .all()
        )
    papers_with_history = len(caches)

    computed_at = now.isoformat()
    if papers_total == 0 or papers_with_history / papers_total < MIN_COVERAGE_RATIO:
        return {
            "status": "insufficient_coverage",
            "papers_total": papers_total,
            "papers_with_history": papers_with_history,
            "series": [],
            "computed_at": computed_at,
        }

    series = []
    for boundary in _week_starts(now, weeks):
        values = [
            float(c.velocity_per_30d)
            for c in caches
            if c.velocity_per_30d is not None
            and c.window_end_observed_at is not None
            and c.window_end_observed_at <= boundary
        ]
        point = median(values)
        if point is not None:
            series.append(
                {"week_start": boundary.date().isoformat(), "median_velocity_per_30d": point}
            )

    return {
        "status": "ready",
        "papers_total": papers_total,
        "papers_with_history": papers_with_history,
        "series": series,
        "computed_at": computed_at,
    }
```

- [ ] **Step 4: Run the tests**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/citations/test_aggregate.py -v`
Expected: 6 passed.

**Type coercion is required, not optional.** `SearchFilters` declares `topic_id: uuid.UUID | None` and `date_from` / `date_to` as `date | None` (`webapp/search.py:14-20`), but a saved search stores its `query_params` as free-form JSONB, so all three arrive as **strings**. Passing them through raw will compare a `str` against a UUID/date column and either raise or silently match nothing.

Coerce each one, treating a malformed stored value as *no filter* rather than an error — `query_params` is unvalidated and may predate any given filter shape:

```python
def _as_uuid(value):
    try:
        return uuid.UUID(value) if value else None
    except (ValueError, AttributeError, TypeError):
        return None


def _as_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except (ValueError, AttributeError, TypeError):
        return None
```

Add a test asserting a saved search whose `query_params` carries string dates still returns `status="ready"` rather than raising — the silent-no-match variant of this bug would otherwise look like "no coverage" forever.

- [ ] **Step 5: Commit**

```bash
git add citations/aggregate.py tests/citations/test_aggregate.py
git commit -m "feat: add saved-search median velocity aggregate with coverage floor"
```

---

## Task 3: HTTP Endpoints

**Files:**
- Modify: `webapp/api.py` (three routes, all above the `StaticFiles` mount)
- Test: `tests/webapp/test_api.py`

**Interfaces:**
- Consumes: `citations.read.get_paper_velocities`, `get_citation_history` (Task 1); `citations.aggregate.saved_search_velocity` (Task 2).
- Produces: `GET /papers/velocity?paper_ids=...`, `GET /papers/{paper_id}/citation-history?days=`, `GET /saved-searches/{saved_search_id}/velocity?user_id=&weeks=`. Task 4's hooks call all three.

- [ ] **Step 1: Write the failing tests**

Append to `tests/webapp/test_api.py`:

```python
def test_paper_velocity_endpoint_returns_a_block_per_requested_id(db_session):
    from decimal import Decimal

    from citations.models import CitationVelocityCache

    paper = Paper(title="Velocity endpoint paper")
    db_session.add(paper)
    db_session.flush()
    db_session.add(
        CitationVelocityCache(
            paper_id=paper.id, status="ready", velocity_per_30d=Decimal("14.00"), percentile=88
        )
    )
    db_session.flush()
    missing = uuid.uuid4()

    client = _client(db_session)
    response = client.get("/papers/velocity", params={"paper_ids": [str(paper.id), str(missing)]})

    assert response.status_code == 200
    velocities = response.json()["velocities"]
    assert velocities[str(paper.id)]["velocity_per_30d"] == 14.0
    assert velocities[str(paper.id)]["percentile"] == 88
    # Every requested id appears, even one that resolves to nothing.
    assert velocities[str(missing)]["status"] == "insufficient_history"


def test_paper_velocity_endpoint_rejects_empty_and_oversized_requests(db_session):
    client = _client(db_session)

    assert client.get("/papers/velocity", params={"paper_ids": []}).status_code == 422
    too_many = {"paper_ids": [str(uuid.uuid4()) for _ in range(101)]}
    assert client.get("/papers/velocity", params=too_many).status_code == 422


def test_citation_history_endpoint_returns_observations(db_session):
    from datetime import date as _date

    from citations.models import CitationSnapshot

    paper = Paper(title="History endpoint paper")
    db_session.add(paper)
    db_session.flush()
    db_session.add(
        CitationSnapshot(
            paper_id=paper.id,
            observed_at=datetime(2026, 7, 1, 4, 0),
            observed_on=_date(2026, 7, 1),
            citation_count=104,
        )
    )
    db_session.flush()

    client = _client(db_session)
    response = client.get(f"/papers/{paper.id}/citation-history")

    assert response.status_code == 200
    body = response.json()
    assert body["observations"][0]["citation_count"] == 104
    assert body["source"] == "semantic_scholar"


def test_citation_history_endpoint_404s_for_unknown_paper(db_session):
    client = _client(db_session)

    response = client.get(f"/papers/{uuid.uuid4()}/citation-history")

    assert response.status_code == 404


def test_citation_history_endpoint_rejects_out_of_range_days(db_session):
    paper = Paper(title="Range paper")
    db_session.add(paper)
    db_session.flush()
    client = _client(db_session)

    assert client.get(f"/papers/{paper.id}/citation-history", params={"days": 5}).status_code == 422
    assert (
        client.get(f"/papers/{paper.id}/citation-history", params={"days": 5000}).status_code == 422
    )


def test_saved_search_velocity_endpoint_404s_for_unknown_saved_search(db_session):
    user = create_user(db_session, "ssvel@example.com")
    client = _client(db_session)

    response = client.get(
        f"/saved-searches/{uuid.uuid4()}/velocity", params={"user_id": str(user.id)}
    )

    assert response.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/webapp/test_api.py -v -k "velocity or citation_history"`
Expected: FAIL with 404s — the routes do not exist.

- [ ] **Step 3: Add the routes to `webapp/api.py`**

Add imports beside the other package imports:

```python
from citations.aggregate import saved_search_velocity
from citations.read import get_citation_history, get_paper_velocities
```

Add the routes **above** the `StaticFiles` mount:

```python
MAX_VELOCITY_IDS = 100


@app.get("/papers/velocity")
def paper_velocity_endpoint(
    paper_ids: list[uuid.UUID] = Query(default_factory=list), db: Session = Depends(get_db)
) -> dict:
    if not paper_ids or len(paper_ids) > MAX_VELOCITY_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"paper_ids must contain between 1 and {MAX_VELOCITY_IDS} identifiers",
        )
    velocities = get_paper_velocities(db, paper_ids)
    return {"velocities": {str(pid): block for pid, block in velocities.items()}}


@app.get("/papers/{paper_id}/citation-history")
def citation_history_endpoint(
    paper_id: uuid.UUID, days: int = Query(default=365, ge=30, le=1095), db: Session = Depends(get_db)
) -> dict:
    if db.get(Paper, paper_id) is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
    return get_citation_history(db, paper_id, days=days)


@app.get("/saved-searches/{saved_search_id}/velocity")
def saved_search_velocity_endpoint(
    saved_search_id: uuid.UUID,
    user_id: uuid.UUID,
    weeks: int = Query(default=12, ge=4, le=52),
    db: Session = Depends(get_db),
) -> dict:
    user = _require_user(db, user_id)
    saved = _get_owned_saved_search(db, user, saved_search_id)
    return saved_search_velocity(db, saved, weeks=weeks)
```

`Paper` must be imported from `evidence_engine.db.models` — check whether the existing import line already includes it and add it if not.

`_get_owned_saved_search` is the existing ownership helper in `webapp/saved_searches.py` used by the delete and run routes; import it the same way those routes do, and let its `ValueError` map to a 404 exactly as they do. If those routes call it inside a `try/except ValueError`, mirror that shape rather than inventing a new one.

- [ ] **Step 4: Run the tests**

Run: `arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest tests/webapp/ -v`
Expected: all pass, including the pre-existing endpoint tests.

- [ ] **Step 5: Run the full suite and commit**

```bash
arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest -q
git add webapp/api.py tests/webapp/test_api.py
git commit -m "feat: add citation velocity, history, and saved-search trend endpoints"
```

---

## Task 4: Frontend Types & Hooks

**Files:**
- Modify: `webapp/frontend/src/api/types.ts`, `src/api/hooks.ts`
- Test: `webapp/frontend/src/api/velocityHooks.test.tsx`

**Interfaces:**
- Consumes: the endpoints from Task 3; the existing `apiGet` helper.
- Produces: types `VelocityStatus`, `PaperVelocity`, `VelocityResponse`, `CitationObservation`, `CitationHistoryResponse`, `SavedSearchVelocityResponse`; hooks `usePaperVelocities(paperIds)`, `useCitationHistory(paperId, days?)`, `useSavedSearchVelocity(savedSearchId, userId, weeks?)`. Tasks 5–7 consume these.

Note: `CitationObservation` is also the name of a Python dataclass in `citations/provider.py`. They are unrelated and live in different languages; no conflict.

- [ ] **Step 1: Add the types**

In `src/api/types.ts`:

```ts
export type VelocityStatus = "ready" | "insufficient_history" | "unrefreshable";

export interface PaperVelocity {
  status: VelocityStatus;
  velocity_per_30d: number | null;
  window_start_observed_at: string | null;
  window_end_observed_at: string | null;
  observation_count: number;
  first_observed_at: string | null;
  percentile: number | null;
  cohort_size: number;
  is_retracted: boolean;
  computed_at: string | null;
}

export interface VelocityResponse {
  velocities: Record<string, PaperVelocity>;
}

export interface CitationObservation {
  observed_on: string;
  citation_count: number;
  is_anomalous: boolean;
}

export interface CitationHistoryResponse {
  paper_id: string;
  observations: CitationObservation[];
  first_observed_at: string | null;
  source: string;
}

export interface SavedSearchVelocityPoint {
  week_start: string;
  median_velocity_per_30d: number;
}

export interface SavedSearchVelocityResponse {
  status: "ready" | "insufficient_coverage";
  papers_total: number;
  papers_with_history: number;
  series: SavedSearchVelocityPoint[];
  computed_at: string;
}
```

- [ ] **Step 2: Add the hooks**

In `src/api/hooks.ts`, importing the new types:

```ts
// Velocity changes at most once a day, so refetching on every mount is wasted work.
const VELOCITY_STALE_MS = 1_800_000;

export function usePaperVelocities(paperIds: string[]) {
  const sorted = [...paperIds].sort();
  return useQuery({
    queryKey: ["paper-velocities", sorted],
    queryFn: () => apiGet<VelocityResponse>("/papers/velocity", { paper_ids: sorted }),
    enabled: sorted.length > 0,
    staleTime: VELOCITY_STALE_MS,
  });
}

export function useCitationHistory(paperId: string | null, days = 365) {
  return useQuery({
    queryKey: ["citation-history", paperId, days],
    queryFn: () =>
      apiGet<CitationHistoryResponse>(`/papers/${paperId}/citation-history`, { days }),
    enabled: paperId !== null,
    staleTime: VELOCITY_STALE_MS,
  });
}

export function useSavedSearchVelocity(
  savedSearchId: string | null,
  userId: string | null,
  weeks = 12,
) {
  return useQuery({
    queryKey: ["saved-search-velocity", savedSearchId, weeks],
    queryFn: () =>
      apiGet<SavedSearchVelocityResponse>(`/saved-searches/${savedSearchId}/velocity`, {
        user_id: userId,
        weeks,
      }),
    enabled: savedSearchId !== null && userId !== null,
    staleTime: VELOCITY_STALE_MS,
  });
}
```

- [ ] **Step 3: Write the failing test**

Create `src/api/velocityHooks.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { server } from "../test/server";
import { useCitationHistory, usePaperVelocities, useSavedSearchVelocity } from "./hooks";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

test("usePaperVelocities sorts ids so key order cannot split the cache", async () => {
  let requested: string[] = [];
  server.use(
    http.get("/papers/velocity", ({ request }) => {
      requested = new URL(request.url).searchParams.getAll("paper_ids");
      return HttpResponse.json({ velocities: {} });
    }),
  );

  const { result } = renderHook(() => usePaperVelocities(["b", "a"]), { wrapper });

  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(requested).toEqual(["a", "b"]);
});

test("usePaperVelocities does not fire for an empty list", () => {
  // No handler registered; onUnhandledRequest is "error", so a request would fail.
  const { result } = renderHook(() => usePaperVelocities([]), { wrapper });

  expect(result.current.fetchStatus).toBe("idle");
});

test("useCitationHistory fetches observations", async () => {
  server.use(
    http.get("/papers/p1/citation-history", () =>
      HttpResponse.json({
        paper_id: "p1",
        observations: [{ observed_on: "2026-07-01", citation_count: 104, is_anomalous: false }],
        first_observed_at: "2026-07-01T04:00:00Z",
        source: "semantic_scholar",
      }),
    ),
  );

  const { result } = renderHook(() => useCitationHistory("p1"), { wrapper });

  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(result.current.data?.observations[0].citation_count).toBe(104);
});

test("useSavedSearchVelocity stays idle without a user", () => {
  const { result } = renderHook(() => useSavedSearchVelocity("s1", null), { wrapper });

  expect(result.current.fetchStatus).toBe("idle");
});
```

- [ ] **Step 4: Run tests and build**

Run from `webapp/frontend`: `npx vitest run && npm run build`
Expected: all pass, build clean.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/api
git commit -m "feat: add citation velocity types and query hooks"
```

---

## Task 5: `VelocitySparkline` and `CitationVelocityBadge`

**Files:**
- Create: `webapp/frontend/src/components/VelocitySparkline.tsx`, `src/components/CitationVelocityBadge.tsx`
- Test: `webapp/frontend/src/components/CitationVelocityBadge.test.tsx`

**Interfaces:**
- Consumes: `PaperVelocity` (Task 4); Recharts (already a dependency).
- Produces: `VelocitySparkline({ points: number[] })` returning `null` below 3 points; `CitationVelocityBadge({ velocity, isRetracted })` returning an element in **every** state. Tasks 6–7 render the badge.

The badge is the whole state matrix in one component. Every row of spec §8's table needs a branch and a test.

- [ ] **Step 1: Write the failing test**

Create `src/components/CitationVelocityBadge.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import type { PaperVelocity } from "../api/types";
import { CitationVelocityBadge } from "./CitationVelocityBadge";

function velocity(overrides: Partial<PaperVelocity> = {}): PaperVelocity {
  return {
    status: "ready",
    velocity_per_30d: 14,
    window_start_observed_at: "2026-07-03T04:20:11Z",
    window_end_observed_at: "2026-08-02T04:18:52Z",
    observation_count: 6,
    first_observed_at: "2026-06-28T04:15:02Z",
    percentile: 88,
    cohort_size: 34,
    is_retracted: false,
    computed_at: new Date().toISOString(),
    ...overrides,
  };
}

test("renders the figure with an explicit unit in text", () => {
  render(<CitationVelocityBadge velocity={velocity()} isRetracted={false} />);

  expect(screen.getByText(/14/)).toBeInTheDocument();
  // Units are spelled out for screen readers, not implied by a compact glyph.
  expect(screen.getByText(/citations in the last 30 days/i)).toBeInTheDocument();
});

test("shows the percentile with age-and-topic scoping", () => {
  render(<CitationVelocityBadge velocity={velocity()} isRetracted={false} />);

  expect(screen.getByText(/top 12% for its age in this topic/i)).toBeInTheDocument();
});

test("omits the percentile when the cohort is too small", () => {
  render(
    <CitationVelocityBadge
      velocity={velocity({ percentile: null, cohort_size: 4 })}
      isRetracted={false}
    />,
  );

  expect(screen.queryByText(/for its age in this topic/i)).not.toBeInTheDocument();
  expect(screen.getByText(/citations in the last 30 days/i)).toBeInTheDocument();
});

test("insufficient history shows the tracking-since date and no number", () => {
  render(
    <CitationVelocityBadge
      velocity={velocity({
        status: "insufficient_history",
        velocity_per_30d: null,
        observation_count: 1,
        percentile: null,
      })}
      isRetracted={false}
    />,
  );

  expect(screen.getByText(/not enough history yet/i)).toBeInTheDocument();
  expect(screen.getByText(/tracking since/i)).toBeInTheDocument();
  expect(screen.queryByText(/citations in the last 30 days/i)).not.toBeInTheDocument();
});

test("undefined velocity renders an element rather than collapsing", () => {
  // The region's height is reserved from first paint; returning null would shift layout.
  const { container } = render(
    <CitationVelocityBadge velocity={undefined} isRetracted={false} />,
  );

  expect(container.firstChild).not.toBeNull();
});

test("an aging computation is labelled with its age", () => {
  const tenDaysAgo = new Date(Date.now() - 10 * 86400000).toISOString();

  render(
    <CitationVelocityBadge velocity={velocity({ computed_at: tenDaysAgo })} isRetracted={false} />,
  );

  expect(screen.getByText(/as of 10 days ago/i)).toBeInTheDocument();
});

test("a computation over 21 days old is suppressed entirely", () => {
  const longAgo = new Date(Date.now() - 30 * 86400000).toISOString();

  render(<CitationVelocityBadge velocity={velocity({ computed_at: longAgo })} isRetracted={false} />);

  expect(screen.getByText(/citation trend unavailable/i)).toBeInTheDocument();
  expect(screen.queryByText(/citations in the last 30 days/i)).not.toBeInTheDocument();
});

test("a retracted paper qualifies the figure", () => {
  render(<CitationVelocityBadge velocity={velocity()} isRetracted={true} />);

  expect(screen.getByText(/citations after retraction/i)).toBeInTheDocument();
});

test("never uses quality language", () => {
  const { container } = render(
    <CitationVelocityBadge velocity={velocity()} isRetracted={false} />,
  );

  expect(container.textContent).not.toMatch(/impact|influence|importance|momentum|trending/i);
});
```

- [ ] **Step 2: Run to verify it fails**

Run from `webapp/frontend`: `npx vitest run src/components/CitationVelocityBadge.test.tsx`
Expected: FAIL — cannot resolve `./CitationVelocityBadge`.

- [ ] **Step 3: Write `src/components/VelocitySparkline.tsx`**

```tsx
import { Line, LineChart, ResponsiveContainer } from "recharts";

const TEAL = "#006a61";

export function VelocitySparkline({ points }: { points: number[] }) {
  // Below three points a "line" is a single straight segment, which implies a trend
  // from one interval. Better to draw nothing than to imply a shape that isn't there.
  if (points.length < 3) return null;

  const data = points.map((value, index) => ({ index, value }));
  return (
    <span aria-hidden="true" className="inline-block h-5 w-20 align-middle">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <Line type="monotone" dataKey="value" stroke={TEAL} strokeWidth={1.5} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </span>
  );
}
```

- [ ] **Step 4: Write `src/components/CitationVelocityBadge.tsx`**

```tsx
import type { PaperVelocity } from "../api/types";

const AGING_DAYS = 3;
const SUPPRESS_DAYS = 21;

function daysSince(iso: string | null): number | null {
  if (!iso) return null;
  const ms = Date.now() - new Date(iso).getTime();
  return Math.floor(ms / 86400000);
}

function formatDate(iso: string | null): string {
  if (!iso) return "recently";
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

// A fixed-height wrapper in every branch: the region is reserved from first paint,
// so a velocity arriving (or never arriving) cannot shift the card around it.
function Region({ children }: { children: React.ReactNode }) {
  return <div className="min-h-5 text-xs text-on-surface-variant">{children}</div>;
}

export function CitationVelocityBadge({
  velocity,
  isRetracted,
}: {
  velocity: PaperVelocity | undefined;
  isRetracted: boolean;
}) {
  // Loading or errored: an empty reserved region, deliberately not a shimmer --
  // most papers legitimately have no history, and a shimmer would promise data
  // that is never going to arrive.
  if (!velocity) return <Region>{null}</Region>;

  const age = daysSince(velocity.computed_at);

  if (age !== null && age > SUPPRESS_DAYS) {
    return <Region>Citation trend unavailable</Region>;
  }

  if (velocity.status !== "ready" || velocity.velocity_per_30d === null) {
    return (
      <Region>
        Not enough history yet
        {velocity.first_observed_at && ` · tracking since ${formatDate(velocity.first_observed_at)}`}
      </Region>
    );
  }

  const figure = Math.round(velocity.velocity_per_30d);
  const label = isRetracted ? "citations after retraction" : "citations in the last 30 days";

  return (
    <Region>
      <span className={isRetracted ? "font-semibold text-error" : "font-semibold text-secondary"}>
        {figure}
      </span>{" "}
      <span>{label}</span>
      {velocity.percentile !== null && (
        <>
          {" · "}
          <span
            tabIndex={0}
            title={`Compared with ${velocity.cohort_size} papers of similar age in this topic`}
          >
            top {100 - velocity.percentile}% for its age in this topic
          </span>
        </>
      )}
      {age !== null && age >= AGING_DAYS && <span> · as of {age} days ago</span>}
    </Region>
  );
}
```

Note the percentile display: an 88th-percentile paper is described as "top 12%". Keep that inversion — the test asserts it.

- [ ] **Step 5: Run tests and build**

Run from `webapp/frontend`: `npx vitest run && npm run build`
Expected: all pass, clean build.

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend/src/components
git commit -m "feat: add citation velocity badge and sparkline components"
```

---

## Task 6: Search Page Integration & Cold-Start Notice

**Files:**
- Modify: `webapp/frontend/src/components/ResearchCard.tsx`, `src/components/TierSection.tsx`, `src/pages/SearchPage.tsx`
- Test: `webapp/frontend/src/pages/SearchPageVelocity.test.tsx`

**Interfaces:**
- Consumes: `usePaperVelocities` (Task 4), `CitationVelocityBadge` (Task 5).
- Produces: `ResearchCard` gains an optional `velocity?: PaperVelocity` prop; `TierSection` gains `velocities?: Record<string, PaperVelocity>` and passes each row its own block. Both props are optional so existing call sites and tests keep working unchanged.

The Search page owns one batched query for all rows on screen — never one request per card.

- [ ] **Step 1: Write the failing test**

Create `src/pages/SearchPageVelocity.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { IdentityProvider } from "../identity/identity";
import { server } from "../test/server";
import { SearchPage } from "./SearchPage";

function row(id: string, title: string) {
  return {
    paper: { id, title, abstract: null, pub_date: "2026-01-01" },
    score: { evidence_tier: "established", study_type: "rct", final_score: 70 },
    topics: [],
  };
}

function renderPage() {
  localStorage.setItem("athena_user_id", "00000000-0000-0000-0000-000000000001");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IdentityProvider>
        <MemoryRouter initialEntries={["/search"]}>
          <SearchPage />
        </MemoryRouter>
      </IdentityProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  server.use(
    http.get("/topics", () => HttpResponse.json([])),
    http.get("/search", () =>
      HttpResponse.json({
        rows: [row("p1", "Fast paper"), row("p2", "Quiet paper")],
        total: 2,
        page: 1,
        page_size: 50,
      }),
    ),
  );
});

test("renders a velocity figure on a card that has history", async () => {
  server.use(
    http.get("/papers/velocity", () =>
      HttpResponse.json({
        velocities: {
          p1: {
            status: "ready",
            velocity_per_30d: 14,
            window_start_observed_at: null,
            window_end_observed_at: null,
            observation_count: 6,
            first_observed_at: "2026-06-28T04:00:00Z",
            percentile: 88,
            cohort_size: 34,
            is_retracted: false,
            computed_at: new Date().toISOString(),
          },
          p2: {
            status: "insufficient_history",
            velocity_per_30d: null,
            window_start_observed_at: null,
            window_end_observed_at: null,
            observation_count: 1,
            first_observed_at: "2026-08-30T04:00:00Z",
            percentile: null,
            cohort_size: 0,
            is_retracted: false,
            computed_at: new Date().toISOString(),
          },
        },
      }),
    ),
  );
  renderPage();

  await waitFor(() => expect(screen.getByText(/citations in the last 30 days/i)).toBeInTheDocument());
  expect(screen.getByText(/not enough history yet/i)).toBeInTheDocument();
});

test("a failed velocity request leaves the results fully usable", async () => {
  server.use(http.get("/papers/velocity", () => HttpResponse.text("boom", { status: 500 })));
  renderPage();

  // The cards still render; velocity is supplementary and must fail silently.
  await waitFor(() => expect(screen.getByText("Fast paper")).toBeInTheDocument());
  expect(screen.getByText("Quiet paper")).toBeInTheDocument();
  expect(screen.queryByText(/citation.*unavailable|error/i)).not.toBeInTheDocument();
});

test("shows one page-level notice when every row lacks history", async () => {
  const none = (id: string) => ({
    status: "insufficient_history",
    velocity_per_30d: null,
    window_start_observed_at: null,
    window_end_observed_at: null,
    observation_count: 0,
    first_observed_at: null,
    percentile: null,
    cohort_size: 0,
    is_retracted: false,
    computed_at: new Date().toISOString(),
  });
  server.use(
    http.get("/papers/velocity", () =>
      HttpResponse.json({ velocities: { p1: none("p1"), p2: none("p2") } }),
    ),
  );
  renderPage();

  await waitFor(() => {
    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent(/citation tracking is still building history/i);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run from `webapp/frontend`: `npx vitest run src/pages/SearchPageVelocity.test.tsx`
Expected: FAIL — no velocity request is made and no badge renders.

- [ ] **Step 3: Thread the prop through `ResearchCard`**

In `src/components/ResearchCard.tsx`, add the optional prop and render the badge under the existing metadata row. Do not change any existing content:

```tsx
import { CitationVelocityBadge } from "./CitationVelocityBadge";
import type { PaperRow, PaperVelocity } from "../api/types";

export function ResearchCard({
  row,
  checked,
  onToggleSelect,
  velocity,
}: {
  row: PaperRow;
  checked: boolean;
  onToggleSelect: (paperId: string) => void;
  velocity?: PaperVelocity;
}) {
```

and, immediately after the existing metadata `<div>`:

```tsx
        <CitationVelocityBadge velocity={velocity} isRetracted={velocity?.is_retracted ?? false} />
```

- [ ] **Step 4: Thread it through `TierSection`**

In `src/components/TierSection.tsx`, accept `velocities?: Record<string, PaperVelocity>` and pass `velocities?.[row.paper.id]` to each `ResearchCard`. Keep it optional so existing tests that omit it still pass.

- [ ] **Step 5: Wire the Search page**

In `src/pages/SearchPage.tsx`:

```tsx
  const paperIds = useMemo(() => (data?.rows ?? []).map((r) => r.paper.id), [data]);
  const velocities = usePaperVelocities(paperIds);
  const velocityMap = velocities.data?.velocities;

  // One notice for the whole page rather than identical text on every card. During
  // the collection warm-up this is the expected state, not an error -- role="status".
  const allEmpty =
    velocityMap !== undefined &&
    paperIds.length > 0 &&
    paperIds.every((id) => velocityMap[id]?.status !== "ready");
```

Render the notice above the tier sections:

```tsx
        {allEmpty && (
          <p role="status" className="mb-4 rounded border border-hairline bg-surface-container-low p-2 text-xs text-on-surface-variant">
            Citation tracking is still building history for these papers. Velocity
            appears once a paper has been observed twice, at least 14 days apart.
          </p>
        )}
```

and pass `velocities={velocityMap}` to each of the four `TierSection`s.

- [ ] **Step 5b: Add a default `/papers/velocity` handler to the shared MSW server**

**This step is required and was missing from the plan's first draft.** `src/test/setup.ts:30` starts MSW with `onUnhandledRequest: "error"`, and the pre-existing `src/pages/SearchPage.test.tsx` registers handlers only for `/search` and `/topics`. The moment `SearchPage` mounts `usePaperVelocities`, every one of those pre-existing tests fires an unhandled `/papers/velocity` request and fails — a break caused by this task, in tests it never touches.

Fix it in the shared server rather than per-file, because the same trap waits for every future page that mounts velocity. In `src/test/server.ts`, register a default handler returning an empty map:

```ts
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

// Velocity is supplementary: its absence must never break a page, in production or
// in tests. A default empty map means any page that mounts usePaperVelocities gets
// a benign response without every test file having to know about it. Tests that
// assert velocity behavior override this with server.use().
export const server = setupServer(
  http.get("/papers/velocity", () => HttpResponse.json({ velocities: {} })),
);
```

Confirm afterwards that `src/pages/SearchPage.test.tsx` still passes **unmodified** — if it needed editing, the default handler is not doing its job. Note in your report whether the pre-existing tests passed untouched.

- [ ] **Step 6: Run all tests and build**

Run from `webapp/frontend`: `npx vitest run && npm run build`
Expected: all pass — including the pre-existing `SearchPage.test.tsx`, which omits velocity entirely and must be unaffected.

- [ ] **Step 7: Commit**

```bash
git add webapp/frontend/src
git commit -m "feat: show citation velocity on search results with a cold-start notice"
```

---

## Task 7: Topic Detail History Chart & Saved-Search Trend

**Files:**
- Create: `webapp/frontend/src/components/CitationHistoryChart.tsx`, `src/components/SavedSearchVelocityTrend.tsx`
- Modify: `webapp/frontend/src/pages/TopicDetailPage.tsx`, `src/pages/SavedSearchesPage.tsx`
- Test: `webapp/frontend/src/components/CitationHistoryChart.test.tsx`, `src/components/SavedSearchVelocityTrend.test.tsx`

**Interfaces:**
- Consumes: `useCitationHistory`, `useSavedSearchVelocity` (Task 4).
- Produces: `CitationHistoryChart({ paperId })` and `SavedSearchVelocityTrend({ savedSearchId, userId })`.

The Saved Searches page must request at most 10 rows' worth at a time (spec §12) — the endpoint re-executes a search and is the most expensive read here.

- [ ] **Step 1: Write the failing tests**

Create `src/components/CitationHistoryChart.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { server } from "../test/server";
import { CitationHistoryChart } from "./CitationHistoryChart";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

test("renders the section heading once history exists", async () => {
  server.use(
    http.get("/papers/p1/citation-history", () =>
      HttpResponse.json({
        paper_id: "p1",
        observations: [
          { observed_on: "2026-07-01", citation_count: 100, is_anomalous: false },
          { observed_on: "2026-07-08", citation_count: 108, is_anomalous: false },
          { observed_on: "2026-07-15", citation_count: 115, is_anomalous: false },
        ],
        first_observed_at: "2026-07-01T04:00:00Z",
        source: "semantic_scholar",
      }),
    ),
  );

  render(<CitationHistoryChart paperId="p1" />, { wrapper });

  await waitFor(() => expect(screen.getByText(/citation history/i)).toBeInTheDocument());
});

test("shows the empty message when there are no observations", async () => {
  server.use(
    http.get("/papers/p2/citation-history", () =>
      HttpResponse.json({
        paper_id: "p2",
        observations: [],
        first_observed_at: null,
        source: "semantic_scholar",
      }),
    ),
  );

  render(<CitationHistoryChart paperId="p2" />, { wrapper });

  await waitFor(() => expect(screen.getByText(/not enough history yet/i)).toBeInTheDocument());
});

test("collapses silently on error", async () => {
  server.use(
    http.get("/papers/p3/citation-history", () => HttpResponse.text("boom", { status: 500 })),
  );

  const { container } = render(<CitationHistoryChart paperId="p3" />, { wrapper });

  await waitFor(() => expect(container.textContent).not.toMatch(/error|failed/i));
});
```

Create `src/components/SavedSearchVelocityTrend.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { server } from "../test/server";
import { SavedSearchVelocityTrend } from "./SavedSearchVelocityTrend";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

test("states coverage rather than drawing a misleading line", async () => {
  server.use(
    http.get("/saved-searches/s1/velocity", () =>
      HttpResponse.json({
        status: "insufficient_coverage",
        papers_total: 40,
        papers_with_history: 3,
        series: [],
        computed_at: new Date().toISOString(),
      }),
    ),
  );

  render(<SavedSearchVelocityTrend savedSearchId="s1" userId="u1" />, { wrapper });

  await waitFor(() => expect(screen.getByText(/3 of 40/i)).toBeInTheDocument());
});

test("renders the trend when coverage is sufficient", async () => {
  server.use(
    http.get("/saved-searches/s2/velocity", () =>
      HttpResponse.json({
        status: "ready",
        papers_total: 40,
        papers_with_history: 28,
        series: [
          { week_start: "2026-05-11", median_velocity_per_30d: 3.5 },
          { week_start: "2026-05-18", median_velocity_per_30d: 4.0 },
          { week_start: "2026-05-25", median_velocity_per_30d: 4.5 },
        ],
        computed_at: new Date().toISOString(),
      }),
    ),
  );

  render(<SavedSearchVelocityTrend savedSearchId="s2" userId="u1" />, { wrapper });

  await waitFor(() => expect(screen.getByText(/median/i)).toBeInTheDocument());
});
```

- [ ] **Step 2: Run to verify they fail**

Run from `webapp/frontend`: `npx vitest run src/components/CitationHistoryChart.test.tsx src/components/SavedSearchVelocityTrend.test.tsx`
Expected: FAIL — modules do not resolve.

- [ ] **Step 3: Write `src/components/CitationHistoryChart.tsx`**

```tsx
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useCitationHistory } from "../api/hooks";

const TEAL = "#006a61";

export function CitationHistoryChart({ paperId }: { paperId: string }) {
  const { data, isError } = useCitationHistory(paperId);

  // Supplementary: on failure the section disappears rather than shouting.
  if (isError) return null;
  if (!data) return <div className="min-h-[220px]" />;

  if (data.observations.length === 0) {
    return (
      <div className="rounded-lg border border-hairline bg-surface-container-lowest p-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
          Citation history
        </p>
        <p className="font-serif text-sm text-on-surface-variant">Not enough history yet</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-hairline bg-surface-container-lowest p-4">
      <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
        Citation history
      </p>
      <div style={{ height: 220 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data.observations}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="observed_on" tick={{ fontSize: 11 }} />
            <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
            <Tooltip />
            <Line type="monotone" dataKey="citation_count" stroke={TEAL} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2 text-xs text-on-surface-variant">
        Counts as reported by {data.source.replace(/_/g, " ")}. A dip usually reflects a
        provider record merge rather than lost citations.
      </p>
    </div>
  );
}
```

- [ ] **Step 4: Write `src/components/SavedSearchVelocityTrend.tsx`**

```tsx
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useSavedSearchVelocity } from "../api/hooks";

const TEAL = "#006a61";

export function SavedSearchVelocityTrend({
  savedSearchId,
  userId,
}: {
  savedSearchId: string;
  userId: string | null;
}) {
  const { data, isError } = useSavedSearchVelocity(savedSearchId, userId);

  if (isError || !data) return null;

  if (data.status === "insufficient_coverage") {
    // Say what is missing rather than drawing a line from a handful of papers and
    // letting it read as the whole search.
    return (
      <p className="mt-2 text-xs text-on-surface-variant">
        Citation trend needs more history — {data.papers_with_history} of{" "}
        {data.papers_total} papers tracked so far.
      </p>
    );
  }

  return (
    <div className="mt-2">
      <p className="mb-1 text-xs text-on-surface-variant">
        Median citations per 30 days across {data.papers_with_history} of {data.papers_total} papers
      </p>
      <div style={{ height: 80 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data.series}>
            <XAxis dataKey="week_start" hide />
            <YAxis hide />
            <Tooltip />
            <Line
              type="monotone"
              dataKey="median_velocity_per_30d"
              stroke={TEAL}
              strokeWidth={1.5}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Mount both**

**Decided 2026-09-10: mount the history chart on the Compare page's paper cards.** `TopicDetailPage` renders a flat table with no single-paper focus, and the spec's assumed expandable row does not exist; adding row expansion would be real scope for a secondary surface. Comparison is also where a citation trajectory is most decision-relevant — it is the screen where a user is actively weighing papers against each other.

So: in `src/pages/ComparePage.tsx`, render `<CitationHistoryChart paperId={row.paper.id} />` inside each paper card in paper mode, below the existing abstract. Do **not** modify `TopicDetailPage.tsx`, and do not add a new route.

Note the load implication: Compare holds up to 10 papers, so this mounts up to 10 independent `useCitationHistory` queries. That is acceptable — each is a single indexed read bounded by the `days` window, and unlike the saved-search endpoint it does not re-execute a search. Do not batch it; a per-card query keeps each card's loading and error states independent, which is what the silent-collapse requirement needs.

In `src/pages/SavedSearchesPage.tsx`, render `<SavedSearchVelocityTrend savedSearchId={saved.id} userId={userId} />` inside each row, but only for the **first 10 rows** — the endpoint re-executes a search per call. Slice explicitly:

```tsx
{(data ?? []).map((saved, index) => (
  ...
  {index < 10 && <SavedSearchVelocityTrend savedSearchId={saved.id} userId={userId} />}
  ...
))}
```

- [ ] **Step 6: Run everything**

```bash
cd webapp/frontend && npx vitest run && npm run build
cd ../.. && arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/pytest -q
```
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add webapp/frontend/src
git commit -m "feat: add citation history chart and saved-search velocity trend"
```

---

## Self-Review

**Spec coverage.** Tasks map to the UI half of the D spec: §12's three endpoints (Tasks 1–3), §13's three hooks and two components (Tasks 4–5), §8's state matrix and cold-start notice (Tasks 5–6), §14.4's median aggregate with its coverage floor (Task 2), and §8's accessibility and terminology rules (Global Constraints, enforced by tests in Task 5).

**Deliberately excluded, with reasons.** The per-`user_id` rate limit on the saved-search endpoint (spec §12) is **not** implemented here. `enterprise_api/rate_limit.py` is per-organization and table-backed, and generalizing it needs its own design — the roadmap already identifies a shared limiter as cross-cutting work. Task 7 instead caps the client at 10 rows, which bounds the load from Athena's own UI but not from a direct API caller.

**Decided 2026-09-09: the user chose to skip the rate limit for now.** Reviewers should not raise its absence as a finding. The residual exposure is that a direct caller can drive repeated search re-execution through `GET /saved-searches/{id}/velocity`; this is acceptable while Athena has no individual-user authentication and no public deployment, and it should be revisited alongside the shared limiter. The 10-row client cap in Task 7 stays, and is now the only thing bounding this endpoint — do not remove it. The topic-detail sparkline column and mobile column-shedding (spec §8) are also omitted; they depend on the table redesign the spec assumes and are not worth blocking the primary surfaces.

**Placeholder scan.** No TBD/TODO markers; every code step carries complete code; every test asserts specific values.

**Type consistency.** `PaperVelocity` fields match between Task 4's TypeScript and Task 1's Python serialization field-for-field, including `computed_at` being nullable (Task 1 emits `None` for a paper with no cache row — Task 4's type says `string | null`, and Task 5's `daysSince` handles null). `VelocitySparkline`'s `points: number[]` matches its only caller. `saved_search_velocity(session, saved_search, weeks)` is called in Task 3 with exactly that signature.

**Resolved 2026-09-10.** Task 7's mount point was genuinely ambiguous — the current Topic Detail page renders a flat papers table with no single-paper focus, while the spec assumes an expandable row. Settled with the user: the history chart mounts on the **Compare page's paper cards**, and `TopicDetailPage` is not modified. Task 7 Step 5 now carries that as a definite instruction rather than a branch, so no implementer has to guess.
