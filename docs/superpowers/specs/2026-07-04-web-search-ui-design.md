# Web App / Search UI — Design Spec

Status: Approved (pending user sign-off on this document)
Date: 2026-07-04
Scope: Third sub-project of the research intelligence platform. Covers the search/filter/comparison/saved-search/visualization query layer that reads from the evidence engine's store, exposed as an HTTP API. Does not cover a rendered frontend, authentication, or the enterprise API, which are separate future sub-projects.

## 1. Purpose

Let a user (via a future frontend, or directly against the API) search and filter the evidence engine's papers and topics, compare papers or topics side by side, save and re-run searches, and pull chart-ready visualization data — all grounded in the evidence engine's scoring and consensus output.

This sub-project answers:
- Given free text and filters (topic, evidence tier, study type, date range), what papers match, ranked by relevance?
- How do several papers, or several topics' current consensus, compare side by side?
- What has a user searched before, and can they re-run it against current data?
- What does the evidence-tier breakdown or the change history for a topic look like, in a form a chart can consume directly?

It is a backend query API, not a logged-in experience with rendered pages. A rendered frontend is explicitly deferred (see Non-Goals).

## 2. Scope Decisions

- **UI scope:** Backend-only for v1 — a query/search HTTP API and service layer. No rendered frontend is built in this sub-project; a future sub-project (or a v2 of this one) adds the actual clickable web app.
- **Relationship to the evidence engine:** Reads the engine's `Topic`, `Paper`, `Score`, `PaperTopic`, `ConsensusSnapshot`, and `ChangeEvent` tables and never writes to them, consistent with the engine spec's downstream-consumer model and digest's precedent.
- **Search architecture:** Postgres full-text search (`tsvector`/GIN), not vector/semantic search. No new infrastructure or embedding-model dependency; semantic search can be added later as a v2 if keyword search proves insufficient.
- **Search index ownership:** This sub-project owns a new `PaperSearchIndex` table in its own migration rather than adding a `tsvector` column to the engine's `Paper` table, so the engine's schema is never modified. The index is kept current by an incremental sync job driven off `ChangeEvent`, not a live daemon.
- **User model:** Saved searches attach to the same `digest.models.User` built in sub-project 2 (no new, divergent user concept). This sub-project takes a dependency on `digest/` for that table.
- **Comparison scope:** Both papers-side-by-side and topics-side-by-side, as two separate comparison endpoints.
- **Visualization scope:** Per-topic evidence-tier distribution and a `ChangeEvent` timeline. Cross-topic trending is deferred.
- **API transport:** A real HTTP API via FastAPI (new dependency), not a Python-functions-only service layer — this sub-project is meant to be called by a future frontend or the enterprise API sub-project, so a real transport is built now.
- **Search filters (v1):** topic, evidence tier, study type, publication date range. Numeric thresholds on citation count / SJR are deferred.

## 3. Architecture

A new sibling Python package `webapp/`, alongside `evidence_engine/` and `digest/`, sharing the engine's Postgres database, config, and DB session, and depending on `digest.models.User` for saved searches.

Six components, each independently testable:

1. **Search index + sync** (`webapp/search_index.py`) — owns `PaperSearchIndex` (tsvector + GIN index) and `SearchIndexSyncState` (single-row watermark). `sync_search_index(session)` reads `ChangeEvent`s since the watermark, collects affected `paper_id`s (from `NEW_PAPER` and `PAPER_RETRACTED` events), re-reads current `Paper`/`Score`/`PaperTopic` data for each, and upserts its index row. Runnable as a script (`scripts/sync_search_index.py`), mirroring the engine's and digest's runner style — not a long-running daemon.
2. **Search service** (`webapp/search.py`) — `search_papers(session, query, filters, page)`: free text matched via `plainto_tsquery` against `search_vector`, filters as `WHERE` clauses on denormalized columns, ranked by `ts_rank`, joined back to live `Paper` fields for display so results never show stale index-only data. Retracted papers excluded by default (`include_retracted` overrides).
3. **Comparison service** (`webapp/compare.py`) — `compare_papers(session, paper_ids)` and `compare_topics(session, topic_ids)`, each returning side-by-side data for resolvable IDs plus a list of unresolved IDs (partial results, not all-or-nothing).
4. **Saved searches** (`webapp/saved_searches.py`) — `create_saved_search`, `list_saved_searches`, `delete_saved_search`, `run_saved_search` (re-executes `search_papers` with stored params against live data, updates `last_run_at`) — all keyed to `digest.models.User`.
5. **Visualization service** (`webapp/visualizations.py`) — `tier_distribution(session, topic_id)` (from live `Score`, not the index) and `change_timeline(session, topic_id, window_start, window_end)` (from `ChangeEvent`, bucketed by day and event type), reusing digest's windowing convention.
6. **HTTP API** (`webapp/api.py`) — a FastAPI app wiring the above into endpoints, testable with `TestClient`.

Data flows one direction: `sync job → search index` (write path, this package's own table only) and `API → service layer → engine's read-only tables + this package's own tables` (read path). No writes to the engine's tables.

## 4. Data Model

Postgres, same database and `Base` as the engine and digest. New tables:

- **PaperSearchIndex** — `id`, `paper_id` (FK `papers.id`, unique), `search_vector` (tsvector, GIN index), `topic_ids` (array of topic IDs, denormalized from `PaperTopic`), `evidence_tier` (nullable — not yet scored), `study_type` (nullable), `publication_date` (denormalized from `Paper`), `indexed_at`.
- **SearchIndexSyncState** — single-row table: `id`, `last_synced_at` (the incremental-sync watermark).
- **SavedSearch** — `id`, `user_id` (FK `digest.users.id`), `name`, `query_params` (JSON: free-text query + filter values), `created_at`, `last_run_at` (nullable).

Denormalizing tier/study_type/topic_ids/publication_date onto `PaperSearchIndex` keeps the full-text + filter query a single-table scan; the sync job is the sole place reconciling the index with source-of-truth tables.

## 5. Search, Sync & Comparison Behavior

- **Sync job:** incremental, windowed off `ChangeEvent.detected_at > last_synced_at`, same pattern as digest's change aggregator. Per-paper reindex failures are isolated (logged, skipped) and do **not** stall the watermark — the watermark still advances to the window end, leaving only the failed paper's index stale until its next relevant `ChangeEvent` (e.g. a later contradiction or retraction) re-triggers it. This favors platform-wide search freshness over perfect freshness for one bad record, consistent with the isolation principle used throughout the engine and digest.
- **Search ranking:** free text via `plainto_tsquery`, ranked by `ts_rank`; filters (topic, tier, study type, date range) as plain `WHERE` clauses; results joined back to live `Paper` fields.
- **Retractions:** excluded from default search results; `include_retracted=true` opts back in for auditing.
- **Comparison:** `compare_papers`/`compare_topics` return partial results plus an `unresolved_ids` list when some requested IDs don't exist — a typo or stale ID in a batch of 5 shouldn't drop the other 4.
- **Saved searches:** no uniqueness constraint on name; a user may save duplicate queries or reuse names freely.

## 6. HTTP API Surface

- `GET /search` — query params: `q`, `topic_id`, `tier`, `study_type`, `date_from`, `date_to`, `include_retracted`, `page`/`page_size`.
- `GET /compare/papers?paper_ids=...`, `GET /compare/topics?topic_ids=...`
- `POST /saved-searches`, `GET /saved-searches?user_id=...`, `DELETE /saved-searches/{id}`, `POST /saved-searches/{id}/run`
- `GET /topics/{id}/tier-distribution`
- `GET /topics/{id}/timeline?window_start=...&window_end=...`

## 7. Error Handling & Edge Cases

- Unknown `topic_id`/`user_id`/`saved_search_id` in a request → `404`.
- Comparison with some unresolvable IDs → `200` with partial results + `unresolved_ids` (not an error).
- Malformed filter values (bad date, unknown tier/study-type enum value) → `422` via FastAPI/Pydantic validation.
- Sync job per-paper failure → isolated, logged, watermark still advances (see Section 5).
- Empty comparison input (`paper_ids=[]` or `topic_ids=[]`) → `200` with an empty result, not an error.
- Paper not yet scored (`score_pending`) → included in search results with `evidence_tier`/`study_type` as null rather than excluded, so it's still discoverable by topic/text even before scoring completes.

## 8. Testing Strategy

- **Search index sync:** seed `ChangeEvent`/`Paper`/`Score` fixtures; assert correct incremental upsert, watermark advance despite an injected per-paper failure (sanity-checked by breaking one paper's reindex and confirming both that it's skipped/logged and that the watermark and other papers still advance/index correctly), and correct reindexing on retraction.
- **Search service:** unit tests per filter dimension and in combination, relevance ranking on a small known corpus, retracted-paper exclusion/override, `score_pending` inclusion with null tier/study_type.
- **Comparison service:** full match, partial match (some IDs unresolvable), and empty input.
- **Saved searches:** DB round-trip CRUD tests, `run_saved_search` re-execution against live (changed) data.
- **Visualizations:** fixture-seeded tier-distribution counts and timeline bucketing, with explicit boundary-pinning at `window_start`/`window_end` (same convention digest's aggregator tests used).
- **API layer:** FastAPI `TestClient` integration tests per endpoint, covering the `404`/`422`/partial-result/empty-input cases above.

## 9. Explicit Non-Goals (v1)

- Any rendered frontend (deferred; this sub-project is the backend query API only).
- Vector/semantic search (Postgres full-text only for v1; semantic search may follow as a v2).
- Authentication (still deferred to a later sub-project, per digest's precedent).
- The enterprise API.
- Real-time/streaming search-index updates (the sync job runs as a script on demand/schedule, not a live daemon).
- Numeric threshold filters on citation count or SJR.
- Cross-topic trending visualizations.
- Multiple saved-search folders, sharing, or collaboration features.
- Any modification of evidence-engine tables — this sub-project is read-only against the engine's store.
