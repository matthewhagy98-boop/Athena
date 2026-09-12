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

test("shows an error message when the saved searches list fails to load", async () => {
  server.use(http.get("/saved-searches", () => HttpResponse.text("not found", { status: 404 })));
  renderPage();
  await waitFor(() => expect(screen.getByText(/couldn't load your saved searches/i)).toBeInTheDocument());
});

test("shows an error message when run fails", async () => {
  server.use(
    http.get("/saved-searches", () => HttpResponse.json(saved)),
    http.post("/saved-searches/s1/run", () => HttpResponse.text("boom", { status: 500 })),
  );
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: /run/i }));
  await waitFor(() => expect(screen.getByText(/couldn't run that search/i)).toBeInTheDocument());
});

test("requests the velocity trend for at most the first 10 rows", async () => {
  const requestedIds: string[] = [];
  const manySaved = Array.from({ length: 12 }, (_, i) => ({
    id: `s${i + 1}`,
    name: `Search ${i + 1}`,
    query_params: { q: "x" },
  }));
  server.use(
    http.get("/saved-searches", () => HttpResponse.json(manySaved)),
    http.get("/saved-searches/:id/velocity", ({ params }) => {
      requestedIds.push(params.id as string);
      return HttpResponse.json({
        status: "insufficient_coverage",
        papers_total: 10,
        papers_examined: 10,
        papers_with_history: 1,
        series: [],
        computed_at: new Date().toISOString(),
      });
    }),
  );

  renderPage();

  await waitFor(() => expect(screen.getByText("Search 12")).toBeInTheDocument());
  await waitFor(() => expect(requestedIds.length).toBeGreaterThanOrEqual(10));

  const uniqueRequestedIds = new Set(requestedIds);
  expect(uniqueRequestedIds.size).toBe(10);
  for (let i = 1; i <= 10; i++) {
    expect(uniqueRequestedIds.has(`s${i}`)).toBe(true);
  }
  expect(uniqueRequestedIds.has("s11")).toBe(false);
  expect(uniqueRequestedIds.has("s12")).toBe(false);
});
