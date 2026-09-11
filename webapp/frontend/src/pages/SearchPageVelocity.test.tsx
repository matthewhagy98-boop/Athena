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
  const none = (_id: string) => ({
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
