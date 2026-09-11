import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { server } from "../test/server";
import { SavedSearchVelocityTrend } from "./SavedSearchVelocityTrend";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

test("states coverage rather than drawing a misleading line", async () => {
  server.use(
    http.get("/saved-searches/s1/velocity", () =>
      HttpResponse.json({
        status: "insufficient_coverage",
        papers_total: 40,
        papers_with_history: 3,
        series: [],
        computed_at: new Date().toISOString(),
      }),
    ),
  );

  render(<SavedSearchVelocityTrend savedSearchId="s1" userId="u1" />, { wrapper });

  await waitFor(() => expect(screen.getByText(/3 of 40/i)).toBeInTheDocument());
});

test("renders the trend when coverage is sufficient", async () => {
  server.use(
    http.get("/saved-searches/s2/velocity", () =>
      HttpResponse.json({
        status: "ready",
        papers_total: 40,
        papers_with_history: 28,
        series: [
          { week_start: "2026-05-11", median_velocity_per_30d: 3.5 },
          { week_start: "2026-05-18", median_velocity_per_30d: 4.0 },
          { week_start: "2026-05-25", median_velocity_per_30d: 4.5 },
        ],
        computed_at: new Date().toISOString(),
      }),
    ),
  );

  render(<SavedSearchVelocityTrend savedSearchId="s2" userId="u1" />, { wrapper });

  await waitFor(() => expect(screen.getByText(/median/i)).toBeInTheDocument());
});

// Guards FR-D-012 / citations/aggregate.py's truncation contract: papers_with_history
// is a subset of papers_examined (<= MAX_AGGREGATE_PAPERS), NOT of papers_total (the
// true, unbounded match count). When a search is truncated (papers_examined <
// papers_total), stating "X of papers_total" overstates what was actually sampled.
test("does not imply coverage is out of papers_total when the search was truncated", async () => {
  server.use(
    http.get("/saved-searches/s3/velocity", () =>
      HttpResponse.json({
        status: "ready",
        papers_total: 500,
        papers_examined: 200,
        papers_with_history: 60,
        series: [{ week_start: "2026-05-11", median_velocity_per_30d: 3.5 }],
        computed_at: new Date().toISOString(),
      }),
    ),
  );

  render(<SavedSearchVelocityTrend savedSearchId="s3" userId="u1" />, { wrapper });

  await waitFor(() => expect(screen.getByText(/median/i)).toBeInTheDocument());
  expect(screen.queryByText(/60 of 500/i)).not.toBeInTheDocument();
  expect(screen.getByText(/60 of 200/i)).toBeInTheDocument();
});

test("collapses silently on error", async () => {
  server.use(
    http.get("/saved-searches/s4/velocity", () => HttpResponse.text("boom", { status: 500 })),
  );

  const { container } = render(<SavedSearchVelocityTrend savedSearchId="s4" userId="u1" />, {
    wrapper,
  });

  await waitFor(() => expect(container).toBeEmptyDOMElement());
});
