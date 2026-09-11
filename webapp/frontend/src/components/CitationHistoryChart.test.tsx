import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { server } from "../test/server";
import { CitationHistoryChart } from "./CitationHistoryChart";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

test("renders the section heading once history exists", async () => {
  server.use(
    http.get("/papers/p1/citation-history", () =>
      HttpResponse.json({
        paper_id: "p1",
        observations: [
          { observed_on: "2026-07-01", citation_count: 100, is_anomalous: false },
          { observed_on: "2026-07-08", citation_count: 108, is_anomalous: false },
          { observed_on: "2026-07-15", citation_count: 115, is_anomalous: false },
        ],
        first_observed_at: "2026-07-01T04:00:00Z",
        source: "semantic_scholar",
      }),
    ),
  );

  render(<CitationHistoryChart paperId="p1" />, { wrapper });

  await waitFor(() => expect(screen.getByText(/citation history/i)).toBeInTheDocument());
});

test("shows the empty message when there are no observations", async () => {
  server.use(
    http.get("/papers/p2/citation-history", () =>
      HttpResponse.json({
        paper_id: "p2",
        observations: [],
        first_observed_at: null,
        source: "semantic_scholar",
      }),
    ),
  );

  render(<CitationHistoryChart paperId="p2" />, { wrapper });

  await waitFor(() => expect(screen.getByText(/not enough history yet/i)).toBeInTheDocument());
});

test("collapses silently on error", async () => {
  server.use(
    http.get("/papers/p3/citation-history", () => HttpResponse.text("boom", { status: 500 })),
  );

  const { container } = render(<CitationHistoryChart paperId="p3" />, { wrapper });

  await waitFor(() => expect(container.textContent).not.toMatch(/error|failed/i));
  // Stronger than the text-content check above: prove the component actually
  // rendered nothing (returned null) rather than merely avoiding the word "error".
  await waitFor(() => expect(container).toBeEmptyDOMElement());
});
