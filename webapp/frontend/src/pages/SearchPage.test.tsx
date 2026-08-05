import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
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

test("save search shows an error when the save fails", async () => {
  server.use(
    http.get("/search", () => HttpResponse.json({ rows: [], total: 0, page: 1, page_size: 50 })),
    http.post("/saved-searches", () => HttpResponse.text("boom", { status: 500 })),
  );
  renderPage("/search?q=neural");
  fireEvent.click(await screen.findByRole("button", { name: /save search/i }));
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "My search" } });
  fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
  await waitFor(() => expect(screen.getByText(/couldn't save that search/i)).toBeInTheDocument());
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
