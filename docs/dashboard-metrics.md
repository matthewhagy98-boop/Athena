# Dashboard metrics: an operator's guide

This document explains what the Trending Dashboard's numbers mean, what keeps them from
being computed for a given topic, how the daily job that produces them works, and how to
tell a broken job from a quiet week. It is written for whoever is running the backend, not
for the code — see `dashboard/trend.py`, `dashboard/activity.py`, and `dashboard/windows.py`
for the implementation these sections describe.

## What the trend score measures

The trend score ranks topics by **the volume of newly indexed and changed evidence for
that topic relative to that topic's own recent history**. Concretely, for a topic with
enough baseline history (see below):

```
activity_ratio = (current_week_events + 1) / (baseline_mean + 1)
volume_weight  = log10(current_week_events + 1)
trend_score    = round(activity_ratio * volume_weight, 3)
```

The `+ 1` on both sides of the ratio is Laplace smoothing: it avoids a division by zero
for a topic whose baseline weeks were silent, which is the common case in a young corpus,
and it keeps a topic that goes from 0 events/week to 1 event/week from producing an
infinite or undefined ratio.

### What it explicitly does not measure

The trend score is **not** a measure of importance, quality, novelty, or clinical
relevance. A topic can rank at the top of "Most active topics" because:

- an upstream adapter backfilled a batch of older papers that happened to land this week,
- one consensus regeneration fired for the topic,
- a cluster of retractions was detected,

— none of which is a scientific development. The frontend's `ActivityWidget` carries this
caveat directly in its "What does this mean?" tooltip (FR-C-016) precisely so the ranking
is never read as an editorial judgement about which topics matter. If you are building any
downstream consumer of `GET /dashboard/activity` (an alert, a digest, a report), carry the
same caveat — the number answers "how much changed," not "how much it matters."

The raw `event_count` is always returned alongside `trend_score` for the same reason a
derived score alone would be unauditable: a reader cannot tell 24 events from 5 just by
looking at a score.

## Eligibility and baseline thresholds

Two thresholds gate whether a topic appears in the ranking at all, and whether it gets a
real `trend_score`:

- **`MIN_EVENTS = 5`** (`dashboard/trend.py`). A topic with fewer than 5 events in the
  current 7-day window is not eligible for the ranking at all — it does not appear, not
  even as a zero. This exists so the ranking is a list of topics with genuine activity
  rather than every topic that ever existed, most of which see no changes in any given
  week.

- **`BASELINE_WINDOWS = 8`** (`dashboard/windows.py`). A topic needs 8 complete prior
  7-day windows of tracked history before it gets a `baseline_mean` and a `trend_score`.
  "Complete" means the topic's first-ever change event predates the start of that
  baseline window — a window during which the topic simply wasn't being tracked yet is
  absence of *tracking*, not absence of *activity*, and averaging it in as a zero would
  understate the baseline and inflate the ratio against it.

  A topic short of 8 complete baseline weeks is marked **`is_newly_tracked: true`**,
  ranked by raw event count instead (see `dashboard/trend.py::rank_topics` for how a
  newly-tracked topic is placed on the same scale as a scored one), and both
  `baseline_mean` and `trend_score` are `null` in the API response and blank in the UI.
  This is expected, not an error — every topic starts here and ages out of it after 8
  weeks. The label reads "Newly tracked," never "new topic": the topic itself may be
  decades old, only our tracking of it is recent.

## The daily job

`dashboard/activity.py::refresh_activity_snapshots` computes one **generation** of
rankings — the current window plus all eligible topics' scores — and publishes it
atomically: rows are written under a fresh `generation_id`, and only once every row is
written does `dashboard_job_state.current_generation_id` advance to point at it. A run
that dies mid-write leaves the previous generation serving; its orphaned rows are pruned
by a later successful run, never read.

### Running it

```bash
arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/python -m scripts.refresh_dashboard_activity
```

Run this daily, sequenced after `run_daily_cycle.py` (the job that ingests new evidence
in the first place — there is nothing for the dashboard job to summarize until that has
run). For local development, `scripts/seed_demo_data.py --run-dashboard-job` seeds demo
data and runs this job in one command; see `webapp/frontend/README.md`.

### Telling a failed run from a quiet week

Both look similar from the outside — an unchanged or empty "Most active topics" widget —
so the job records enough state to tell them apart. Check
`dashboard_job_state` (single row per job, `job_name = 'activity_snapshot'`):

| `status`    | Meaning                                                                 |
|-------------|--------------------------------------------------------------------------|
| `idle`      | The last run finished successfully. Normal resting state.               |
| `running`   | A run is in progress. If this persists across multiple expected runs, the process likely died without reaching the failure handler — check for a crashed process rather than trusting this to self-clear. |
| `failed`    | The last run raised an exception. `last_error` holds the exception text (truncated to 2000 characters). |

A **quiet week** — genuinely nothing crossed `MIN_EVENTS` for any topic — is a
`status = 'idle'` run with `topics_processed = 0` and an empty `topics` array from
`GET /dashboard/activity`, but a fresh `computed_at`. `StalenessBanner` in the frontend
stays silent in this case, because the job did run; the ranking is just empty, which the
`ActivityWidget` reflects with "No topic reached the activity threshold this week."

A **failed run** is `status = 'failed'` with `last_error` populated, and — critically —
`current_generation_id` still points at the *last successful* generation, so the
dashboard keeps serving stale-but-real data rather than going blank. The frontend surfaces
this through `StalenessBanner`: once the most recent successful generation's `computed_at`
is more than 36 hours old, it shows "Data as of \<timestamp\> — the daily refresh has not
run since." 36 hours rather than 24 gives one missed run some slack before alarming the
user, while still catching a genuinely stuck job (the job runs daily, so 36 hours means at
least one run was skipped).

If you see `status = 'failed'`, read `last_error`, fix the underlying cause, and re-run
the job manually — there is no separate retry mechanism.

## Rebuilding the search index

The search index is event-sourced: `sync_search_index` reindexes a paper only when a
`NEW_PAPER` or `PAPER_RETRACTED` change event names it, inside the window after
`search_index_sync_state.last_synced_at`. That makes the scheduled sync cheap, and it
means the sync **cannot repair the index**. If index rows are lost, no future event names
those papers again, so they stay unsearchable — and because the watermark keeps advancing,
the sync walks an empty event set and reports success over the hole.

`rebuild_search_index` is the way back. It reads `papers` directly, so a paper is indexed
because it exists rather than because something happened to it:

```bash
arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/python -m scripts.sync_search_index --rebuild
```

Reach for it when papers are missing from search results but present in `papers`, after
restoring a backup, or after any migration that touched `paper_search_index`. It is
O(corpus) and therefore opt-in: the scheduled job must keep running without `--rebuild`.

Two behaviours worth knowing. It leaves the watermark at the time the scan **started**,
not finished, so a paper created mid-rebuild is still picked up by the next incremental
sync rather than being stranded behind the watermark. And unlike the incremental sync —
which skips a failed paper on purpose, since a later event will retry it — a rebuild
raises if any paper fails and leaves the watermark alone, because a rebuild has no later
event to fall back on and a partial index reported as success is the exact failure it
exists to undo.

## Retention

`refresh_activity_snapshots` prunes old generations after every successful run:
`TopicActivitySnapshot` rows older than **180 days** (`RETENTION_DAYS` in
`dashboard/activity.py`) are deleted, keyed on `computed_at`.

**The current generation is exempt from this regardless of its age.** If the daily job
stops running entirely — the scheduler is down, the process is broken — the dashboard
keeps serving its last successful generation indefinitely rather than the retention sweep
eventually deleting it out from under a still-live query. Retention only ever removes
*superseded* generations; it never empties the dashboard by itself. (`StalenessBanner`, not
retention, is what tells the user the data has gone stale.)

## The `DASHBOARD_ENABLED` flag

`Settings.dashboard_enabled` (`evidence_engine/config.py`, env var `DASHBOARD_ENABLED`,
default `false`) was introduced by this sub-project's design as a kill switch: the
intent was that setting it to `false` would make the four dashboard endpoints return 404,
hide the dashboard's sidebar entry, and revert `/` to redirecting to `/#/search` — all
without a redeploy, in case the dashboard needed to be pulled back after launch.

**The flag is wired.** Setting `DASHBOARD_ENABLED=false` (the default) has these effects:

| Surface | With the flag off |
|---|---|
| `GET /dashboard/activity`, `/dashboard/changes`, `/dashboard/personal` | `404 Not Found` |
| `POST /interests`, `DELETE /interests/{topic_id}` | `404 Not Found` |
| `GET /features` | `200 {"dashboard_enabled": false}` — never gated, because the client has to be able to ask |
| `/` (root redirect) | continues to `/#/search` |
| Sidebar | no Dashboard entry |
| `/#/dashboard` typed directly | still renders; its widgets show their error states |

404 rather than 503, per spec section 20: a disabled dashboard should be
indistinguishable from a deployment where it was never added. (The synthesis endpoint
returns 503 for its own flag, which is different — that route is permanently present and
merely declines to generate.)

The gate is a route-level FastAPI dependency, so it runs before each route's parameter
validation. That matters: an earlier in-body version let four of the five routes answer
`422` with the parameter names, locations and types for a caller who could not use them,
and it opened a database session before refusing.

**Flipping the flag takes effect on an API restart, with no frontend rebuild.** The client
reads `/features` at runtime, so the redirect and the nav entry follow the backend.

`/#/dashboard` stays routable on purpose. Whoever is verifying the rollout can reach the
page and see its widgets fail honestly, rather than meeting a 404 that looks like a broken
deploy.

One thing the flag does NOT stop: `scripts/refresh_dashboard_activity.py` keeps computing
and writing snapshots while the dashboard is switched off. That is deliberate — the data
is ready the instant the flag flips — but it means the job's cost and its
`dashboard_job_state` rows exist before anyone can see a dashboard.
