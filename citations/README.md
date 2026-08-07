# Citation tracking

Collects dated citation snapshots so citation velocity can be computed. This package
owns `citation_snapshots`, `citation_velocity_cache`, and `citation_refresh_state`,
and is read-only against evidence-engine tables.

## Running

    CITATION_TRACKING_ENABLED=true python -m scripts.refresh_citations

Run it as a module from the repo root, as above. Invoking the file by path
(`python scripts/refresh_citations.py`) fails to import the packages, because the
repo root is not on `sys.path` that way — the same is true of every other script in
`scripts/`.

Schedule once daily. Running more than once a day is harmless: snapshots are unique
per `(paper, day, source)`, so repeat runs skip papers already observed today.

With the flag unset or false the job exits immediately, without contacting the
provider, and prints `Citation tracking disabled; nothing to do.`

## The warm-up period

Citation history cannot be backfilled. Semantic Scholar reports current counts, not
dated series, so the first run establishes a baseline and nothing more.

A paper needs **two observations at least 14 days apart** before any velocity is
produced. Until then its status is `insufficient_history` and its velocity is `NULL` —
never `0`. Percentiles additionally need a cohort of at least 10 ready papers sharing
a topic and a 4-year publication band.

Roughly what to expect:

| Elapsed | State |
|---|---|
| Day 0 | Baseline only. No velocity anywhere. |
| Day 14 | The first papers cross the minimum span and turn `ready`. |
| Week 6 | Most papers with stable provider ids have a velocity; cohorts start filling. |

This is why collection ships ahead of the UI. Starting the job early is what makes
the feature possible later.

## Statuses

`citation_velocity_cache.status`

- `ready` — velocity available
- `insufficient_history` — fewer than 2 observations, or none ≥ 14 days apart, or all
  snapshots have since been removed
- `unrefreshable` — reserved; no code writes it today

`citation_velocity_cache.refresh_status`

- `active` — the provider returned this paper on the last run
- `no_provider_id` — the paper has no `semantic_scholar_id` and can never be tracked;
  it is never sent to the provider
- `gone` — requested but not returned; the provider no longer knows this id

## Velocity

Citations per 30 days, over the widest qualifying observation pair: most recent end
first, then the earliest start within a 90-day lookback, requiring at least a 14-day
span. Gaps are not interpolated — a wider interval is simply a wider interval, and the
delta genuinely accrued across it.

Percentiles are field-normalized: the cohort is papers sharing a topic and a fixed
4-year publication band. A paper linked to more than one topic is placed in exactly
one cohort, keyed on its lowest `topic_id` — a deliberate simplification of spec
§14.2's "shares at least one topic" definition, chosen so a paper's cohort (and thus
its percentile) is deterministic and stable across recomputes rather than depending
on unordered multi-topic membership. Bands are anchored on years divisible by 4 rather than
sliding ±2 years, so membership is symmetric — a sliding window would put A in B's
cohort without necessarily putting B in A's. Percentiles are clamped to 1–99, because
a cohort this size cannot support a claim of 0th or 100th.

**What this metric is not.** It measures how fast a paper's count grew, as reported by
one provider. It is affected by field size, publication age, and provider indexing lag.
It is not a measure of quality, correctness, or importance — a paper can accumulate
citations quickly because it is being refuted.

## Anomalies

Counts are stored exactly as reported and never clamped. When a count decreases —
usually a provider record merge — the snapshot is flagged `is_anomalous`, and velocity
pair selection refuses to span that transition, falling back to a window entirely
before or entirely after the merge. Clamping would destroy the evidence that the merge
happened.

## Rollback

`alembic downgrade` on this migration is **destructive and irreversible**: snapshots
cannot be re-derived from any source. To disable the feature operationally, set
`CITATION_TRACKING_ENABLED=false` instead.
