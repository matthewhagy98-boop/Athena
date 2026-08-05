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

test("renders a scored paper with null study_type without throwing", async () => {
  server.use(
    http.get("/compare/papers", () =>
      HttpResponse.json({
        rows: [
          {
            paper: { id: "p2", title: "Untyped paper", abstract: "Abs.", pub_date: "2024-01-01" },
            score: { evidence_tier: "established", study_type: null, final_score: 80 },
            topics: [],
          },
        ],
        unresolved_ids: [],
      }),
    ),
  );
  renderAt("/compare?paper_ids=p2");
  await waitFor(() => expect(screen.getByText("Untyped paper")).toBeInTheDocument());
  expect(screen.getByText("—")).toBeInTheDocument();
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
