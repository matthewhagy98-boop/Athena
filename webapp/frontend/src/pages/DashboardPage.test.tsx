import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
