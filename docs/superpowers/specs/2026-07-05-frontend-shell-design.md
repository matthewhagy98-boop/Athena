# Frontend Shell — Design Spec

Status: Approved (pending user sign-off on this document)
Date: 2026-07-05
Scope: Sub-project A of the rendered-frontend work (backlog item #1). Adds a rendered React frontend over `webapp/`'s existing search/compare/saved-search/visualization JSON API, styled per the "Scholastic Precision" reference design. Does not cover AI-generated synthesis narratives, trending/dashboard widgets, citation-velocity tracking, bookmarks/alerts/sharing/audit-log, or the interactive statistical analysis suite — those are sub-projects B through F, decomposed separately and out of scope here.

## 1. Purpose

Give the research intelligence platform a real, usable web UI over data the platform already has. Today, `webapp/`'s search, comparison, saved-search, and visualization capabilities (built in the third backend sub-project) are only reachable as a JSON API — there is no way for a person to actually use the product. This sub-project answers:

- How does a visitor search papers and topics, filter by tier/study-type/date, and see results grouped by evidence tier?
- How do they select papers or topics and see them compared side by side?
- How do they save a search, see their saved searches, re-run one, or delete it?
- How do they see a topic's evidence-tier distribution and change-event timeline as charts?
- How is a visitor identified without a login system, since none exists anywhere in the platform yet?

## 2. Scope Decisions

- **Frontend stack:** React + Vite SPA (TypeScript), not server-rendered Jinja2/HTMX — `webapp/api.py` was designed as a pure JSON API, and mixing in server-rendered HTML would blur that separation.
- **Serving:** Vite builds static assets; `webapp/api.py` mounts them via `StaticFiles` alongside its existing JSON routes. Same origin, no CORS needed, one deployable.
- **Visual direction:** the user-provided Google Stitch reference design (`Athena Web-View Template/`, "Scholastic Precision") is the source of truth for colors, type, spacing, and component visual language. `Athena Web-View Template/scholastic_precision/DESIGN.md` is the design-token file. The reference's `code.html` files are built with Tailwind CSS (CDN) using custom theme token names that map directly onto `DESIGN.md`'s color/type names, and Material Symbols Outlined icons.
- **Styling:** Tailwind CSS, configured with a theme extending `DESIGN.md`'s exact token names (`primary`, `primary-container`, `secondary`, `surface-container-*`, `font-headline-md`, etc.), so reference markup translates directly into JSX/className rather than re-deriving a CSS system from scratch.
- **Icons:** Material Symbols Outlined, loaded via Google Fonts stylesheet link, matching the reference.
- **Routing:** React Router, four routes: `/search`, `/compare`, `/saved-searches`, `/topics/:id`.
- **Server state:** TanStack Query (React Query) for every call to the webapp API — caching, loading/error states, and refetch-on-mutation, instead of hand-rolled state machines.
- **Charting library:** Recharts, for the tier-distribution and timeline charts on the Topic Detail page.
- **User identity:** no login system exists anywhere in the platform. On first visit, the frontend checks `localStorage` for a `user_id`; if absent, it calls a new backend endpoint to create a `digest.models.User` with no real email, and stores the returned `user_id`. All saved-search calls attach this `user_id`. Identity is device-bound (clearing storage loses it) — acceptable until real auth exists (a separate backlog item).
- **Scope boundary:** this sub-project covers exactly what `webapp/`'s existing API already supports — search, compare, saved searches, tier-distribution/timeline visualization. No synthesis narrative text, no trending widgets, no citation-velocity charts, no bookmarks/alerts/sharing/audit-log. Those need new backend capability and are separate, later sub-projects.

## 3. Architecture

A new sibling package `webapp/frontend/` (Vite + React + TypeScript), built to static assets and mounted by `webapp/api.py` via `StaticFiles`. The existing FastAPI app gains exactly one new endpoint (the anonymous-user creation endpoint below); everything else is consumed as-is from the already-shipped search/compare/saved-search/visualization API (see `docs/superpowers/specs/2026-07-04-web-search-ui-design.md` section 6 for the full existing route list).

```
webapp/frontend/
  src/
    api/          # typed fetch wrappers + React Query hooks, one per webapp endpoint
    identity/      # anonymous user_id bootstrap (localStorage + POST /users/anonymous)
    components/    # IconSidebar, ResearchCard, EvidenceIndicator, TierSection, CompareTray, charts
    pages/          # SearchPage, ComparePage, SavedSearchesPage, TopicDetailPage
    App.tsx         # React Router route table + IconSidebar shell
  tailwind.config.ts # theme tokens mirroring DESIGN.md
  vite.config.ts
```

Data flow is read-mostly against the existing API, plus the one new write path:

- **New write path:** `POST /users/anonymous` → `digest.profiles.create_anonymous_user(session) -> User` → new `digest.models.User` row with a generated placeholder email.
- **Existing read/write paths:** unchanged, consumed via React Query hooks that wrap the routes listed in the web-search-ui spec's section 6 (`/search`, `/compare/papers`, `/compare/topics`, `/saved-searches` CRUD + `/run`, `/topics/{id}/tier-distribution`, `/topics/{id}/timeline`).

### New backend endpoint: anonymous user creation

`digest.models.User.email` is currently `unique=True, nullable=False` (designed assuming every user is a real digest-delivery recipient). Rather than migrate the schema to make email nullable, the anonymous-user endpoint generates a placeholder unique value (e.g. `anon-<uuid>@no-reply.local`). No `digest/` migration needed; if a user later gets real auth, the row can be updated in place.

- `digest.profiles` (new module): `create_anonymous_user(session) -> User`, generates the placeholder email, inserts, returns the row.
- `webapp/api.py`: `POST /users/anonymous`, no request body, returns `{"user_id": "<uuid>"}`.
- Gets its own small test file (`tests/digest/test_profiles.py` or similar), mirroring how every prior sub-project gave a new endpoint its own focused test — folding it into a page's task would bury a genuinely new capability (user creation) inside frontend plumbing.

## 4. Pages & Components

- **App shell:** `IconSidebar` — slim, deep-navy, icon-only nav (Material Symbols Outlined) for Search, Compare, Saved Searches, with teal active-state indicators, matching every reference screen. Collapses to a bottom-sheet/stacked nav on mobile per `DESIGN.md`'s responsive rules. Wraps all routed pages.

- **Search page** (`/search`):
  - `FilterSidebar` — topic, evidence tier, study type, publication date range, always visible, controlled inputs.
  - Three `TierSection`s, one per `EvidenceTier` (Established / Emerging / Speculative), each rendering its matching papers as a list of `ResearchCard`s (title in Inter bold, excerpt in Source Serif 4, an `EvidenceIndicator` 5-step bar, a selection checkbox). Papers with `evidence_tier: null` (not yet scored) render in their own "Not Yet Scored" section rather than being dropped, consistent with the backend's `score_pending` inclusion behavior.
  - A floating `CompareTray` appears once ≥1 card is checked, showing "Compare (N)"; clicking it navigates to `/compare?paper_ids=...`.
  - A "Save this search" action opens a name-entry dialog and `POST`s the current query+filters to `/saved-searches`.
  - The reference's Consensus Report gauge and Research Quality Breakdown donut are **not built in this sub-project** — they depend on synthesis-narrative/quality-scoring data that's out of scope until sub-project B.

- **Compare page** (`/compare`): reads `paper_ids` or `topic_ids` from the URL query string (set by the Search page's tray, or by a Topic Detail page's "Add to compare" action), calls `/compare/papers` or `/compare/topics` accordingly, renders resolved items as side-by-side cards plus a small notice listing any `unresolved_ids`.

- **Saved Searches page** (`/saved-searches`): lists the current user's saved searches (name, stored query/filters, last-run time) with Run and Delete actions per row. Running re-executes the search live and navigates to `/search` with the results loaded; deleting removes it after a confirmation.

- **Topic Detail page** (`/topics/:id`): `TierDistributionChart` and `TimelineChart` (Recharts) full-width on top, a plain papers table below (this layout was already confirmed separately from the Search-page card/table question and is unaffected by it). Reached by drilling into a topic link from search results, not from the sidebar nav. Includes an "Add to compare" action that appends this topic's ID to the Compare page's `topic_ids` query param.

## 5. Data Flow

Each page's data need is a single React Query hook wrapping one API call (e.g. `useSearch(filters, page)` → `GET /search`, `useTopicTimeline(topicId, window)` → `GET /topics/:id/timeline`). Compare-selection state lives in the URL query string, not client-side state, so a compare view survives refresh and back-navigation and can be shared as a link. Checkbox selection *before* navigating to Compare is local component state scoped to the Search page. Identity (`user_id`) is bootstrapped once at app mount (`identity/` module: check `localStorage`, `POST /users/anonymous` if absent, persist the result) and read by any hook that needs it (saved searches CRUD).

## 6. Error Handling & Edge Cases

- Unknown `topic_id` / `user_id` / `saved_search_id` (backend 404) → inline "not found" message scoped to the affected panel, not a full-page crash.
- Partial compare results (`unresolved_ids` non-empty) → render resolved cards normally, plus a small "N id(s) not found" notice.
- Malformed filter values are prevented client-side (native date inputs, enum-constrained selects for tier/study-type), so the backend's `422` is a defensive fallback, not a normal path — no dedicated UI is built for it beyond a generic inline error message if it ever occurs.
- Empty search results → per-`TierSection` "no papers in this tier" state, or a single page-level "no results" state if every tier (including "Not Yet Scored") is empty.
- Loading states → skeleton `ResearchCard`s and chart placeholders driven by React Query's `isLoading`.
- Anonymous user creation failing (network error at first app load) → retry via React Query's default retry behavior; block saved-search actions (not search/compare, which don't need identity) with a disabled state + inline error until identity resolves.

## 7. Testing Strategy

- **Vitest + React Testing Library** for component/page tests: `FilterSidebar` interactions, tier-grouping logic against sample API responses (including the `score_pending`/null-tier case), checkbox selection building `CompareTray` state and URL params, empty/error/loading states per page.
- **MSW (Mock Service Worker)** to mock the webapp API in all frontend unit tests — no real backend required for these.
- **`tests/digest/test_profiles.py`** (or equivalent): unit tests for `create_anonymous_user` — generates a valid placeholder email, inserts successfully, uniqueness across repeated calls.
- **One Playwright smoke test** against the real FastAPI app (serving the built frontend): anonymous user creation → search → select two papers → compare → save a search → run the saved search. Covers the golden path end-to-end; deeper per-feature testing happens at the unit/component level above.

## 8. Explicit Non-Goals (this sub-project)

- Any AI-generated synthesis narrative or "Consensus Report" gauge / "Research Quality Breakdown" donut on the Search page (sub-project B).
- Trending topics, "Weekly Research Blurb," or any dashboard page (sub-project C).
- Citation-velocity charts on saved searches (sub-project D).
- Bookmarks, alerts, sharing/workspaces, audit log (sub-project E).
- The Interactive Evidence Suite (regression/raw-data views) (sub-project F).
- Real user authentication (anonymous `localStorage` identity only; real auth is a separate backlog item).
- Any modification to `webapp/`'s existing search/compare/saved-search/visualization service logic — this sub-project is a pure frontend consumer of that API plus the one new anonymous-user endpoint.
- Semantic/vector search, numeric threshold filters, cross-topic trending — already out of scope per the underlying web-search-ui spec and unchanged here.
