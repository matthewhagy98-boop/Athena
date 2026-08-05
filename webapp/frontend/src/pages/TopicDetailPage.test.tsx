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

test("renders paper with null study_type without crashing", async () => {
  server.use(
    http.get("/search", () =>
      HttpResponse.json({
        rows: [
          {
            paper: { id: "p2", title: "Paper with null study type", abstract: null, pub_date: "2026-05-15" },
            score: { evidence_tier: "established", study_type: null, final_score: 70 },
            topics: [{ id: "t1", canonical_label: "Cognitive mapping" }],
          },
        ],
        total: 1,
        page: 1,
        page_size: 50,
      }),
    ),
  );
  renderPage();
  await waitFor(() => expect(screen.getByText("Paper with null study type")).toBeInTheDocument());
  // Verify the table renders without crashing and shows em-dash for null study_type
  expect(screen.getByText("—")).toBeInTheDocument();
});

test("shows a general error, distinct from not-found, when the distribution request fails", async () => {
  server.use(
    http.get("/topics/t1/tier-distribution", () => HttpResponse.text("boom", { status: 500 })),
  );
  renderPage();
  await waitFor(() =>
    expect(screen.getByText(/couldn't load this topic/i)).toBeInTheDocument(),
  );
  expect(screen.queryByText(/topic not found/i)).not.toBeInTheDocument();
});

test("shows a loading state while topic data is in flight", () => {
  renderPage();
  expect(screen.getByText(/loading topic/i)).toBeInTheDocument();
});
