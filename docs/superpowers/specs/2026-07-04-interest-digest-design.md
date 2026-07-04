# Interest Profiles & Digest Delivery — Design Spec

Status: Approved (pending user sign-off on this document)
Date: 2026-07-04
Scope: Second sub-project of the research intelligence platform. Covers user interest profiles and the weekly AI-summarized digest pipeline that reads from the evidence engine. Does not cover the web app / search UI or the enterprise API, which are separate sub-projects. Does not cover authentication (login/session/password) — that belongs to a later sub-project.

## 1. Purpose

Let a user register interests (free-text research topics), and receive a periodic AI-summarized email digest of what changed in those topics — new strong evidence, updated consensus, contradictions, and retractions — grounded in the evidence engine's output.

This sub-project answers, per user:
- What research topics does this user care about?
- What meaningfully changed in those topics since we last told them?
- How do we turn those changes into a readable per-topic summary and deliver it on a schedule, reliably and idempotently?

It is a backend pipeline, not a logged-in experience. Digest generation and delivery run on a schedule; there is no interactive UI in this sub-project.

## 2. Scope Decisions

- **Relationship to the evidence engine:** This sub-project **reads** the engine's `Topic`, `Paper`, `Score`, `ConsensusSnapshot`, and `ChangeEvent` tables and **never writes** to them. Data flows one direction (engine → digest), consistent with the engine spec's downstream-consumer model.
- **User model:** Build `User`, interest `InterestProfile`, and `DeliveryPreference`. **No authentication** (no login, password, or session) — that is a later sub-project's concern. A `User` here is just an addressable recipient with interests and preferences.
- **Interest resolution:** Free-text interests are resolved to canonical evidence-engine `Topic`s by reusing the engine's existing `evidence_engine.topics.registry.get_or_create_topic`. No duplicate MeSH/normalization logic is built here.
- **Digest content:** Change-driven and LLM-summarized. For each of a user's topics, the digest reports the `ChangeEvent`s in the delivery window (new top-tier papers, consensus updates, contradictions, retractions), summarized into a short per-topic narrative. Topics with no meaningful change in the window are omitted.
- **Delivery:** A pluggable `EmailSender` interface. Every digest is rendered (HTML + plain text) and persisted for audit before/independent of sending. The default sender is a console/no-op sender used in tests and local runs; a real SMTP sender implements the same interface behind configuration. No live email credentials are required to run or test the default path — mirroring the engine's respx-mocked LLM discipline.
- **"What changed today":** The reusable per-user change-aggregation core is built in v1, but only the **weekly** digest is wired to it. A standalone daily/real-time "what changed today" surface is deferred to when the web app exists to display it.
- **Cadence:** Per-user cadence. `DeliveryPreference` stores a `frequency` enum (`weekly` for v1, with room for `daily` later), a preferred `send_day`, and a `last_digest_sent_at` watermark. A scheduled runner selects users who are *due* and is idempotent via the watermark.
- **LLM provider:** Anthropic Claude, model `claude-sonnet-4-6` by default via the same `ANTHROPIC_MODEL` config the engine uses, behind a mockable client.
- **HTML rendering:** Jinja2 templates (one new dependency), for HTML and plain-text digest bodies.

## 3. Architecture

A new sibling Python package `digest/` in the same repository, sharing the engine's Postgres database, config (`evidence_engine.config`), and DB session (`evidence_engine.db.session`). New ORM models share the engine's declarative `Base` (`evidence_engine.db.models.Base`) so the project keeps a single Alembic migration chain and can declare foreign keys to `topics.id`; the model classes themselves live in `digest/models.py` to keep the two sub-projects' code separate.

Six components, each independently testable:

1. **Profile service** (`digest/profiles.py`) — create/lookup users; add/remove interests (resolving free text to `Topic`s via the engine registry); read/update delivery preferences.
2. **Change aggregator** (`digest/aggregate.py`) — the reusable core. Given a `user` and a `(window_start, window_end)`, gather `ChangeEvent`s across the user's topics and hydrate them with the associated `Paper`/`Score`/`ConsensusSnapshot` data into a structured, LLM-ready result (only topics with change in the window are included). This is the shared engine a future "what changed today" feed will also call.
3. **Digest composer** (`digest/compose.py`) — an LLM pass turning each topic's structured changes into a short per-topic narrative, assembled into a composed-digest object. Claude behind the same mockable client pattern the engine uses.
4. **Renderer** (`digest/render.py`) — deterministic Jinja2 rendering of the composed digest into HTML + plain-text bodies and a subject line. No LLM; template-based and byte-for-byte unit-testable.
5. **Delivery** (`digest/delivery.py`) — an `EmailSender` `Protocol` with `ConsoleSender` (default/tests) and `SmtpSender` (real, behind config). Persists a `DigestEmail` row regardless of send outcome.
6. **Weekly runner** (`digest/runner.py` + `scripts/run_digests.py`) — the scheduled entrypoint, mirroring the engine's `run_daily_cycle`. Runs daily, selects due users, and for each runs aggregate → compose → render → send → advance-watermark within a per-user transaction, isolating per-user failures.

Data flows one direction: `runner → aggregate → compose → render → deliver`, reading from the engine's store and writing only to the digest package's own tables.

## 4. Data Model

Postgres, same database and `Base` as the engine. New tables:

- **User** — id (UUID), email (unique), status (`active`/`paused`, default `active`), created_at.
- **InterestProfile** — id, user_id (FK `users.id`), created_at. (One profile per user in v1; modeled as its own table to leave room for multiple named profiles later.)
- **ProfileTopic** — many-to-many join: id, profile_id (FK), topic_id (FK `topics.id`), added_at. Unique on (profile_id, topic_id).
- **DeliveryPreference** — id, user_id (FK, unique), frequency (enum `DigestFrequency`: `weekly`; enum leaves room for `daily`), send_day (int 0–6, Monday=0), last_digest_sent_at (nullable timestamp — the watermark), created_at, updated_at.
- **DigestRun** — id, user_id (FK), window_start, window_end, status (enum `DigestRunStatus`: `sent`, `skipped_no_changes`, `failed`), created_at. One row per generation attempt, for audit and idempotency.
- **DigestEmail** — id, digest_run_id (FK, unique), subject, html_body, text_body, sender_name (which sender handled it), send_result (`success`/`failure` + detail), sent_at (nullable). Written whenever a render happens, including failed sends.

Enums (`DigestFrequency`, `DigestRunStatus`, `EmailSendResult`) live in `digest/models.py`.

## 5. Cadence & Scheduling

- **Due selection:** the runner runs daily. A user is *due* when: status is `active`, they have at least one interest topic, and either `last_digest_sent_at` is null (never sent) or the configured `frequency` interval has elapsed since it. For `weekly`, the runner also honors `send_day` (only send on the user's chosen weekday), so weekly users get a predictable delivery day.
- **Window:** `window_start` = `last_digest_sent_at` (or the user/profile creation time on first send, to avoid an unbounded first window); `window_end` = run time.
- **Idempotency:** because due-selection is driven by the watermark and the watermark advances only on a successful `sent`/`skipped_no_changes` outcome, re-running the runner the same day does not double-send.
- **Watermark advance:** advanced to `window_end` on `sent` and on `skipped_no_changes`; **not** advanced on `failed` (so the user is retried next run and no change is lost).

## 6. Error Handling & Edge Cases

- **No changes in window:** no email is sent; a `DigestRun` with status `skipped_no_changes` is recorded and the watermark still advances (so the window does not grow unbounded and the user isn't reprocessed for the same empty period).
- **LLM compose failure:** retried; on persistent failure the user's `DigestRun` is marked `failed`, the watermark is not advanced, and the runner moves on to the next user. One user's failure never blocks others (same isolation principle as the engine's per-topic cycle).
- **Send failure:** the `DigestEmail` is persisted with a `failure` send_result; the `DigestRun` is marked `failed`; the watermark is not advanced.
- **Unresolvable interest:** adding an interest that the engine registry cannot resolve raises the same `ValueError` contract as `get_or_create_topic` — surfaced to the caller, not silently dropped.
- **Paused user / no interests:** excluded from due-selection; no run is created.
- **Retracted / contradicted evidence:** surfaced in the digest as first-class change types (from the engine's `PAPER_RETRACTED` and `CONTRADICTION_FLAGGED` `ChangeEvent`s), not suppressed.

## 7. Testing Strategy

- **Profile service:** DB round-trip tests for users/profiles/preferences; interest-add reuses the engine registry (mocked) and the unresolvable-term path raises.
- **Change aggregator:** seed the engine tables with `ChangeEvent`/`Paper`/`Score`/`ConsensusSnapshot` fixtures and assert correct windowing and hydration. Explicitly pin the boundary semantics — a change exactly at `window_start` vs `window_end` — and explicitly assert that topics with no change in the window are excluded (so the test proves the filtering, not just the happy path).
- **Digest composer:** LLM mocked; assert the structured changes reach the prompt and the model output maps into the composed-digest object; assert a topic with only a retraction still composes.
- **Renderer:** deterministic golden-file assertions for HTML and plain text from a fixed composed digest.
- **Delivery:** `ConsoleSender` captures output; assert `DigestEmail` is persisted on both success and failure, and that `SmtpSender` is selected only when configured.
- **Runner (integration):** a full cycle over mocked engine data and mocked LLM verifying due-selection (including `send_day` and never-sent cases), watermark advance on sent/skipped but not on failed, per-user failure isolation, and no-double-send on same-day re-run.

## 8. Explicit Non-Goals (v1)

- Authentication (login, password, session, account recovery).
- The web app UI, search/filter experience, or any interactive surface.
- A standalone daily "what changed today" email or feed (the reusable aggregation core is built; only the weekly digest is wired).
- The enterprise API.
- Real transactional-email-provider integration beyond a single SMTP adapter (e.g., SES/SendGrid API clients) — added later behind the same `EmailSender` interface.
- Multiple named profiles per user, unsubscribe-link handling, and bounce/complaint processing.
- Any modification of evidence-engine tables — this sub-project is read-only against the engine's store.
