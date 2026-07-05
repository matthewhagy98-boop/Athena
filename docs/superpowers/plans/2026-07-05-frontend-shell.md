# Frontend Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the rendered React frontend (sub-project A) over `webapp/`'s existing search/compare/saved-search/visualization API, styled per the Scholastic Precision reference design, plus three small backend additions to `webapp/api.py` (anonymous-user endpoint, `GET /topics`, enriched paper serialization).

**Architecture:** A Vite + React + TypeScript SPA in `webapp/frontend/`, built to static assets and mounted by `webapp/api.py` via `StaticFiles`. Hash-based routing (`/#/search`) so the SPA needs no server-side fallback route. TanStack Query wraps every API call; identity is an anonymous `digest.models.User` created on first visit and stored in `localStorage`. Backend additions are serialization/query-only — no service-logic or schema changes.

**Tech Stack:** Python 3.12 + FastAPI (existing), React 18 + TypeScript + Vite, Tailwind CSS v4 (`@tailwindcss/vite`, theme tokens from `Athena Web-View Template/scholastic_precision/DESIGN.md`), react-router-dom v7 (HashRouter), @tanstack/react-query v5, Recharts, Vitest + React Testing Library + MSW, Playwright.

## Global Constraints

- Design tokens come from `Athena Web-View Template/scholastic_precision/DESIGN.md` — exact hex values below in Task 3's `index.css`; do not invent colors or type sizes (per spec section 2).
- Fonts: Inter for UI/labels, Source Serif 4 for paper excerpts/long-form text; icons are Material Symbols Outlined (per spec section 2).
- The Search page groups results into tier card sections (Established / Emerging / Speculative / Not yet scored) — NOT a flat table. No Consensus Report gauge, no Research Quality Breakdown donut (deferred to sub-project B) (per spec section 4).
- Backend changes are limited to `webapp/api.py` serialization/endpoints and a new `digest.profiles.create_anonymous_user` — never modify `webapp/` service modules (`search.py`, `compare.py`, `saved_searches.py`, `visualizations.py`, `search_index.py`), evidence-engine tables, or any Alembic schema (per spec sections 3 and 8).
- `digest.models.User.email` stays `unique=True, nullable=False`; anonymous users get a generated `anon-<uuid>@no-reply.local` placeholder email — no migration (per spec section 3).
- `create_anonymous_user` must NOT create `DeliveryPreference`/`InterestProfile` rows (unlike `digest.profiles.create_user`) — placeholder emails must never be enrolled in digest delivery.
- Compare-selection state lives in the URL query string (`#/compare?paper_ids=...`), not client state (per spec section 5).
- Backend tests run with the existing `db_session` fixture (real Postgres, transaction-rollback isolation) from `tests/conftest.py`. Frontend unit tests use MSW — never a real backend.
- Python: run tests with `.venv/bin/pytest` from the repo root. Frontend: run everything from `webapp/frontend/` with `npm`/`npx`.

---

## Task 1: Anonymous-User Endpoint

**Files:**
- Modify: `digest/profiles.py` (add `create_anonymous_user`)
- Modify: `webapp/api.py` (add `POST /users/anonymous`)
- Test: `tests/digest/test_profiles.py`, `tests/webapp/test_api.py`

**Interfaces:**
- Consumes: `digest.models.User` (existing), `tests/conftest.py::db_session` fixture (existing).
- Produces: `digest.profiles.create_anonymous_user(session: Session) -> User`; HTTP `POST /users/anonymous` → `201 {"user_id": "<uuid>"}`. Task 4's identity bootstrap calls this endpoint.

- [ ] **Step 1: Write the failing tests**

Append to `tests/digest/test_profiles.py`:

```python
def test_create_anonymous_user_generates_placeholder_email(db_session):
    user = create_anonymous_user(db_session)
    assert user.id is not None
    assert user.email.startswith("anon-")
    assert user.email.endswith("@no-reply.local")


def test_create_anonymous_user_emails_are_unique(db_session):
    a = create_anonymous_user(db_session)
    b = create_anonymous_user(db_session)
    assert a.email != b.email


def test_create_anonymous_user_does_not_enroll_in_digest_delivery(db_session):
    from sqlalchemy import select
    from digest.models import DeliveryPreference, InterestProfile

    user = create_anonymous_user(db_session)
    assert db_session.execute(
        select(DeliveryPreference).where(DeliveryPreference.user_id == user.id)
    ).scalar_one_or_none() is None
    assert db_session.execute(
        select(InterestProfile).where(InterestProfile.user_id == user.id)
    ).scalar_one_or_none() is None
```

Update the import at the top of the file to include `create_anonymous_user`:

```python
from digest.profiles import add_interest, create_anonymous_user, create_user, list_interests, remove_interest
```

(Match whatever names that import line already has — only add `create_anonymous_user`.)

Append to `tests/webapp/test_api.py`:

```python
def test_create_anonymous_user_endpoint(db_session):
    client = _client(db_session)
    response = client.post("/users/anonymous")
    assert response.status_code == 201
    user_id = uuid.UUID(response.json()["user_id"])

    from digest.models import User
    user = db_session.get(User, user_id)
    assert user is not None
    assert user.email.endswith("@no-reply.local")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/digest/test_profiles.py tests/webapp/test_api.py::test_create_anonymous_user_endpoint -v`
Expected: FAIL — `ImportError: cannot import name 'create_anonymous_user'`.

- [ ] **Step 3: Implement `create_anonymous_user`**

In `digest/profiles.py`, add after `create_user` (uuid is already imported):

```python
def create_anonymous_user(session: Session) -> User:
    # No InterestProfile/DeliveryPreference: placeholder emails must never
    # be enrolled in digest delivery.
    user = User(email=f"anon-{uuid.uuid4()}@no-reply.local")
    session.add(user)
    session.flush()
    return user
```

- [ ] **Step 4: Implement the endpoint**

In `webapp/api.py`, add to the imports from digest:

```python
from digest.profiles import create_anonymous_user
```

Add the route (place it with the other saved-search/user routes):

```python
@app.post("/users/anonymous", status_code=201)
def create_anonymous_user_endpoint(db: Session = Depends(get_db)) -> dict:
    user = create_anonymous_user(db)
    return {"user_id": str(user.id)}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/digest/test_profiles.py tests/webapp/test_api.py -v`
Expected: all PASS (including pre-existing tests).

- [ ] **Step 6: Commit**

```bash
git add digest/profiles.py webapp/api.py tests/digest/test_profiles.py tests/webapp/test_api.py
git commit -m "feat: add anonymous-user creation endpoint for frontend identity"
```

---

## Task 2: `GET /topics` + Enriched Paper Serialization

**Files:**
- Modify: `webapp/api.py`
- Test: `tests/webapp/test_api.py`

**Interfaces:**
- Consumes: `evidence_engine.db.models.Topic`, `PaperTopic` (read-only), existing `_paper_out` helper and its three call sites (`/search`, `/compare/papers`, `/saved-searches/{id}/run`).
- Produces: HTTP `GET /topics` → `200 [{"id", "canonical_label"}]` sorted by label. Every paper row in `/search`, `/compare/papers`, and `/saved-searches/{id}/run` responses gains `"topics": [{"id", "canonical_label"}]`, `paper.abstract` (string | null), and `score.study_type` (string). `GET /saved-searches` rows gain `"last_run_at"` (ISO string | null). Task 4's TypeScript types mirror these shapes exactly.

- [ ] **Step 1: Write the failing tests**

Append to `tests/webapp/test_api.py`:

```python
def test_list_topics_endpoint_returns_sorted_topics(db_session):
    db_session.add(Topic(canonical_label="Zebra Topic", mesh_id="D000101"))
    db_session.add(Topic(canonical_label="Alpha Topic", mesh_id="D000102"))
    db_session.flush()

    client = _client(db_session)
    response = client.get("/topics")

    assert response.status_code == 200
    labels = [t["canonical_label"] for t in response.json()]
    assert labels == sorted(labels)
    assert {"id", "canonical_label"} <= set(response.json()[0].keys())


def test_search_rows_include_topics_abstract_and_study_type(db_session):
    topic = Topic(canonical_label="Enriched Topic", mesh_id="D000103")
    db_session.add(topic)
    db_session.flush()
    paper = _seed_paper(db_session, topic, "Enrichment study of drug Q")
    paper.abstract = "A detailed abstract about drug Q."
    db_session.flush()
    sync_search_index(db_session)

    client = _client(db_session)
    row = client.get("/search", params={"q": "drug Q"}).json()["rows"][0]

    assert row["paper"]["abstract"] == "A detailed abstract about drug Q."
    assert row["score"]["study_type"] == "rct"
    assert row["topics"] == [{"id": str(topic.id), "canonical_label": "Enriched Topic"}]


def test_compare_papers_rows_include_topics(db_session):
    topic = Topic(canonical_label="Compare Topic", mesh_id="D000104")
    db_session.add(topic)
    db_session.flush()
    paper = _seed_paper(db_session, topic, "Comparable paper")

    client = _client(db_session)
    response = client.get("/compare/papers", params={"paper_ids": [str(paper.id)]})

    assert response.json()["rows"][0]["topics"][0]["canonical_label"] == "Compare Topic"


def test_list_saved_searches_includes_last_run_at(db_session):
    user = create_user(db_session, "listrun@example.com")
    client = _client(db_session)
    client.post("/saved-searches", json={"user_id": str(user.id), "name": "Mine", "query_params": {"q": "x"}})

    rows = client.get("/saved-searches", params={"user_id": str(user.id)}).json()

    assert rows[0]["last_run_at"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/webapp/test_api.py -v -k "topics or enriched or study_type"`
Expected: FAIL — `/topics` returns 404 (route doesn't exist yet; note FastAPI will match `/topics` against no route since only `/topics/{id}/...` exist), and KeyError on `"topics"` / `"abstract"`.

- [ ] **Step 3: Implement**

In `webapp/api.py`:

Add imports:

```python
from sqlalchemy import select

from evidence_engine.db.models import EvidenceTier, PaperTopic, StudyType, Topic
```

(Merge with the existing `evidence_engine.db.models` import line.)

Replace `_paper_out` and add the topics helper:

```python
def _topics_by_paper(db: Session, paper_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
    if not paper_ids:
        return {}
    rows = db.execute(
        select(PaperTopic.paper_id, Topic.id, Topic.canonical_label)
        .join(Topic, Topic.id == PaperTopic.topic_id)
        .where(PaperTopic.paper_id.in_(paper_ids))
        .order_by(Topic.canonical_label)
    ).all()
    out: dict[uuid.UUID, list[dict]] = {}
    for paper_id, topic_id, label in rows:
        out.setdefault(paper_id, []).append({"id": str(topic_id), "canonical_label": label})
    return out


def _paper_out(row, topics_by_paper: dict) -> dict:
    return {
        "paper": {
            "id": str(row.paper.id),
            "title": row.paper.title,
            "abstract": row.paper.abstract,
            "pub_date": row.paper.pub_date.isoformat() if row.paper.pub_date else None,
        },
        "score": {
            "evidence_tier": row.score.evidence_tier.value,
            "study_type": row.score.study_type.value,
            "final_score": row.score.final_score,
        }
        if row.score
        else None,
        "topics": topics_by_paper.get(row.paper.id, []),
    }
```

Update all three `_paper_out` call sites to build the map first. In `search_endpoint` and `run_saved_search_endpoint`:

```python
    topics_map = _topics_by_paper(db, [row.paper.id for row in result.rows])
    return {
        "rows": [_paper_out(row, topics_map) for row in result.rows],
        ...
    }
```

(In `run_saved_search_endpoint` the result variable is named `page` — same pattern: `topics_map = _topics_by_paper(db, [row.paper.id for row in page.rows])`.)

In `compare_papers_endpoint`:

```python
    topics_map = _topics_by_paper(db, [row.paper.id for row in result.rows])
    return {
        "rows": [_paper_out(row, topics_map) for row in result.rows],
        "unresolved_ids": [str(pid) for pid in result.unresolved_ids],
    }
```

Add the topics list route. **Order matters:** FastAPI matches in declaration order; declare `GET /topics` before `GET /topics/{topic_id}/tier-distribution` in the file to be safe:

```python
@app.get("/topics")
def list_topics_endpoint(db: Session = Depends(get_db)) -> list[dict]:
    topics = db.execute(select(Topic).order_by(Topic.canonical_label)).scalars().all()
    return [{"id": str(t.id), "canonical_label": t.canonical_label} for t in topics]
```

Add `last_run_at` to the saved-search list serialization — in `list_saved_searches_endpoint`, extend the row dict:

```python
    return [
        {
            "id": str(s.id),
            "name": s.name,
            "query_params": s.query_params,
            "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        }
        for s in list_saved_searches(db, user)
    ]
```

- [ ] **Step 4: Run the full webapp test suite**

Run: `.venv/bin/pytest tests/webapp/ -v`
Expected: all PASS — pre-existing `_paper_out` assertions in `test_api.py` don't check for absence of keys, so added keys are backward-compatible. If any pre-existing test asserts exact dict equality, update it to include the new keys.

- [ ] **Step 5: Commit**

```bash
git add webapp/api.py tests/webapp/test_api.py
git commit -m "feat: add GET /topics and enrich paper serialization with topics/abstract/study_type"
```

---

## Task 3: Frontend Scaffold, Theme, Shell & Static Serving

**Files:**
- Create: `webapp/frontend/` (Vite scaffold: `package.json`, `vite.config.ts`, `tsconfig*.json`, `index.html`, `src/main.tsx`, `src/index.css`)
- Create: `webapp/frontend/src/App.tsx`, `src/components/IconSidebar.tsx`
- Create: `webapp/frontend/src/pages/SearchPage.tsx`, `ComparePage.tsx`, `SavedSearchesPage.tsx`, `TopicDetailPage.tsx` (placeholders; filled in Tasks 6–9)
- Create: `webapp/frontend/src/test/setup.ts`
- Test: `webapp/frontend/src/App.test.tsx`
- Modify: `webapp/api.py` (StaticFiles mount), `.gitignore`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: the app shell — `IconSidebar` component, `HashRouter` route table (`/search`, `/compare`, `/saved-searches`, `/topics/:topicId`), Tailwind theme tokens (used as `bg-surface`, `text-on-surface-variant`, `font-serif`, etc. by Tasks 5–9), `npm test` / `npm run build` scripts. Page components at `src/pages/*.tsx` are replaced wholesale by Tasks 6–9.

- [ ] **Step 1: Scaffold the Vite app**

```bash
cd webapp
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install tailwindcss @tailwindcss/vite react-router-dom @tanstack/react-query recharts
npm install -D vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event msw
```

Delete scaffold noise: `src/App.css`, `src/assets/react.svg`, `public/vite.svg` (and their references).

- [ ] **Step 2: Add ignores**

Append to the repo root `.gitignore`:

```
node_modules/
webapp/frontend/dist/
```

- [ ] **Step 3: Configure Vite + Vitest**

Replace `webapp/frontend/vite.config.ts`:

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const apiPaths = ["/search", "/compare", "/saved-searches", "/topics", "/users"];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: Object.fromEntries(apiPaths.map((p) => [p, "http://localhost:8000"])),
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    globals: true,
  },
});
```

In `package.json` scripts, set `"test": "vitest run"`.

In `tsconfig.app.json` `compilerOptions`, add (so `test`/`expect`/`vi` globals and jest-dom matchers type-check under `tsc -b`):

```json
    "types": ["vitest/globals", "@testing-library/jest-dom"]
```

Create `src/test/setup.ts`:

```ts
import "@testing-library/jest-dom";
```

- [ ] **Step 4: Theme tokens and fonts**

Replace `webapp/frontend/src/index.css` (hex values verbatim from `DESIGN.md`; `hairline`/`card-border` from its Elevation section):

```css
@import "tailwindcss";

@theme {
  --color-surface: #f7f9fb;
  --color-surface-container-lowest: #ffffff;
  --color-surface-container-low: #f2f4f6;
  --color-surface-container: #eceef0;
  --color-surface-container-high: #e6e8ea;
  --color-surface-container-highest: #e0e3e5;
  --color-on-surface: #191c1e;
  --color-on-surface-variant: #45464d;
  --color-outline: #76777d;
  --color-outline-variant: #c6c6cd;
  --color-primary: #000000;
  --color-on-primary: #ffffff;
  --color-primary-container: #131b2e;
  --color-on-primary-container: #7c839b;
  --color-secondary: #006a61;
  --color-on-secondary: #ffffff;
  --color-secondary-container: #86f2e4;
  --color-on-secondary-container: #006f66;
  --color-tertiary-container: #0b1c30;
  --color-on-tertiary-container: #75859d;
  --color-error: #ba1a1a;
  --color-hairline: #e2e8f0;
  --font-sans: "Inter", ui-sans-serif, system-ui, sans-serif;
  --font-serif: "Source Serif 4", Georgia, serif;
}

body {
  background-color: var(--color-surface);
  color: var(--color-on-surface);
  font-family: var(--font-sans);
}

.material-symbols-outlined {
  font-variation-settings: "wght" 300;
}
```

Replace `webapp/frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Athena — Research Intelligence</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap"
      rel="stylesheet"
    />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Write the failing shell test**

Create `webapp/frontend/src/App.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import App from "./App";

test("renders icon sidebar with the three nav destinations", () => {
  render(<App />);
  expect(screen.getByLabelText("Search")).toBeInTheDocument();
  expect(screen.getByLabelText("Compare")).toBeInTheDocument();
  expect(screen.getByLabelText("Saved searches")).toBeInTheDocument();
});

test("default route redirects to the search page", () => {
  window.location.hash = "";
  render(<App />);
  expect(screen.getByRole("heading", { name: /search/i })).toBeInTheDocument();
});
```

Run: `cd webapp/frontend && npx vitest run`
Expected: FAIL — `App.tsx` doesn't exist in the required shape yet.

- [ ] **Step 6: Implement the shell**

Create `webapp/frontend/src/components/IconSidebar.tsx`:

```tsx
import { NavLink } from "react-router-dom";

const items = [
  { to: "/search", icon: "search", label: "Search" },
  { to: "/compare", icon: "compare_arrows", label: "Compare" },
  { to: "/saved-searches", icon: "bookmark", label: "Saved searches" },
];

export function IconSidebar() {
  // Per DESIGN.md responsive rules: the sidebar becomes a fixed bottom bar on
  // mobile (< md) so content keeps the full width.
  return (
    <nav className="flex w-14 shrink-0 flex-col items-center gap-1 bg-tertiary-container py-4 max-md:fixed max-md:bottom-0 max-md:z-10 max-md:h-14 max-md:w-full max-md:flex-row max-md:justify-center max-md:py-0">
      <div className="mb-4 flex h-7 w-7 items-center justify-center rounded bg-secondary text-sm font-bold text-on-secondary">
        A
      </div>
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          aria-label={item.label}
          title={item.label}
          className={({ isActive }) =>
            `flex h-9 w-9 items-center justify-center rounded ${
              isActive
                ? "border-l-2 border-secondary-container bg-primary-container text-secondary-container"
                : "text-on-tertiary-container hover:text-secondary-container"
            }`
          }
        >
          <span className="material-symbols-outlined text-[18px]">{item.icon}</span>
        </NavLink>
      ))}
    </nav>
  );
}
```

Create the four placeholder pages, e.g. `webapp/frontend/src/pages/SearchPage.tsx`:

```tsx
export function SearchPage() {
  return <h1 className="text-2xl font-semibold">Search</h1>;
}
```

Same pattern for `ComparePage` ("Compare"), `SavedSearchesPage` ("Saved searches"), `TopicDetailPage` ("Topic detail").

Replace `webapp/frontend/src/App.tsx`:

```tsx
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { IconSidebar } from "./components/IconSidebar";
import { SearchPage } from "./pages/SearchPage";
import { ComparePage } from "./pages/ComparePage";
import { SavedSearchesPage } from "./pages/SavedSearchesPage";
import { TopicDetailPage } from "./pages/TopicDetailPage";

export default function App() {
  return (
    <HashRouter>
      <div className="flex min-h-screen">
        <IconSidebar />
        <main className="mx-auto w-full max-w-[1200px] flex-1 px-12 py-8">
          <Routes>
            <Route path="/" element={<Navigate to="/search" replace />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/compare" element={<ComparePage />} />
            <Route path="/saved-searches" element={<SavedSearchesPage />} />
            <Route path="/topics/:topicId" element={<TopicDetailPage />} />
          </Routes>
        </main>
      </div>
    </HashRouter>
  );
}
```

Ensure `src/main.tsx` renders `<App />` and imports `./index.css` (adjust the scaffold's version if needed).

- [ ] **Step 7: Run tests + build**

Run: `cd webapp/frontend && npx vitest run && npm run build`
Expected: both tests PASS; `dist/` produced without TypeScript errors.

- [ ] **Step 8: Mount static assets in FastAPI**

At the **end** of `webapp/api.py` (after all route declarations — the mount at `/` must be registered last so API routes win):

```python
from pathlib import Path

from fastapi.staticfiles import StaticFiles

_FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
```

(Hash routing means only `/` ever needs `index.html` — no SPA fallback route required.)

Verify: `.venv/bin/pytest tests/webapp/ -q` — all still PASS (the mount is inert when `dist/` is absent and doesn't shadow API routes when present).

- [ ] **Step 9: Commit**

```bash
git add webapp/frontend webapp/api.py .gitignore
git commit -m "feat: scaffold React frontend shell with Scholastic Precision theme and static serving"
```

---

## Task 4: API Client, Types, React Query Hooks & Identity

**Files:**
- Create: `webapp/frontend/src/api/types.ts`, `src/api/client.ts`, `src/api/hooks.ts`
- Create: `webapp/frontend/src/identity/identity.tsx`
- Create: `webapp/frontend/src/test/server.ts` (MSW)
- Modify: `webapp/frontend/src/App.tsx` (wrap providers), `src/test/setup.ts`
- Test: `webapp/frontend/src/api/hooks.test.tsx`, `src/identity/identity.test.tsx`

**Interfaces:**
- Consumes: HTTP shapes from Tasks 1–2 and the pre-existing API (spec section 6 of the web-search-ui spec).
- Produces (used by Tasks 5–9):
  - Types: `TopicRef {id, canonical_label}`, `PaperRow {paper: {id, title, abstract, pub_date}, score: {evidence_tier, study_type, final_score} | null, topics: TopicRef[]}`, `SearchResponse {rows, total, page, page_size}`, `SearchParams {q?, topic_id?, tier?, study_type?, date_from?, date_to?}`, `SavedSearch {id, name, query_params}`, `TierDistribution {established, emerging, speculative}`, `TimelineBucket {bucket_date, event_type, count}`, `TopicCompareRow {topic: TopicRef, consensus: {consensus_text} | null}`.
  - Hooks: `useTopics()`, `useSearch(params: SearchParams)`, `useComparePapers(ids: string[])`, `useCompareTopics(ids: string[])`, `useSavedSearches(userId: string | null)`, `useCreateSavedSearch()`, `useDeleteSavedSearch()`, `useRunSavedSearch()`, `useTierDistribution(topicId: string)`, `useTimeline(topicId: string)`.
  - Identity: `useIdentity() -> {userId: string | null, error: boolean}`; localStorage key `athena_user_id`.
  - `ApiError` with `.status: number`.

- [ ] **Step 1: Write types and client**

Create `src/api/types.ts`:

```ts
export interface TopicRef {
  id: string;
  canonical_label: string;
}

export interface PaperRow {
  paper: { id: string; title: string; abstract: string | null; pub_date: string | null };
  score: { evidence_tier: "established" | "emerging" | "speculative"; study_type: string; final_score: number } | null;
  topics: TopicRef[];
}

export interface SearchResponse {
  rows: PaperRow[];
  total: number;
  page: number;
  page_size: number;
}

export interface SearchParams {
  q?: string;
  topic_id?: string;
  tier?: string;
  study_type?: string;
  date_from?: string;
  date_to?: string;
}

export interface PaperCompareResponse {
  rows: PaperRow[];
  unresolved_ids: string[];
}

export interface TopicCompareRow {
  topic: TopicRef;
  consensus: { consensus_text: string } | null;
}

export interface TopicCompareResponse {
  rows: TopicCompareRow[];
  unresolved_ids: string[];
}

export interface SavedSearch {
  id: string;
  name: string;
  query_params: SearchParams;
  last_run_at?: string | null;
}

export interface TierDistribution {
  established: number;
  emerging: number;
  speculative: number;
}

export interface TimelineBucket {
  bucket_date: string;
  event_type: string;
  count: number;
}
```

Create `src/api/client.ts`:

```ts
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) throw new ApiError(res.status, await res.text());
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function buildUrl(path: string, params?: Record<string, unknown>): string {
  const url = new URL(path, window.location.origin);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === "") continue;
      if (Array.isArray(value)) value.forEach((v) => url.searchParams.append(key, String(v)));
      else url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

export function apiGet<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  return fetch(buildUrl(path, params)).then((r) => handle<T>(r));
}

export function apiPost<T>(path: string, body?: unknown, params?: Record<string, unknown>): Promise<T> {
  return fetch(buildUrl(path, params), {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then((r) => handle<T>(r));
}

export function apiDelete(path: string, params?: Record<string, unknown>): Promise<void> {
  return fetch(buildUrl(path, params), { method: "DELETE" }).then((r) => handle<void>(r));
}
```

- [ ] **Step 2: Write hooks**

Create `src/api/hooks.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDelete, apiGet, apiPost } from "./client";
import type {
  PaperCompareResponse,
  SavedSearch,
  SearchParams,
  SearchResponse,
  TierDistribution,
  TimelineBucket,
  TopicCompareResponse,
  TopicRef,
} from "./types";

export function useTopics() {
  return useQuery({ queryKey: ["topics"], queryFn: () => apiGet<TopicRef[]>("/topics") });
}

export function useSearch(params: SearchParams) {
  return useQuery({
    queryKey: ["search", params],
    queryFn: () => apiGet<SearchResponse>("/search", { ...params, page_size: 50 }),
  });
}

export function useComparePapers(paperIds: string[]) {
  return useQuery({
    queryKey: ["compare-papers", paperIds],
    queryFn: () => apiGet<PaperCompareResponse>("/compare/papers", { paper_ids: paperIds }),
    enabled: paperIds.length > 0,
  });
}

export function useCompareTopics(topicIds: string[]) {
  return useQuery({
    queryKey: ["compare-topics", topicIds],
    queryFn: () => apiGet<TopicCompareResponse>("/compare/topics", { topic_ids: topicIds }),
    enabled: topicIds.length > 0,
  });
}

export function useSavedSearches(userId: string | null) {
  return useQuery({
    queryKey: ["saved-searches", userId],
    queryFn: () => apiGet<SavedSearch[]>("/saved-searches", { user_id: userId }),
    enabled: userId !== null,
  });
}

export function useCreateSavedSearch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { userId: string; name: string; queryParams: SearchParams }) =>
      apiPost<SavedSearch>("/saved-searches", {
        user_id: input.userId,
        name: input.name,
        query_params: input.queryParams,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["saved-searches"] }),
  });
}

export function useDeleteSavedSearch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { userId: string; savedSearchId: string }) =>
      apiDelete(`/saved-searches/${input.savedSearchId}`, { user_id: input.userId }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["saved-searches"] }),
  });
}

export function useRunSavedSearch() {
  return useMutation({
    mutationFn: (input: { userId: string; savedSearchId: string }) =>
      apiPost<SearchResponse>(`/saved-searches/${input.savedSearchId}/run`, undefined, {
        user_id: input.userId,
      }),
  });
}

export function useTierDistribution(topicId: string) {
  return useQuery({
    queryKey: ["tier-distribution", topicId],
    queryFn: () => apiGet<TierDistribution>(`/topics/${topicId}/tier-distribution`),
  });
}

const NINETY_DAYS_MS = 90 * 24 * 60 * 60 * 1000;

export function useTimeline(topicId: string) {
  return useQuery({
    queryKey: ["timeline", topicId],
    queryFn: () =>
      apiGet<TimelineBucket[]>(`/topics/${topicId}/timeline`, {
        window_start: new Date(Date.now() - NINETY_DAYS_MS).toISOString(),
        window_end: new Date().toISOString(),
      }),
  });
}
```

- [ ] **Step 3: Write identity provider**

Create `src/identity/identity.tsx`:

```tsx
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { apiPost } from "../api/client";

const STORAGE_KEY = "athena_user_id";

interface IdentityState {
  userId: string | null;
  error: boolean;
}

const IdentityContext = createContext<IdentityState>({ userId: null, error: false });

export function IdentityProvider({ children }: { children: ReactNode }) {
  const [userId, setUserId] = useState<string | null>(() => localStorage.getItem(STORAGE_KEY));
  const [error, setError] = useState(false);

  useEffect(() => {
    if (userId !== null) return;
    apiPost<{ user_id: string }>("/users/anonymous")
      .then(({ user_id }) => {
        localStorage.setItem(STORAGE_KEY, user_id);
        setUserId(user_id);
      })
      .catch(() => setError(true));
  }, [userId]);

  return <IdentityContext.Provider value={{ userId, error }}>{children}</IdentityContext.Provider>;
}

export function useIdentity(): IdentityState {
  return useContext(IdentityContext);
}
```

- [ ] **Step 4: MSW test server**

Create `src/test/server.ts`:

```ts
import { setupServer } from "msw/node";

export const server = setupServer();
```

Replace `src/test/setup.ts`:

```ts
import "@testing-library/jest-dom";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  localStorage.clear();
});
afterAll(() => server.close());
```

Note: `App.test.tsx` (Task 3) makes no network calls in its current form, but once `App` wraps `IdentityProvider` (Step 6 below) it will POST `/users/anonymous` on render — add a default handler in those tests or pre-seed `localStorage.setItem("athena_user_id", "test-user")` before `render(<App />)`. Update `App.test.tsx` accordingly:

```tsx
beforeEach(() => localStorage.setItem("athena_user_id", "00000000-0000-0000-0000-000000000001"));
```

- [ ] **Step 5: Write the failing tests**

Create `src/identity/identity.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { IdentityProvider, useIdentity } from "./identity";

function Probe() {
  const { userId, error } = useIdentity();
  return <div>{error ? "error" : (userId ?? "loading")}</div>;
}

test("creates an anonymous user on first visit and persists it", async () => {
  server.use(
    http.post("/users/anonymous", () => HttpResponse.json({ user_id: "abc-123" }, { status: 201 })),
  );
  render(
    <IdentityProvider>
      <Probe />
    </IdentityProvider>,
  );
  await waitFor(() => expect(screen.getByText("abc-123")).toBeInTheDocument());
  expect(localStorage.getItem("athena_user_id")).toBe("abc-123");
});

test("reuses a stored user id without calling the API", () => {
  localStorage.setItem("athena_user_id", "stored-id");
  render(
    <IdentityProvider>
      <Probe />
    </IdentityProvider>,
  );
  expect(screen.getByText("stored-id")).toBeInTheDocument();
});

test("reports an error when creation fails", async () => {
  server.use(http.post("/users/anonymous", () => HttpResponse.text("boom", { status: 500 })));
  render(
    <IdentityProvider>
      <Probe />
    </IdentityProvider>,
  );
  await waitFor(() => expect(screen.getByText("error")).toBeInTheDocument());
});
```

Create `src/api/hooks.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { server } from "../test/server";
import { useSearch, useTopics } from "./hooks";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

test("useSearch fetches rows with params", async () => {
  server.use(
    http.get("/search", ({ request }) => {
      const url = new URL(request.url);
      expect(url.searchParams.get("q")).toBe("neural");
      return HttpResponse.json({ rows: [], total: 0, page: 1, page_size: 50 });
    }),
  );
  const { result } = renderHook(() => useSearch({ q: "neural" }), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(result.current.data?.total).toBe(0);
});

test("useTopics fetches the topic list", async () => {
  server.use(
    http.get("/topics", () => HttpResponse.json([{ id: "t1", canonical_label: "Alpha" }])),
  );
  const { result } = renderHook(() => useTopics(), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(result.current.data?.[0].canonical_label).toBe("Alpha");
});
```

For strict TDD, write these two test files FIRST (before Steps 1–3's implementation files), run `npx vitest run` and confirm they FAIL with unresolved imports, then save the Step 1–3 files. Either way, all tests must PASS by Step 7.

- [ ] **Step 6: Wire providers into App**

Modify `src/App.tsx` — wrap the router:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { IdentityProvider } from "./identity/identity";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <IdentityProvider>
        <HashRouter>{/* ...unchanged shell... */}</HashRouter>
      </IdentityProvider>
    </QueryClientProvider>
  );
}
```

(Keep the existing shell JSX unchanged inside `HashRouter`.)

- [ ] **Step 7: Run all frontend tests**

Run: `cd webapp/frontend && npx vitest run && npm run build`
Expected: all PASS, build clean.

- [ ] **Step 8: Commit**

```bash
git add webapp/frontend
git commit -m "feat: add typed API client, React Query hooks, and anonymous identity bootstrap"
```

---

## Task 5: Shared Components (EvidenceIndicator, ResearchCard, TierSection, CompareTray)

**Files:**
- Create: `webapp/frontend/src/components/EvidenceIndicator.tsx`, `ResearchCard.tsx`, `TierSection.tsx`, `CompareTray.tsx`
- Test: `webapp/frontend/src/components/components.test.tsx`

**Interfaces:**
- Consumes: `PaperRow`, `TopicRef` from Task 4's `src/api/types.ts`.
- Produces (used by Tasks 6–9):
  - `EvidenceIndicator({ finalScore: number })` — 5-step bar; filled steps = `Math.max(0, Math.min(5, Math.round(finalScore / 20)))`; `aria-label="Evidence strength N of 5"`.
  - `ResearchCard({ row: PaperRow, checked: boolean, onToggleSelect: (paperId: string) => void })` — checkbox, Inter-bold title, serif abstract excerpt, study-type badge, date, evidence bar, topic links to `/topics/:id`.
  - `TierSection({ title: string, papers: PaperRow[], emptyMessage: string, selectedIds: Set<string>, onToggleSelect: (paperId: string) => void })`.
  - `CompareTray({ count: number, onCompare: () => void })` — renders `null` when `count === 0`.

- [ ] **Step 1: Write the failing tests**

Create `src/components/components.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { PaperRow } from "../api/types";
import { CompareTray } from "./CompareTray";
import { EvidenceIndicator } from "./EvidenceIndicator";
import { ResearchCard } from "./ResearchCard";
import { TierSection } from "./TierSection";

const row: PaperRow = {
  paper: { id: "p1", title: "Neural plasticity study", abstract: "An abstract.", pub_date: "2024-11-02" },
  score: { evidence_tier: "established", study_type: "meta_analysis", final_score: 88 },
  topics: [{ id: "t1", canonical_label: "Cognitive mapping" }],
};

test("EvidenceIndicator maps final_score to filled steps", () => {
  render(<EvidenceIndicator finalScore={88} />);
  expect(screen.getByLabelText("Evidence strength 4 of 5")).toBeInTheDocument();
});

test("ResearchCard shows title, badge, topic link, and toggles selection", () => {
  const onToggle = vi.fn();
  render(
    <MemoryRouter>
      <ResearchCard row={row} checked={false} onToggleSelect={onToggle} />
    </MemoryRouter>,
  );
  expect(screen.getByText("Neural plasticity study")).toBeInTheDocument();
  expect(screen.getByText("meta analysis")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Cognitive mapping" })).toHaveAttribute("href", "/topics/t1");
  fireEvent.click(screen.getByRole("checkbox"));
  expect(onToggle).toHaveBeenCalledWith("p1");
});

test("TierSection shows empty state when no papers", () => {
  render(
    <MemoryRouter>
      <TierSection title="Speculation and hypotheses" papers={[]} emptyMessage="No speculative papers match." selectedIds={new Set()} onToggleSelect={() => {}} />
    </MemoryRouter>,
  );
  expect(screen.getByText("No speculative papers match.")).toBeInTheDocument();
  expect(screen.getByText("0 papers")).toBeInTheDocument();
});

test("CompareTray hides at zero and fires onCompare", () => {
  const onCompare = vi.fn();
  const { rerender } = render(<CompareTray count={0} onCompare={onCompare} />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  rerender(<CompareTray count={2} onCompare={onCompare} />);
  fireEvent.click(screen.getByRole("button", { name: /compare \(2\)/i }));
  expect(onCompare).toHaveBeenCalled();
});
```

(Under `MemoryRouter` the link renders `href="/topics/t1"`; in the real app `HashRouter` produces `#/topics/t1`.)

Run: `cd webapp/frontend && npx vitest run src/components`
Expected: FAIL — components don't exist.

- [ ] **Step 2: Implement the components**

`src/components/EvidenceIndicator.tsx`:

```tsx
export function EvidenceIndicator({ finalScore }: { finalScore: number }) {
  const filled = Math.max(0, Math.min(5, Math.round(finalScore / 20)));
  return (
    <span className="flex gap-0.5" aria-label={`Evidence strength ${filled} of 5`}>
      {Array.from({ length: 5 }, (_, i) => (
        <span
          key={i}
          className={`h-1 w-3.5 rounded ${i < filled ? "bg-secondary" : "bg-surface-container-highest"}`}
        />
      ))}
    </span>
  );
}
```

`src/components/ResearchCard.tsx`:

```tsx
import { Link } from "react-router-dom";
import type { PaperRow } from "../api/types";
import { EvidenceIndicator } from "./EvidenceIndicator";

export function ResearchCard({
  row,
  checked,
  onToggleSelect,
}: {
  row: PaperRow;
  checked: boolean;
  onToggleSelect: (paperId: string) => void;
}) {
  return (
    <div className="mb-2 flex gap-3 rounded-lg border border-hairline bg-surface-container-lowest p-4">
      <input
        type="checkbox"
        checked={checked}
        onChange={() => onToggleSelect(row.paper.id)}
        className="mt-1 h-4 w-4 shrink-0 accent-secondary"
        aria-label={`Select ${row.paper.title}`}
      />
      <div className="min-w-0">
        <p className="mb-1 text-sm font-bold text-primary-container">{row.paper.title}</p>
        {row.paper.abstract && (
          <p className="mb-2 line-clamp-2 font-serif text-sm leading-relaxed text-on-surface-variant">
            {row.paper.abstract}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3 text-xs">
          {row.score && (
            <span className="rounded bg-secondary-container px-1.5 font-semibold text-on-secondary-container">
              {row.score.study_type.replace(/_/g, " ")}
            </span>
          )}
          {row.paper.pub_date && <span className="text-on-surface-variant">{row.paper.pub_date}</span>}
          {row.score && <EvidenceIndicator finalScore={row.score.final_score} />}
          {row.topics.map((topic) => (
            <Link key={topic.id} to={`/topics/${topic.id}`} className="font-semibold text-secondary hover:underline">
              {topic.canonical_label}
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
```

`src/components/TierSection.tsx`:

```tsx
import type { PaperRow } from "../api/types";
import { ResearchCard } from "./ResearchCard";

export function TierSection({
  title,
  papers,
  emptyMessage,
  selectedIds,
  onToggleSelect,
}: {
  title: string;
  papers: PaperRow[];
  emptyMessage: string;
  selectedIds: Set<string>;
  onToggleSelect: (paperId: string) => void;
}) {
  return (
    <section className="mb-4">
      <p className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
        {title}
        <span className="h-px flex-1 bg-hairline" />
        <span className="normal-case tracking-normal">
          {papers.length} paper{papers.length === 1 ? "" : "s"}
        </span>
      </p>
      {papers.length === 0 ? (
        <div className="rounded-lg border border-dashed border-outline-variant px-4 py-2.5 font-serif text-sm text-on-surface-variant">
          {emptyMessage}
        </div>
      ) : (
        papers.map((row) => (
          <ResearchCard key={row.paper.id} row={row} checked={selectedIds.has(row.paper.id)} onToggleSelect={onToggleSelect} />
        ))
      )}
    </section>
  );
}
```

`src/components/CompareTray.tsx`:

```tsx
export function CompareTray({ count, onCompare }: { count: number; onCompare: () => void }) {
  if (count === 0) return null;
  return (
    <button
      onClick={onCompare}
      className="fixed bottom-6 right-8 flex items-center gap-2 rounded bg-primary-container px-4 py-2.5 text-xs font-semibold text-on-primary"
    >
      <span className="material-symbols-outlined text-[15px] text-secondary-container">compare_arrows</span>
      Compare ({count})
      <span className="material-symbols-outlined text-[14px] text-secondary-container">arrow_forward</span>
    </button>
  );
}
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd webapp/frontend && npx vitest run`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add webapp/frontend/src/components
git commit -m "feat: add shared frontend components (evidence bar, research card, tier section, compare tray)"
```

---

## Task 6: Search Page

**Files:**
- Create: `webapp/frontend/src/components/FilterSidebar.tsx`, `src/components/SaveSearchDialog.tsx`
- Replace: `webapp/frontend/src/pages/SearchPage.tsx`
- Test: `webapp/frontend/src/pages/SearchPage.test.tsx`

**Interfaces:**
- Consumes: `useSearch`, `useTopics`, `useCreateSavedSearch`, `useIdentity` (Task 4); `TierSection`, `CompareTray` (Task 5); `SearchParams` (Task 4).
- Produces: the `/search` route reads filters from URL search params (within the hash) — keys: `q`, `topic_id`, `tier`, `study_type`, `date_from`, `date_to`. Task 8's "Run" action navigates here with those params; Task 10's smoke test drives this page.

- [ ] **Step 1: Write the failing tests**

Create `src/pages/SearchPage.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import type { PaperRow } from "../api/types";
import { IdentityProvider } from "../identity/identity";
import { server } from "../test/server";
import { SearchPage } from "./SearchPage";

function makeRow(id: string, title: string, tier: "established" | "emerging" | "speculative" | null): PaperRow {
  return {
    paper: { id, title, abstract: null, pub_date: "2025-01-01" },
    score: tier ? { evidence_tier: tier, study_type: "rct", final_score: 60 } : null,
    topics: [],
  };
}

function renderPage(initialEntry = "/search") {
  localStorage.setItem("athena_user_id", "00000000-0000-0000-0000-000000000001");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IdentityProvider>
        <MemoryRouter initialEntries={[initialEntry]}>
          <SearchPage />
        </MemoryRouter>
      </IdentityProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  server.use(http.get("/topics", () => HttpResponse.json([{ id: "t1", canonical_label: "Cognitive mapping" }])));
});

test("groups results into tier sections including not-yet-scored", async () => {
  server.use(
    http.get("/search", () =>
      HttpResponse.json({
        rows: [makeRow("p1", "Established one", "established"), makeRow("p2", "Pending one", null)],
        total: 2,
        page: 1,
        page_size: 50,
      }),
    ),
  );
  renderPage();
  await waitFor(() => expect(screen.getByText("Established one")).toBeInTheDocument());
  expect(screen.getByText("Established evidence")).toBeInTheDocument();
  expect(screen.getByText("Not yet scored")).toBeInTheDocument();
  expect(screen.getByText("Pending one")).toBeInTheDocument();
  expect(screen.getByText("No emerging papers match the current filters.")).toBeInTheDocument();
});

test("selecting cards shows the compare tray", async () => {
  server.use(
    http.get("/search", () =>
      HttpResponse.json({
        rows: [makeRow("p1", "Paper A", "established"), makeRow("p2", "Paper B", "established")],
        total: 2,
        page: 1,
        page_size: 50,
      }),
    ),
  );
  renderPage();
  await waitFor(() => expect(screen.getByText("Paper A")).toBeInTheDocument());
  fireEvent.click(screen.getByLabelText("Select Paper A"));
  fireEvent.click(screen.getByLabelText("Select Paper B"));
  expect(screen.getByRole("button", { name: /compare \(2\)/i })).toBeInTheDocument();
});

test("save search posts current params with the identity user", async () => {
  let posted: unknown = null;
  server.use(
    http.get("/search", () => HttpResponse.json({ rows: [], total: 0, page: 1, page_size: 50 })),
    http.post("/saved-searches", async ({ request }) => {
      posted = await request.json();
      return HttpResponse.json({ id: "s1", name: "My search", query_params: {} });
    }),
  );
  renderPage("/search?q=neural");
  fireEvent.click(await screen.findByRole("button", { name: /save search/i }));
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "My search" } });
  fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
  await waitFor(() => expect(posted).not.toBeNull());
  expect(posted).toMatchObject({
    user_id: "00000000-0000-0000-0000-000000000001",
    name: "My search",
    query_params: { q: "neural" },
  });
});
```

Run: `cd webapp/frontend && npx vitest run src/pages`
Expected: FAIL.

- [ ] **Step 2: Implement FilterSidebar**

Create `src/components/FilterSidebar.tsx`:

```tsx
import { useState } from "react";
import type { SearchParams } from "../api/types";
import type { TopicRef } from "../api/types";

const TIERS = ["established", "emerging", "speculative"];
const STUDY_TYPES = [
  "meta_analysis",
  "systematic_review",
  "rct",
  "cohort",
  "case_control",
  "case_series",
  "opinion_editorial",
  "unknown",
];

export function FilterSidebar({
  topics,
  value,
  onApply,
}: {
  topics: TopicRef[];
  value: SearchParams;
  onApply: (params: SearchParams) => void;
}) {
  const [draft, setDraft] = useState<SearchParams>(value);

  function set<K extends keyof SearchParams>(key: K, v: SearchParams[K]) {
    setDraft((d) => ({ ...d, [key]: v || undefined }));
  }

  return (
    <aside className="w-52 shrink-0 border-r border-hairline bg-surface-container-lowest p-4">
      <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">Filters</p>

      <label className="mb-1 block text-xs font-medium text-on-surface-variant" htmlFor="filter-topic">Topic</label>
      <select
        id="filter-topic"
        className="mb-3 w-full rounded border border-outline-variant p-1.5 text-xs"
        value={draft.topic_id ?? ""}
        onChange={(e) => set("topic_id", e.target.value)}
      >
        <option value="">All topics</option>
        {topics.map((t) => (
          <option key={t.id} value={t.id}>{t.canonical_label}</option>
        ))}
      </select>

      <label className="mb-1 block text-xs font-medium text-on-surface-variant" htmlFor="filter-tier">Evidence tier</label>
      <select
        id="filter-tier"
        className="mb-3 w-full rounded border border-outline-variant p-1.5 text-xs"
        value={draft.tier ?? ""}
        onChange={(e) => set("tier", e.target.value)}
      >
        <option value="">All tiers</option>
        {TIERS.map((t) => (
          <option key={t} value={t}>{t}</option>
        ))}
      </select>

      <label className="mb-1 block text-xs font-medium text-on-surface-variant" htmlFor="filter-study-type">Study type</label>
      <select
        id="filter-study-type"
        className="mb-3 w-full rounded border border-outline-variant p-1.5 text-xs"
        value={draft.study_type ?? ""}
        onChange={(e) => set("study_type", e.target.value)}
      >
        <option value="">All types</option>
        {STUDY_TYPES.map((t) => (
          <option key={t} value={t}>{t.replace(/_/g, " ")}</option>
        ))}
      </select>

      <label className="mb-1 block text-xs font-medium text-on-surface-variant" htmlFor="filter-date-from">Published after</label>
      <input
        id="filter-date-from"
        type="date"
        className="mb-3 w-full rounded border border-outline-variant p-1.5 text-xs"
        value={draft.date_from ?? ""}
        onChange={(e) => set("date_from", e.target.value)}
      />

      <label className="mb-1 block text-xs font-medium text-on-surface-variant" htmlFor="filter-date-to">Published before</label>
      <input
        id="filter-date-to"
        type="date"
        className="mb-4 w-full rounded border border-outline-variant p-1.5 text-xs"
        value={draft.date_to ?? ""}
        onChange={(e) => set("date_to", e.target.value)}
      />

      <button
        onClick={() => onApply(draft)}
        className="w-full rounded bg-primary-container py-1.5 text-xs font-semibold text-on-primary"
      >
        Apply filters
      </button>
    </aside>
  );
}
```

- [ ] **Step 3: Implement SaveSearchDialog**

Create `src/components/SaveSearchDialog.tsx`:

```tsx
import { useState } from "react";

export function SaveSearchDialog({
  open,
  onSave,
  onClose,
  disabled,
}: {
  open: boolean;
  onSave: (name: string) => void;
  onClose: () => void;
  disabled: boolean;
}) {
  const [name, setName] = useState("");
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-primary-container/40">
      <div className="w-80 rounded-lg border border-hairline bg-surface-container-lowest p-5">
        <p className="mb-3 text-sm font-semibold">Save this search</p>
        <label className="mb-1 block text-xs font-medium text-on-surface-variant" htmlFor="save-search-name">Name</label>
        <input
          id="save-search-name"
          className="mb-4 w-full rounded border border-outline-variant p-1.5 text-sm"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Machine learning in hematology"
        />
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="rounded border border-outline-variant px-3 py-1.5 text-xs font-semibold">
            Cancel
          </button>
          <button
            onClick={() => name.trim() && onSave(name.trim())}
            disabled={disabled || !name.trim()}
            className="rounded bg-secondary px-3 py-1.5 text-xs font-semibold text-on-secondary disabled:opacity-50"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Implement SearchPage**

Replace `src/pages/SearchPage.tsx`:

```tsx
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useCreateSavedSearch, useSearch, useTopics } from "../api/hooks";
import type { SearchParams } from "../api/types";
import { CompareTray } from "../components/CompareTray";
import { FilterSidebar } from "../components/FilterSidebar";
import { SaveSearchDialog } from "../components/SaveSearchDialog";
import { TierSection } from "../components/TierSection";
import { useIdentity } from "../identity/identity";

const PARAM_KEYS = ["q", "topic_id", "tier", "study_type", "date_from", "date_to"] as const;

function paramsFromUrl(searchParams: URLSearchParams): SearchParams {
  const out: SearchParams = {};
  for (const key of PARAM_KEYS) {
    const v = searchParams.get(key);
    if (v) out[key] = v;
  }
  return out;
}

export function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const params = useMemo(() => paramsFromUrl(searchParams), [searchParams]);
  const [queryDraft, setQueryDraft] = useState(params.q ?? "");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [saveOpen, setSaveOpen] = useState(false);
  const navigate = useNavigate();
  const { userId, error: identityError } = useIdentity();

  const { data, isLoading, isError } = useSearch(params);
  const { data: topics } = useTopics();
  const createSavedSearch = useCreateSavedSearch();

  function applyParams(next: SearchParams) {
    const entries = Object.entries(next).filter(([, v]) => v);
    setSearchParams(Object.fromEntries(entries));
    setSelected(new Set());
  }

  function toggleSelect(paperId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(paperId)) next.delete(paperId);
      else next.add(paperId);
      return next;
    });
  }

  const byTier = useMemo(() => {
    const rows = data?.rows ?? [];
    const pick = (tier: string) => rows.filter((r) => r.score?.evidence_tier === tier);
    return {
      established: pick("established"),
      emerging: pick("emerging"),
      speculative: pick("speculative"),
      unscored: rows.filter((r) => r.score === null),
    };
  }, [data]);

  return (
    <div className="flex gap-6">
      <FilterSidebar topics={topics ?? []} value={params} onApply={(p) => applyParams({ ...p, q: params.q })} />
      <div className="min-w-0 flex-1 pb-20">
        <form
          className="mb-5 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            applyParams({ ...params, q: queryDraft || undefined });
          }}
        >
          <input
            className="flex-1 rounded border border-hairline bg-surface-container-lowest px-3 py-2 text-sm"
            placeholder="Search papers"
            value={queryDraft}
            onChange={(e) => setQueryDraft(e.target.value)}
          />
          <button
            type="button"
            onClick={() => setSaveOpen(true)}
            className="flex items-center gap-1.5 rounded border border-outline-variant bg-surface-container-lowest px-3 text-xs font-semibold"
          >
            <span className="material-symbols-outlined text-[15px]">bookmark_add</span>
            Save search
          </button>
        </form>

        {identityError && (
          <p className="mb-4 rounded border border-error/40 bg-surface-container-lowest p-2 text-xs text-error">
            Couldn't set up your anonymous profile — saved searches are unavailable. Search and compare still work.
          </p>
        )}
        {isError && <p className="text-sm text-error">Search failed. Adjust your query and try again.</p>}
        {isLoading && <p className="text-sm text-on-surface-variant">Loading results…</p>}

        {data && (
          <>
            <TierSection title="Established evidence" papers={byTier.established} emptyMessage="No established papers match the current filters." selectedIds={selected} onToggleSelect={toggleSelect} />
            <TierSection title="Emerging evidence" papers={byTier.emerging} emptyMessage="No emerging papers match the current filters." selectedIds={selected} onToggleSelect={toggleSelect} />
            <TierSection title="Speculation and hypotheses" papers={byTier.speculative} emptyMessage="No speculative papers match the current filters." selectedIds={selected} onToggleSelect={toggleSelect} />
            <TierSection title="Not yet scored" papers={byTier.unscored} emptyMessage="All matching papers have been scored." selectedIds={selected} onToggleSelect={toggleSelect} />
          </>
        )}
      </div>

      <CompareTray
        count={selected.size}
        onCompare={() => navigate(`/compare?${[...selected].map((id) => `paper_ids=${id}`).join("&")}`)}
      />
      <SaveSearchDialog
        open={saveOpen}
        disabled={userId === null || createSavedSearch.isPending}
        onClose={() => setSaveOpen(false)}
        onSave={(name) => {
          if (userId === null) return;
          createSavedSearch.mutate(
            { userId, name, queryParams: params },
            { onSuccess: () => setSaveOpen(false) },
          );
        }}
      />
    </div>
  );
}
```

- [ ] **Step 5: Run tests**

Run: `cd webapp/frontend && npx vitest run`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend/src
git commit -m "feat: add search page with tier-grouped results, filters, compare selection, and save-search"
```

---

## Task 7: Compare Page

**Files:**
- Replace: `webapp/frontend/src/pages/ComparePage.tsx`
- Test: `webapp/frontend/src/pages/ComparePage.test.tsx`

**Interfaces:**
- Consumes: `useComparePapers`, `useCompareTopics`, `useTopics` (Task 4); `EvidenceIndicator` (Task 5).
- Produces: `/compare` route reading `paper_ids` (repeated) or `topic_ids` (repeated) query params. Task 9's "Add to compare" navigates here with `topic_ids`.

- [ ] **Step 1: Write the failing tests**

Create `src/pages/ComparePage.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { server } from "../test/server";
import { ComparePage } from "./ComparePage";

function renderAt(url: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <ComparePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("renders side-by-side paper cards with an unresolved notice", async () => {
  server.use(
    http.get("/compare/papers", () =>
      HttpResponse.json({
        rows: [
          {
            paper: { id: "p1", title: "Paper one", abstract: "Abs.", pub_date: "2024-01-01" },
            score: { evidence_tier: "established", study_type: "rct", final_score: 80 },
            topics: [],
          },
        ],
        unresolved_ids: ["dead-beef"],
      }),
    ),
  );
  renderAt("/compare?paper_ids=p1&paper_ids=dead-beef");
  await waitFor(() => expect(screen.getByText("Paper one")).toBeInTheDocument());
  expect(screen.getByText(/1 id\(s\) could not be found/i)).toBeInTheDocument();
});

test("renders topic comparison with consensus text", async () => {
  server.use(
    http.get("/topics", () => HttpResponse.json([])),
    http.get("/compare/topics", () =>
      HttpResponse.json({
        rows: [{ topic: { id: "t1", canonical_label: "Topic one" }, consensus: { consensus_text: "Strong agreement." } }],
        unresolved_ids: [],
      }),
    ),
  );
  renderAt("/compare?topic_ids=t1");
  await waitFor(() => expect(screen.getByText("Topic one")).toBeInTheDocument());
  expect(screen.getByText("Strong agreement.")).toBeInTheDocument();
});

test("shows empty guidance with no selection", () => {
  renderAt("/compare");
  expect(screen.getByText(/select papers from search/i)).toBeInTheDocument();
});
```

Run: `cd webapp/frontend && npx vitest run src/pages/ComparePage.test.tsx`
Expected: FAIL.

- [ ] **Step 2: Implement ComparePage**

Replace `src/pages/ComparePage.tsx`:

```tsx
import { useSearchParams } from "react-router-dom";
import { useComparePapers, useCompareTopics, useTopics } from "../api/hooks";
import { EvidenceIndicator } from "../components/EvidenceIndicator";

function UnresolvedNotice({ ids }: { ids: string[] }) {
  if (ids.length === 0) return null;
  return (
    <p className="mb-4 rounded border border-outline-variant bg-surface-container-low p-2 text-xs text-on-surface-variant">
      {ids.length} id(s) could not be found and were left out of this comparison.
    </p>
  );
}

export function ComparePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const paperIds = searchParams.getAll("paper_ids");
  const topicIds = searchParams.getAll("topic_ids");

  const papers = useComparePapers(paperIds);
  const topicsCompare = useCompareTopics(topicIds);
  const { data: allTopics } = useTopics();

  if (paperIds.length === 0 && topicIds.length === 0) {
    return (
      <div>
        <h1 className="mb-4 text-2xl font-semibold">Compare</h1>
        <p className="font-serif text-sm text-on-surface-variant">
          Select papers from Search using the checkboxes, or add a topic from its detail page, to build a comparison.
        </p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="mb-4 text-2xl font-semibold">Compare</h1>

      {paperIds.length > 0 && (
        <>
          {papers.isLoading && <p className="text-sm text-on-surface-variant">Loading comparison…</p>}
          {papers.data && (
            <>
              <UnresolvedNotice ids={papers.data.unresolved_ids} />
              <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-4">
                {papers.data.rows.map((row) => (
                  <div key={row.paper.id} className="rounded-lg border border-hairline bg-surface-container-lowest p-4">
                    <p className="mb-2 text-sm font-bold text-primary-container">{row.paper.title}</p>
                    {row.paper.pub_date && (
                      <p className="mb-2 text-xs text-on-surface-variant">{row.paper.pub_date}</p>
                    )}
                    {row.score ? (
                      <div className="mb-2 flex items-center gap-2 text-xs">
                        <span className="rounded bg-secondary-container px-1.5 font-semibold text-on-secondary-container">
                          {row.score.evidence_tier}
                        </span>
                        <span>{row.score.study_type.replace(/_/g, " ")}</span>
                        <EvidenceIndicator finalScore={row.score.final_score} />
                      </div>
                    ) : (
                      <p className="mb-2 text-xs text-on-surface-variant">Not yet scored</p>
                    )}
                    {row.paper.abstract && (
                      <p className="font-serif text-sm leading-relaxed text-on-surface-variant">{row.paper.abstract}</p>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}

      {topicIds.length > 0 && (
        <>
          {topicsCompare.isLoading && <p className="text-sm text-on-surface-variant">Loading comparison…</p>}
          {topicsCompare.data && (
            <>
              <UnresolvedNotice ids={topicsCompare.data.unresolved_ids} />
              <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-4">
                {topicsCompare.data.rows.map((row) => (
                  <div key={row.topic.id} className="rounded-lg border border-hairline bg-surface-container-lowest p-4">
                    <p className="mb-2 text-sm font-bold text-primary-container">{row.topic.canonical_label}</p>
                    {row.consensus ? (
                      <p className="font-serif text-sm leading-relaxed text-on-surface-variant">
                        {row.consensus.consensus_text}
                      </p>
                    ) : (
                      <p className="text-xs text-on-surface-variant">No consensus snapshot yet.</p>
                    )}
                  </div>
                ))}
              </div>
              <div className="mt-4">
                <label className="mr-2 text-xs font-medium text-on-surface-variant" htmlFor="add-topic">
                  Add topic
                </label>
                <select
                  id="add-topic"
                  className="rounded border border-outline-variant p-1.5 text-xs"
                  value=""
                  onChange={(e) => {
                    if (!e.target.value) return;
                    const next = new URLSearchParams(searchParams);
                    next.append("topic_ids", e.target.value);
                    setSearchParams(next);
                  }}
                >
                  <option value="">Choose a topic…</option>
                  {(allTopics ?? [])
                    .filter((t) => !topicIds.includes(t.id))
                    .map((t) => (
                      <option key={t.id} value={t.id}>{t.canonical_label}</option>
                    ))}
                </select>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Run tests**

Run: `cd webapp/frontend && npx vitest run`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add webapp/frontend/src/pages
git commit -m "feat: add compare page for side-by-side papers and topics"
```

---

## Task 8: Saved Searches Page

**Files:**
- Replace: `webapp/frontend/src/pages/SavedSearchesPage.tsx`
- Test: `webapp/frontend/src/pages/SavedSearchesPage.test.tsx`

**Interfaces:**
- Consumes: `useSavedSearches`, `useDeleteSavedSearch`, `useRunSavedSearch`, `useIdentity` (Task 4); `SearchParams` (Task 4).
- Produces: "Run" calls `POST /saved-searches/{id}/run` (updates `last_run_at` server-side), then navigates to `/search?<stored params>` so the Search page shows live results.

- [ ] **Step 1: Write the failing tests**

Create `src/pages/SavedSearchesPage.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { IdentityProvider } from "../identity/identity";
import { server } from "../test/server";
import { SavedSearchesPage } from "./SavedSearchesPage";

function renderPage() {
  localStorage.setItem("athena_user_id", "u1");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IdentityProvider>
        <MemoryRouter initialEntries={["/saved-searches"]}>
          <Routes>
            <Route path="/saved-searches" element={<SavedSearchesPage />} />
            <Route path="/search" element={<p>search page target</p>} />
          </Routes>
        </MemoryRouter>
      </IdentityProvider>
    </QueryClientProvider>,
  );
}

const saved = [{ id: "s1", name: "Hematology ML", query_params: { q: "hematology" } }];

test("lists saved searches", async () => {
  server.use(http.get("/saved-searches", () => HttpResponse.json(saved)));
  renderPage();
  await waitFor(() => expect(screen.getByText("Hematology ML")).toBeInTheDocument());
});

test("run posts to the run endpoint then navigates to search with stored params", async () => {
  let ran = false;
  server.use(
    http.get("/saved-searches", () => HttpResponse.json(saved)),
    http.post("/saved-searches/s1/run", () => {
      ran = true;
      return HttpResponse.json({ rows: [], total: 0, page: 1, page_size: 20 });
    }),
  );
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: /run/i }));
  await waitFor(() => expect(screen.getByText("search page target")).toBeInTheDocument());
  expect(ran).toBe(true);
});

test("delete asks for confirmation and calls the API", async () => {
  let deleted = false;
  vi.spyOn(window, "confirm").mockReturnValue(true);
  server.use(
    http.get("/saved-searches", () => HttpResponse.json(saved)),
    http.delete("/saved-searches/s1", () => {
      deleted = true;
      return new HttpResponse(null, { status: 204 });
    }),
  );
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: /delete/i }));
  await waitFor(() => expect(deleted).toBe(true));
});
```

Run: `cd webapp/frontend && npx vitest run src/pages/SavedSearchesPage.test.tsx`
Expected: FAIL.

- [ ] **Step 2: Implement SavedSearchesPage**

Replace `src/pages/SavedSearchesPage.tsx`:

```tsx
import { createSearchParams, useNavigate } from "react-router-dom";
import { useDeleteSavedSearch, useRunSavedSearch, useSavedSearches } from "../api/hooks";
import type { SavedSearch, SearchParams } from "../api/types";
import { useIdentity } from "../identity/identity";

function toUrlParams(params: SearchParams): Record<string, string> {
  return Object.fromEntries(Object.entries(params).filter(([, v]) => v)) as Record<string, string>;
}

export function SavedSearchesPage() {
  const { userId, error: identityError } = useIdentity();
  const { data, isLoading } = useSavedSearches(userId);
  const runSearch = useRunSavedSearch();
  const deleteSearch = useDeleteSavedSearch();
  const navigate = useNavigate();

  function run(saved: SavedSearch) {
    if (userId === null) return;
    runSearch.mutate(
      { userId, savedSearchId: saved.id },
      {
        onSuccess: () =>
          navigate({ pathname: "/search", search: createSearchParams(toUrlParams(saved.query_params)).toString() }),
      },
    );
  }

  function remove(saved: SavedSearch) {
    if (userId === null) return;
    if (!window.confirm(`Delete "${saved.name}"?`)) return;
    deleteSearch.mutate({ userId, savedSearchId: saved.id });
  }

  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold">Saved searches</h1>
      <p className="mb-6 font-serif text-sm text-on-surface-variant">
        Re-run a saved query against current data, or remove ones you no longer need.
      </p>

      {identityError && (
        <p className="mb-4 rounded border border-error/40 bg-surface-container-lowest p-2 text-xs text-error">
          Couldn't set up your anonymous profile — saved searches are unavailable.
        </p>
      )}
      {isLoading && userId !== null && <p className="text-sm text-on-surface-variant">Loading…</p>}
      {data?.length === 0 && (
        <p className="rounded-lg border border-dashed border-outline-variant p-4 font-serif text-sm text-on-surface-variant">
          Nothing saved yet — run a search and use "Save search" to keep it here.
        </p>
      )}

      {(data ?? []).map((saved) => (
        <div
          key={saved.id}
          className="mb-2 flex items-center justify-between rounded-lg border border-hairline bg-surface-container-lowest p-4"
        >
          <div>
            <p className="text-sm font-bold text-primary-container">{saved.name}</p>
            <p className="text-xs text-on-surface-variant">
              {Object.entries(saved.query_params)
                .filter(([, v]) => v)
                .map(([k, v]) => `${k}: ${v}`)
                .join(" · ") || "No filters"}
            </p>
            <p className="text-xs text-on-surface-variant">
              {saved.last_run_at ? `Last run ${saved.last_run_at.slice(0, 10)}` : "Never run"}
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => run(saved)}
              className="rounded bg-secondary px-3 py-1.5 text-xs font-semibold text-on-secondary"
            >
              Run
            </button>
            <button
              onClick={() => remove(saved)}
              className="rounded border border-outline-variant px-3 py-1.5 text-xs font-semibold text-on-surface-variant"
            >
              Delete
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Run tests**

Run: `cd webapp/frontend && npx vitest run`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add webapp/frontend/src/pages
git commit -m "feat: add saved searches page with run and delete actions"
```

---

## Task 9: Topic Detail Page

**Files:**
- Replace: `webapp/frontend/src/pages/TopicDetailPage.tsx`
- Test: `webapp/frontend/src/pages/TopicDetailPage.test.tsx`

**Interfaces:**
- Consumes: `useTierDistribution`, `useTimeline`, `useSearch`, `useTopics` (Task 4); Recharts (`BarChart`, `Bar`, `XAxis`, `YAxis`, `Tooltip`, `ResponsiveContainer`).
- Produces: `/topics/:topicId` route; "Add to compare" navigates to `/compare?topic_ids=<topicId>`.

- [ ] **Step 1: Write the failing tests**

Create `src/pages/TopicDetailPage.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { server } from "../test/server";
import { TopicDetailPage } from "./TopicDetailPage";

function renderPage(topicId = "t1") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/topics/${topicId}`]}>
        <Routes>
          <Route path="/topics/:topicId" element={<TopicDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  server.use(
    http.get("/topics", () => HttpResponse.json([{ id: "t1", canonical_label: "Cognitive mapping" }])),
    http.get("/topics/t1/tier-distribution", () =>
      HttpResponse.json({ established: 3, emerging: 2, speculative: 1 }),
    ),
    http.get("/topics/t1/timeline", () =>
      HttpResponse.json([{ bucket_date: "2026-06-01", event_type: "new_paper", count: 2 }]),
    ),
    http.get("/search", () =>
      HttpResponse.json({
        rows: [
          {
            paper: { id: "p1", title: "Topic paper", abstract: null, pub_date: "2026-05-01" },
            score: { evidence_tier: "established", study_type: "rct", final_score: 70 },
            topics: [{ id: "t1", canonical_label: "Cognitive mapping" }],
          },
        ],
        total: 1,
        page: 1,
        page_size: 50,
      }),
    ),
  );
});

test("shows topic name, charts sections, and papers table", async () => {
  renderPage();
  await waitFor(() => expect(screen.getByText("Cognitive mapping")).toBeInTheDocument());
  expect(screen.getByText("Evidence tier distribution")).toBeInTheDocument();
  expect(screen.getByText("Change timeline (90 days)")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText("Topic paper")).toBeInTheDocument());
});

test("shows a not-found message when tier distribution 404s", async () => {
  server.use(http.get("/topics/t1/tier-distribution", () => HttpResponse.text("not found", { status: 404 })));
  renderPage();
  await waitFor(() => expect(screen.getByText(/topic not found/i)).toBeInTheDocument());
});

test("add to compare links to the compare page with this topic", async () => {
  renderPage();
  const link = await screen.findByRole("link", { name: /add to compare/i });
  expect(link).toHaveAttribute("href", "/compare?topic_ids=t1");
});
```

Note: Recharts renders SVG with zero dimensions under jsdom — tests assert section headings and table content, not chart internals. That's expected.

Run: `cd webapp/frontend && npx vitest run src/pages/TopicDetailPage.test.tsx`
Expected: FAIL.

- [ ] **Step 2: Implement TopicDetailPage**

Replace `src/pages/TopicDetailPage.tsx`:

```tsx
import { Link, useParams } from "react-router-dom";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useSearch, useTierDistribution, useTimeline, useTopics } from "../api/hooks";
import { ApiError } from "../api/client";

const TEAL = "#006a61";
const NAVY = "#131b2e";

export function TopicDetailPage() {
  const { topicId } = useParams<{ topicId: string }>();
  const id = topicId ?? "";
  const { data: topics } = useTopics();
  const distribution = useTierDistribution(id);
  const timeline = useTimeline(id);
  const papers = useSearch({ topic_id: id });

  const topicName = topics?.find((t) => t.id === id)?.canonical_label ?? "Topic";

  if (distribution.error instanceof ApiError && distribution.error.status === 404) {
    return <p className="text-sm text-on-surface-variant">Topic not found.</p>;
  }

  const distData = distribution.data
    ? [
        { tier: "Established", count: distribution.data.established },
        { tier: "Emerging", count: distribution.data.emerging },
        { tier: "Speculative", count: distribution.data.speculative },
      ]
    : [];

  const timelineByDay = (timeline.data ?? []).reduce<Record<string, Record<string, number | string>>>(
    (acc, bucket) => {
      acc[bucket.bucket_date] ??= { bucket_date: bucket.bucket_date };
      acc[bucket.bucket_date][bucket.event_type] = bucket.count;
      return acc;
    },
    {},
  );
  const timelineData = Object.values(timelineByDay);
  const eventTypes = [...new Set((timeline.data ?? []).map((b) => b.event_type))];

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{topicName}</h1>
        <Link
          to={`/compare?topic_ids=${id}`}
          className="flex items-center gap-1.5 rounded border border-outline-variant bg-surface-container-lowest px-3 py-1.5 text-xs font-semibold"
        >
          <span className="material-symbols-outlined text-[15px]">compare_arrows</span>
          Add to compare
        </Link>
      </div>

      <div className="mb-8 grid grid-cols-[repeat(auto-fit,minmax(320px,1fr))] gap-4">
        <div className="rounded-lg border border-hairline bg-surface-container-lowest p-4">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
            Evidence tier distribution
          </p>
          <div style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={distData}>
                <XAxis dataKey="tier" tick={{ fontSize: 12 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="count" fill={TEAL} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-lg border border-hairline bg-surface-container-lowest p-4">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
            Change timeline (90 days)
          </p>
          <div style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={timelineData}>
                <XAxis dataKey="bucket_date" tick={{ fontSize: 11 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                <Tooltip />
                {eventTypes.map((eventType, i) => (
                  <Bar key={eventType} dataKey={eventType} stackId="events" fill={i % 2 === 0 ? TEAL : NAVY} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">Papers</p>
      <div className="overflow-hidden rounded-lg border border-hairline bg-surface-container-lowest">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-hairline text-left text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
              <th className="p-3">Title</th>
              <th className="p-3">Tier</th>
              <th className="p-3">Study type</th>
              <th className="p-3">Published</th>
            </tr>
          </thead>
          <tbody>
            {(papers.data?.rows ?? []).map((row) => (
              <tr key={row.paper.id} className="border-b border-surface-container-low">
                <td className="p-3 font-medium text-primary-container">{row.paper.title}</td>
                <td className="p-3">{row.score?.evidence_tier ?? "pending"}</td>
                <td className="p-3">{row.score?.study_type.replace(/_/g, " ") ?? "—"}</td>
                <td className="p-3">{row.paper.pub_date ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {papers.data?.rows.length === 0 && (
          <p className="p-4 font-serif text-sm text-on-surface-variant">No papers for this topic yet.</p>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Run tests + build**

Run: `cd webapp/frontend && npx vitest run && npm run build`
Expected: all PASS, build clean.

- [ ] **Step 4: Commit**

```bash
git add webapp/frontend/src/pages
git commit -m "feat: add topic detail page with tier and timeline charts"
```

---

## Task 10: Playwright Smoke Test + Demo Seed

**Files:**
- Create: `scripts/seed_demo_data.py`
- Create: `webapp/frontend/playwright.config.ts`, `webapp/frontend/e2e/smoke.spec.ts`
- Modify: `webapp/frontend/package.json` (add `e2e` script), `.gitignore` (playwright artifacts)

**Interfaces:**
- Consumes: everything — the built frontend, the real FastAPI app, real Postgres.
- Produces: `npm run e2e` — the spec's golden-path verification (anonymous user → search → select two papers → compare → save search → run it).

- [ ] **Step 1: Write the seed script**

Create `scripts/seed_demo_data.py` (mirrors the fixture style of `tests/webapp/test_api.py::_seed_paper`; idempotent via the topic label):

```python
"""Seed a demo topic with papers for local dev and the e2e smoke test."""

from datetime import date, datetime

from sqlalchemy import select

from evidence_engine.db.models import (
    ChangeEvent,
    ChangeEventType,
    EvidenceTier,
    Paper,
    PaperTopic,
    Score,
    StudyType,
    Topic,
)
from evidence_engine.db.session import SessionLocal
from webapp.search_index import sync_search_index

DEMO_TOPIC = "Demo: AI and Cognitive Mapping"

PAPERS = [
    ("Longitudinal analysis of neural plasticity under AI assistance", EvidenceTier.ESTABLISHED, StudyType.META_ANALYSIS, 88.0),
    ("Cognitive offloading and digital tool interaction: a systematic review", EvidenceTier.ESTABLISHED, StudyType.SYSTEMATIC_REVIEW, 76.0),
    ("Cross-cultural variance in generative AI adaptation", EvidenceTier.EMERGING, StudyType.RCT, 44.0),
    ("Attention residue in multi-agent workflows: a hypothesis", EvidenceTier.SPECULATIVE, StudyType.OPINION_EDITORIAL, 12.0),
]


def main() -> None:
    session = SessionLocal()
    try:
        existing = session.execute(select(Topic).where(Topic.canonical_label == DEMO_TOPIC)).scalar_one_or_none()
        if existing is not None:
            print(f"Demo topic already seeded ({existing.id}); nothing to do.")
            return

        topic = Topic(canonical_label=DEMO_TOPIC, mesh_id="D_DEMO_01")
        session.add(topic)
        session.flush()

        for i, (title, tier, study_type, score) in enumerate(PAPERS):
            paper = Paper(
                title=title,
                abstract=f"Demo abstract for: {title}.",
                pub_date=date(2026, 1 + i, 15),
            )
            session.add(paper)
            session.flush()
            session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
            session.add(
                Score(paper_id=paper.id, evidence_tier=tier, study_type=study_type, final_score=score, model_version="demo")
            )
            session.add(
                ChangeEvent(
                    topic_id=topic.id,
                    paper_id=paper.id,
                    event_type=ChangeEventType.NEW_PAPER,
                    detected_at=datetime(2026, 1 + i, 16),
                )
            )
        session.flush()
        sync_search_index(session)
        session.commit()
        print(f"Seeded demo topic {topic.id} with {len(PAPERS)} papers.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
```

Run: `.venv/bin/python scripts/seed_demo_data.py`
Expected: `Seeded demo topic <uuid> with 4 papers.` (second run: "nothing to do").

Check the `Score` constructor kwargs against `evidence_engine/db/models.py` — if `Score` has required fields beyond these (e.g. component scores), copy the minimal-valid construction used by `tests/webapp/test_api.py::_seed_paper` exactly.

- [ ] **Step 2: Install and configure Playwright**

```bash
cd webapp/frontend
npm install -D @playwright/test
npx playwright install chromium
```

Create `webapp/frontend/playwright.config.ts`:

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://localhost:8123" },
  webServer: {
    command: "cd ../.. && .venv/bin/uvicorn webapp.api:app --port 8123",
    url: "http://localhost:8123/topics",
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
```

Add to `package.json` scripts: `"e2e": "playwright test"`.

Append to the repo root `.gitignore`:

```
webapp/frontend/test-results/
webapp/frontend/playwright-report/
```

Exclude Playwright specs from Vitest — in `vite.config.ts`'s `test` block add:

```ts
    exclude: ["e2e/**", "node_modules/**"],
```

- [ ] **Step 3: Write the smoke test**

Create `webapp/frontend/e2e/smoke.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test("golden path: search → compare → save → run", async ({ page }) => {
  await page.goto("/#/search");

  await page.getByPlaceholder("Search papers").fill("neural plasticity");
  await page.getByPlaceholder("Search papers").press("Enter");

  await expect(page.getByText("Longitudinal analysis of neural plasticity under AI assistance")).toBeVisible();
  await expect(page.getByText("Established evidence")).toBeVisible();

  await page.goto("/#/search");
  await expect(page.getByText("Established evidence")).toBeVisible();
  await page.getByLabel(/Select Longitudinal analysis/).check();
  await page.getByLabel(/Select Cognitive offloading/).check();
  await page.getByRole("button", { name: /compare \(2\)/i }).click();

  await expect(page).toHaveURL(/#\/compare\?paper_ids=/);
  await expect(page.getByText("Longitudinal analysis of neural plasticity under AI assistance")).toBeVisible();
  await expect(page.getByText("Cognitive offloading and digital tool interaction: a systematic review")).toBeVisible();

  await page.goto("/#/search?q=cognitive");
  await expect(page.getByText("Established evidence")).toBeVisible();
  await page.getByRole("button", { name: /save search/i }).click();
  await page.getByLabel("Name").fill("Smoke test search");
  await page.getByRole("button", { name: /^save$/i }).click();

  await page.goto("/#/saved-searches");
  await expect(page.getByText("Smoke test search")).toBeVisible();
  await page.getByRole("button", { name: /run/i }).first().click();
  await expect(page).toHaveURL(/#\/search\?/);
  await expect(page.getByText("Established evidence")).toBeVisible();
});
```

- [ ] **Step 4: Build, seed, run**

```bash
cd webapp/frontend && npm run build
cd ../.. && .venv/bin/python scripts/seed_demo_data.py
cd webapp/frontend && npm run e2e
```

Expected: 1 passed. Debug selector drift with `npx playwright test --ui` if needed — the page markup is authoritative, adjust selectors, not features.

- [ ] **Step 5: Run everything**

```bash
.venv/bin/pytest -q
cd webapp/frontend && npx vitest run && npm run e2e
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/seed_demo_data.py webapp/frontend .gitignore
git commit -m "test: add Playwright golden-path smoke test with demo seed script"
```
