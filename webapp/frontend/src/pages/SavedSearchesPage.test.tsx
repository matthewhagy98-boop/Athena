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
