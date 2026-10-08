import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import type { ActivityResponse, ChangeFeedResponse, PersonalDashboardResponse } from "../api/types";
import { IdentityProvider } from "../identity/identity";
import { server } from "../test/server";
import { DashboardPage } from "./DashboardPage";

const EMPTY_ACTIVITY: ActivityResponse = {
  computed_at: null,
  window_start: null,
  window_end: null,
  topics: [],
};
const EMPTY_CHANGES: ChangeFeedResponse = { days: [], total_events: 0 };
const NO_PROFILE: PersonalDashboardResponse = {
  has_profile: false,
  computed_at: null,
  window_start: null,
  window_end: null,
  topics: [],
  blurb: null,
};

function handlers({
  activity = EMPTY_ACTIVITY,
  changes = EMPTY_CHANGES,
  personal = NO_PROFILE,
}: {
  activity?: ActivityResponse;
  changes?: ChangeFeedResponse;
  personal?: PersonalDashboardResponse;
} = {}) {
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
  // G-C-1, and the assertion has to survive the personal query RESOLVING. Waiting on the
  // activity heading is not enough -- it renders on first paint, so the absence check ran
  // before the personal response arrived and passed even with the has_profile gate
  // deleted entirely. That is the same racing shape already fixed twice in this file; it
  // survived here a third time, in the one test named for the constraint.
  let personalResolved = 0;
  server.use(
    http.get("/dashboard/activity", () => HttpResponse.json(EMPTY_ACTIVITY)),
    http.get("/dashboard/changes", () => HttpResponse.json(EMPTY_CHANGES)),
    http.get("/dashboard/personal", () => {
      personalResolved += 1;
      return HttpResponse.json(NO_PROFILE);
    }),
  );
  renderPage();

  await waitFor(() => expect(personalResolved).toBe(1));
  // Let react-query commit the resolved state before asserting what is NOT on screen.
  await waitFor(() =>
    expect(screen.getByText(/no topic reached the activity threshold/i)).toBeInTheDocument(),
  );
  await new Promise((resolve) => setTimeout(resolve, 50));

  expect(screen.queryByText(/your topics/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/couldn't load/i)).not.toBeInTheDocument();
});

test("the interest topic picker is present even with no profile", async () => {
  // Task 11: the picker is the only route from no profile to having one, so it must not
  // be gated behind has_profile the way PersonalTopicsWidget is -- otherwise the personal
  // dashboard stays exactly as unreachable as it is without it.
  handlers();
  renderPage();

  await waitFor(() => expect(screen.getByText(/most active topics/i)).toBeInTheDocument());
  expect(screen.getByLabelText(/add a topic to follow/i)).toBeInTheDocument();
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

test("removing a topic calls the API with that topic's id and the current user's id", async () => {
  let deletedPath: string | null = null;
  let deletedUserId: string | null = null;
  server.use(
    http.get("/dashboard/activity", () => HttpResponse.json(EMPTY_ACTIVITY)),
    http.get("/dashboard/changes", () => HttpResponse.json(EMPTY_CHANGES)),
    http.get("/dashboard/personal", () =>
      HttpResponse.json({
        ...NO_PROFILE,
        has_profile: true,
        topics: [
          {
            topic: { id: "t1", canonical_label: "Atrial fibrillation" },
            event_count: 0,
            breakdown: { new_paper: 0, consensus_updated: 0, contradiction_flagged: 0, paper_retracted: 0 },
            latest_event_at: null,
          },
        ],
      }),
    ),
    http.delete("/interests/:topicId", ({ params, request }) => {
      deletedPath = params.topicId as string;
      deletedUserId = new URL(request.url).searchParams.get("user_id");
      return new HttpResponse(null, { status: 204 });
    }),
  );
  renderPage();

  const removeButton = await screen.findByRole("button", { name: /remove atrial fibrillation/i });
  fireEvent.click(removeButton);

  await waitFor(() => expect(deletedPath).toBe("t1"));
  expect(deletedUserId).toBe("00000000-0000-0000-0000-000000000001");
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

// 48 hours versus fresh brackets the threshold so loosely that ANY value between roughly
// 1 and 47 satisfies both -- confirmed by mutation. FR-C-011 specifies 36, and that number
// is the entire content of this component, so it is pinned from both sides.
test("35 hours old is not yet stale", async () => {
  handlers({
    activity: { ...EMPTY_ACTIVITY, computed_at: new Date(Date.now() - 35 * 3_600_000).toISOString() },
  });
  renderPage();

  // Waits for the ACTIVITY DATA, not the heading. The heading renders while the query is
  // still in flight, so asserting the banner's absence after it races the fetch and
  // passes for any threshold. This line only renders once data has arrived.
  await waitFor(() =>
    expect(screen.getByText(/no topic reached the activity threshold/i)).toBeInTheDocument(),
  );
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

test("37 hours old is stale", async () => {
  handlers({
    activity: { ...EMPTY_ACTIVITY, computed_at: new Date(Date.now() - 37 * 3_600_000).toISOString() },
  });
  renderPage();

  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/data as of/i));
});

test("no staleness banner for fresh data", async () => {
  handlers({ activity: { ...EMPTY_ACTIVITY, computed_at: new Date().toISOString() } });
  renderPage();

  // Waits for the ACTIVITY DATA, not the heading. The heading renders while the query is
  // still in flight, so asserting the banner's absence after it races the fetch and
  // passes for any threshold. This line only renders once data has arrived.
  await waitFor(() =>
    expect(screen.getByText(/no topic reached the activity threshold/i)).toBeInTheDocument(),
  );
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


test("no staleness banner when computed_at is null", async () => {
  // Six tests in this file use computed_at: null and none asserted the banner's absence,
  // so removing StalenessBanner's `if (!computedAt) return null` guard passed all of
  // them. new Date(null).getTime() is 0, not NaN, so the age computes as decades and the
  // banner would render unconditionally on every cold-start dashboard.
  handlers();
  renderPage();

  await waitFor(() =>
    expect(screen.getByText(/no topic reached the activity threshold/i)).toBeInTheDocument(),
  );
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

test("just under 36 hours old is not yet stale", async () => {
  // Named for what it actually checks. An earlier version of this test was called
  // "exactly 36 hours" and used 36h-minus-2s, so it never touched the boundary and the
  // `<=` -> `<` mutation survived it. The true instant cannot be hit without freezing the
  // clock, because wall time advances between building the fixture and the component
  // reading Date.now(). That exact-instant case is deliberately left unpinned: the window
  // is sub-second on a 36-hour threshold, so no user outcome turns on it -- unlike the
  // threshold VALUE, which 35h/37h do pin.
  handlers({
    activity: {
      ...EMPTY_ACTIVITY,
      computed_at: new Date(Date.now() - 36 * 3_600_000 + 2_000).toISOString(),
    },
  });
  renderPage();

  await waitFor(() =>
    expect(screen.getByText(/no topic reached the activity threshold/i)).toBeInTheDocument(),
  );
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

test("the day heading is rendered in UTC, not the viewer's zone", async () => {
  // day.date is a calendar date the backend already grouped in UTC. Letting the browser
  // reinterpret it locally files events under the previous day for anyone west of UTC --
  // the same class of bug the Z suffix guards against on the backend. Nothing asserted
  // the rendered heading at all, so deleting timeZone: "UTC" passed the whole suite.
  handlers({
    changes: {
      days: [
        {
          date: "2026-08-01",
          events: [
            {
              event_type: "consensus_updated",
              detected_at: "2026-08-01T02:00:00Z",
              topic: { id: "t1", canonical_label: "Atrial fibrillation" },
              paper: null,
              evidence_tier: null,
            },
          ],
        },
      ],
      total_events: 1,
    },
  });
  renderPage();

  // Expectation computed the same way, but pinned to UTC -- so the assertion is
  // locale-agnostic while still catching the drop. On a machine at any negative offset,
  // a component without timeZone: "UTC" renders the PREVIOUS day and this fails.
  const expected = new Date("2026-08-01T00:00:00Z").toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
  await waitFor(() => expect(screen.getByText(expected)).toBeInTheDocument());
});

test("a contradiction is visually distinguished, like a retraction", async () => {
  // WARNING_TYPES holds both, and the comment calls them jointly "the highest-signal
  // events", but only the retraction half was tested -- dropping contradiction_flagged
  // from the set passed everything.
  handlers({
    changes: {
      days: [
        {
          date: "2026-08-01",
          events: [
            {
              event_type: "contradiction_flagged",
              detected_at: "2026-08-01T06:00:00Z",
              topic: { id: "t1", canonical_label: "Atrial fibrillation" },
              paper: { id: "p1", title: "Conflicting cohort" },
              evidence_tier: null,
            },
          ],
        },
      ],
      total_events: 1,
    },
  });
  renderPage();

  await waitFor(() => expect(screen.getByText("Contradiction flagged")).toBeInTheDocument());
  expect(screen.getByText("Contradiction flagged").className).toContain("text-error");
});


test("FR-C-012: change-feed and personal-topic rows reach a real destination", async () => {
  // The requirement is "the dashboard must add no dead ends", and it was enforced on one
  // of three surfaces. Replacing the <Link> with a <span> in ChangeFeedWidget, and again
  // in PersonalTopicsWidget, left all 145 tests passing -- because several tests assert
  // getByText on those rows, and the text is unchanged when the anchor disappears. Both
  // files carry a comment citing FR-C-012 above the link they did not test.
  //
  // Asserting the ROLE rather than the text is the whole point: only a real anchor has
  // role="link", and only an anchor carries href.
  server.use(
    http.get("/dashboard/changes", () =>
      HttpResponse.json({
        total_events: 1,
        days: [
          {
            date: "2026-09-19",
            events: [
              {
                id: "e1",
                event_type: "new_paper",
                detected_at: "2026-09-19T10:00:00Z",
                topic: { id: "t9", canonical_label: "GLP-1 receptor agonists" },
                paper: { id: "p1", title: "A paper", evidence_tier: "established" },
              },
            ],
          },
        ],
      }),
    ),
    http.get("/dashboard/personal", () =>
      HttpResponse.json({
        has_profile: true,
        computed_at: "2026-09-20T00:00:00Z",
        window_start: "2026-09-13T00:00:00Z",
        window_end: "2026-09-20T00:00:00Z",
        blurb: "1 new paper across your 1 topic this week.",
        topics: [
          {
            topic: { id: "t1", canonical_label: "Atrial fibrillation" },
            event_count: 1,
            breakdown: {
              new_paper: 1,
              consensus_updated: 0,
              contradiction_flagged: 0,
              paper_retracted: 0,
            },
            latest_event_at: "2026-09-19T10:00:00Z",
          },
        ],
      }),
    ),
  );
  renderPage();

  const feedLink = await screen.findByRole("link", { name: /glp-1 receptor agonists/i });
  // Suffix rather than exact: these tests use MemoryRouter while production uses
  // HashRouter, so the prefix differs ("/topics/t9" vs "#/topics/t9"). What matters is
  // that it is a real anchor pointing at that topic.
  expect(feedLink.getAttribute("href")).toMatch(/\/topics\/t9$/);

  const topicLink = await screen.findByRole("link", { name: /atrial fibrillation/i });
  expect(topicLink.getAttribute("href")).toMatch(/\/topics\/t1$/);
});


test("a failing personal request shows the error, rather than the panel vanishing", async () => {
  // PersonalTopicsWidget mounted only on `personal.data?.has_profile`, which requires
  // success -- so its isError branch was dead code. A user who HAS a profile and whose
  // request fails saw their topic list silently disappear while the other two panels
  // rendered fine, which is the exact failure the per-widget error surfaces prevent.
  // The only existing one-endpoint-fails test fails /dashboard/activity.
  server.use(http.get("/dashboard/personal", () => new HttpResponse(null, { status: 500 })));
  renderPage();

  await waitFor(() =>
    expect(screen.getByText(/couldn't load your topics/i)).toBeInTheDocument(),
  );
  // ...and the rest of the dashboard is genuinely unaffected.
  expect(screen.queryByText(/couldn't load topic activity/i)).not.toBeInTheDocument();
});


test("the change feed's empty state says no change rather than no results (FR-C-015)", async () => {
  // EMPTY_CHANGES is the default fixture here and in src/test/server.ts, so almost every
  // test in this file renders this branch -- and none asserted it produced anything.
  // Deleting the paragraph entirely left all 145 tests passing.
  renderPage();

  await waitFor(() =>
    expect(screen.getByText(/no change recorded in this period/i)).toBeInTheDocument(),
  );
  // DashboardPage renders standalone here, with no <main> wrapper.
  expect(document.body.textContent).not.toMatch(/no results|nothing found/i);
});


test("the personal request is not fired before identity exists", async () => {
  // `enabled: Boolean(userId)` in usePersonalDashboard. Deleting it fires
  // /dashboard/personal?user_id=null, which 422s -- turning the ordinary pre-identity
  // render into an error state, which is exactly what the code comment says the guard is
  // there to prevent. Nothing tested it.
  const seen: string[] = [];
  server.use(
    http.get("/dashboard/personal", ({ request }) => {
      seen.push(new URL(request.url).searchParams.get("user_id") ?? "<absent>");
      return HttpResponse.json(NO_PROFILE);
    }),
    http.post("/users/anonymous", () => new Promise(() => {})),  // identity never arrives
  );
  // renderPage() seeds identity into localStorage, which is the whole thing under test
  // here, so this case renders without it.
  localStorage.removeItem("athena_user_id");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <IdentityProvider>
        <MemoryRouter initialEntries={["/dashboard"]}>
          <DashboardPage />
        </MemoryRouter>
      </IdentityProvider>
    </QueryClientProvider>,
  );

  await waitFor(() => expect(screen.getByText(/most active topics/i)).toBeInTheDocument());

  expect(seen).toEqual([]);
});
