import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

// Velocity is supplementary: its absence must never break a page, in production or
// in tests. A default empty map means any page that mounts usePaperVelocities gets
// a benign response without every test file having to know about it. Tests that
// assert velocity behavior override this with server.use().
export const server = setupServer(
  http.get("/papers/velocity", () => HttpResponse.json({ velocities: {} })),
  // Same reasoning as above: ComparePage mounts a CitationHistoryChart per card and
  // SavedSearchesPage mounts a SavedSearchVelocityTrend per row, each issuing its own
  // request. Pre-existing tests for those pages don't know about these endpoints, so
  // a default benign response keeps them passing unmodified.
  http.get("/papers/:paperId/citation-history", () =>
    HttpResponse.json({ paper_id: "unknown", observations: [], first_observed_at: null, source: "semantic_scholar" }),
  ),
  http.get("/saved-searches/:savedSearchId/velocity", () =>
    HttpResponse.json({
      status: "insufficient_coverage",
      papers_total: 0,
      papers_examined: 0,
      papers_with_history: 0,
      series: [],
      computed_at: new Date().toISOString(),
    }),
  ),
);
