import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { server } from "../test/server";
import { useSearch, useTopics } from "./hooks";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

test("useSearch fetches rows with params", async () => {
  server.use(
    http.get("/search", ({ request }) => {
      const url = new URL(request.url);
      expect(url.searchParams.get("q")).toBe("neural");
      return HttpResponse.json({ rows: [], total: 0, page: 1, page_size: 50 });
    }),
  );
  const { result } = renderHook(() => useSearch({ q: "neural" }), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(result.current.data?.total).toBe(0);
});

test("useTopics fetches the topic list", async () => {
  server.use(
    http.get("/topics", () => HttpResponse.json([{ id: "t1", canonical_label: "Alpha" }])),
  );
  const { result } = renderHook(() => useTopics(), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(result.current.data?.[0].canonical_label).toBe("Alpha");
});
