# Enterprise API — Design Spec

Status: Approved (pending user sign-off on this document)
Date: 2026-07-05
Scope: Fourth and final sub-project of the research intelligence platform. Covers organization authentication (API keys), per-organization rate limiting, and an org-facing query surface over the evidence engine's data. Does not cover a rendered frontend, self-serve signup/billing, OAuth, or per-org data partitioning.

## 1. Purpose

Let organizations programmatically query the evidence engine's data — search, comparison, and visualizations — via API keys, with per-organization rate limits enforced before any query executes. This is the enterprise-facing counterpart to the individual-user-facing search API built in sub-project 3 (`webapp/`): same underlying data and query logic, different audience, different access model (authenticated, rate-limited, server-to-server) instead of no-auth.

This sub-project answers:
- Which organization is making this request, and is its API key valid and unrevoked?
- Is this organization suspended, and if so, should the request be blocked regardless of key validity?
- Has this organization exceeded its allotted request rate for the current window?
- Once authenticated and within its rate limit, how does an organization search papers, compare papers/topics, or pull visualization data?

## 2. Scope Decisions

- **Auth mechanism:** API keys, not OAuth 2.0. Each organization holds one or more long-lived keys (hashed at rest, shown once at creation). Standard for server-to-server B2B data APIs; avoids building token issuance/refresh/expiry infrastructure this sub-project doesn't need.
- **Organization model:** A new, separate `Organization`/`ApiKey` concept in this sub-project's own package — not an extension of `digest.models.User`. Organizations (a company, authenticated via API key) and Users (an individual digest/interest-profile recipient, no auth) are different audiences with different lifecycles; conflating them would tangle two unrelated concepts into one table.
- **Rate limiting:** Enforced via a Postgres-backed per-organization request counter (fixed hourly window), not a new Redis dependency — consistent with this codebase's existing preference for reusing Postgres over adding new infrastructure (mirrors the full-text-search-over-vector-DB decision in sub-project 3).
- **Rate limit configurability:** Per-organization, not a single global constant. Each `Organization` row carries its own `rate_limit_per_hour` (defaulting to a standard value at provisioning), so future negotiated/tiered quotas need no schema change.
- **API surface:** A separate FastAPI app (`enterprise_api/`), not an extension of `webapp/api.py`. Its route handlers call directly into `webapp/`'s existing, already-tested service functions (`search_papers`, `compare_papers`/`compare_topics`, `tier_distribution`/`change_timeline`) rather than reimplementing query logic. Keeps the no-auth consumer surface and the authenticated/rate-limited org surface cleanly separated, matching the existing pattern of `digest/` and `webapp/` as independent packages reading the same engine store.
- **Endpoint scope:** Search, comparison, and visualizations only — no saved searches on this surface. Saved searches are a personal workflow feature tied to an individual `digest.User`, not a natural fit for a server-to-server org API.
- **Provisioning:** Admin-only in v1. Organizations and API keys are created via Python functions and a CLI script, mirroring how `Topic`s and `User`s are created elsewhere in this codebase today — no public signup endpoint, no billing integration.

## 3. Architecture

A new sibling Python package `enterprise_api/`, alongside `evidence_engine/`, `digest/`, and `webapp/`, sharing the engine's Postgres database, config, and DB session. It depends on `webapp/`'s service-layer functions (not its FastAPI app) for all query logic.

Five components, each independently testable:

1. **Data model** (`enterprise_api/models.py`) — `Organization`, `ApiKey`, `RateLimitWindow`.
2. **Provisioning** (`enterprise_api/provisioning.py`) — `create_organization`, `create_api_key` (returns the plaintext key once, stores only its hash), `revoke_api_key`. Wrapped by `scripts/provision_organization.py` for operator use.
3. **Auth** (`enterprise_api/auth.py`) — `get_authenticated_organization`, a FastAPI dependency that validates the presented API key and resolves it to an `Organization`, or raises `401`/`403`.
4. **Rate limiting** (`enterprise_api/rate_limit.py`) — `enforce_rate_limit`, a FastAPI dependency that increments a Postgres-backed per-org, per-hour counter and raises `429` when the organization's limit is exceeded.
5. **API** (`enterprise_api/api.py`) — a FastAPI app applying `get_authenticated_organization` → `enforce_rate_limit` to every route, delegating each route's actual query logic to `webapp/`'s existing service functions.

Data/request flow: `request → auth dependency (key → Organization) → rate-limit dependency (Postgres counter check/increment) → route handler → webapp service function → response`. This package writes only to its own tables (`organizations`, `api_keys`, `rate_limit_windows`); it never writes to the evidence engine's tables and never writes to `webapp/`'s or `digest/`'s tables either — it only calls their read-only service functions.

## 4. Data Model

Postgres, same database and `Base` as the rest of the platform. New tables:

- **Organization** — `id`, `name`, `status` (`active`/`suspended`, default `active`), `rate_limit_per_hour` (int, default a standard value, e.g. 1000), `created_at`.
- **ApiKey** — `id`, `organization_id` (FK `organizations.id`), `key_hash` (hashed secret; the plaintext key is never persisted), `key_prefix` (short, non-secret visible portion for display/audit, e.g. the first 8 characters), `created_at`, `revoked_at` (nullable; non-null means the key no longer authenticates).
- **RateLimitWindow** — `id`, `organization_id` (FK), `window_start` (the current fixed-hour window's start timestamp), `request_count` (int). Unique on `(organization_id, window_start)`. A fixed hourly window (not sliding) keeps the counter logic to a single upsert-and-increment per request.

## 5. Auth & Rate Limiting Behavior

- **Auth:** the API key is read from an `Authorization: Bearer <key>` header, hashed, and looked up against non-revoked `ApiKey` rows. Missing/malformed header, or no matching non-revoked key → `401`. A key is checked for revocation on every single request (not cached), so a just-revoked key fails immediately, even mid-hour. A valid key whose `Organization.status == "suspended"` → `403`.
- **Rate limiting:** runs after auth succeeds. Computes the current hour's `window_start` (truncated to the hour), upserts `RateLimitWindow` for `(organization_id, window_start)` incrementing `request_count`, and raises `429` (with the limit and window in the response body) if the incremented count exceeds the organization's `rate_limit_per_hour`. The request that crosses the limit is itself counted (standard fixed-window semantics) — a fresh hour always starts the counter at zero via the upsert's default insert path.
- **Provisioning:** `create_api_key` generates a random secret, stores only its hash and prefix, and returns the plaintext secret exactly once at creation time — nothing in the system persists or re-displays it afterward. `revoke_api_key` sets `revoked_at`, taking effect on the very next request.

## 6. HTTP API Surface

All routes require a valid, non-revoked API key belonging to a non-suspended organization, and are subject to that organization's rate limit.

- `GET /v1/search` — delegates to `webapp.search.search_papers`.
- `GET /v1/compare/papers` — delegates to `webapp.compare.compare_papers`.
- `GET /v1/compare/topics` — delegates to `webapp.compare.compare_topics`.
- `GET /v1/topics/{topic_id}/tier-distribution` — delegates to `webapp.visualizations.tier_distribution`.
- `GET /v1/topics/{topic_id}/timeline` — delegates to `webapp.visualizations.change_timeline`.

Response shapes mirror `webapp/api.py`'s existing JSON shapes for the same underlying data, since both surfaces expose the same query capabilities to different audiences.

## 7. Error Handling & Edge Cases

- `401` — missing/malformed `Authorization` header; API key not found; API key revoked (checked on every request, never cached).
- `403` — API key is valid, but its organization's `status` is `suspended`.
- `429` — organization has exceeded `rate_limit_per_hour` for the current hour window; response body includes the configured limit and window info.
- `404`/`422` — unchanged from `webapp/api.py`'s existing behavior (unknown topic ID, malformed filter values), since these routes delegate to the same service functions and inherit their validation.
- Revocation is immediate: a key revoked mid-window fails auth on its very next request, regardless of remaining rate-limit budget.
- A brand-new hour window for an organization always starts its counter at zero, even if the organization was previously rate-limited in the prior hour.

## 8. Testing Strategy

- **Models:** round-trip tests for `Organization`/`ApiKey`/`RateLimitWindow`; the unique constraint on `(organization_id, window_start)` rejects a duplicate window row.
- **Provisioning:** `create_api_key` returns a plaintext key that is not itself persisted anywhere (only its hash is stored), and that hash correctly re-validates the same plaintext on a later lookup; `revoke_api_key` causes subsequent auth attempts with that key to fail.
- **Auth:** valid key resolves the correct organization; unknown key → 401; revoked key → 401; suspended organization's otherwise-valid key → 403.
- **Rate limiting:** requests under the limit succeed and increment the counter; the request that pushes the count over the limit returns 429; seeding a `RateLimitWindow` for a past hour and then making a request in the current hour proves the counter resets to a fresh window rather than carrying over.
- **API integration:** FastAPI `TestClient` tests per route, covering the full auth → rate-limit → service-function → response chain end-to-end, plus explicit 401/403/429 path tests.

## 9. Explicit Non-Goals (v1)

- Self-serve organization signup (admin-provisioned only).
- Saved searches on this surface.
- OAuth 2.0 or any auth mechanism beyond API keys.
- Per-organization result-level data scoping/partitioning — the evidence data is not org-owned; v1 scopes access, not data.
- Tiered/negotiated rate-limit plans as a billing/product concept (the schema supports per-org limits; no plan-tier UI or billing logic).
- API key rotation UX beyond immediate revocation (e.g. no overlapping-validity grace period for a replacement key).
- Any modification of evidence-engine, digest, or webapp tables — this sub-project is read-only against all of them, writing only to its own three tables.
