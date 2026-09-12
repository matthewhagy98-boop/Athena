import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { server } from "../test/server";
import { useCitationHistory, usePaperVelocities, useSavedSearchVelocity } from "./hooks";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

test("usePaperVelocities sorts ids so key order cannot split the cache", async () => {
  let requested: string[] = [];
  server.use(
    http.get("/papers/velocity", ({ request }) => {
      requested = new URL(request.url).searchParams.getAll("paper_ids");
      return HttpResponse.json({ velocities: {} });
    }),
  );

  const { result } = renderHook(() => usePaperVelocities(["b", "a"]), { wrapper });

  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(requested).toEqual(["a", "b"]);
});

test("usePaperVelocities does not fire for an empty list", () => {
  // No handler registered; onUnhandledRequest is "error", so a request would fail.
  const { result } = renderHook(() => usePaperVelocities([]), { wrapper });

  expect(result.current.fetchStatus).toBe("idle");
});

test("useCitationHistory fetches observations", async () => {
  server.use(
    http.get("/papers/p1/citation-history", () =>
      HttpResponse.json({
        paper_id: "p1",
        observations: [{ observed_on: "2026-07-01", citation_count: 104, is_anomalous: false }],
        first_observed_at: "2026-07-01T04:00:00Z",
        source: "semantic_scholar",
      }),
    ),
  );

  const { result } = renderHook(() => useCitationHistory("p1"), { wrapper });

  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(result.current.data?.observations[0].citation_count).toBe(104);
});

test("useSavedSearchVelocity stays idle without a user", () => {
  const { result } = renderHook(() => useSavedSearchVelocity("s1", null), { wrapper });

  expect(result.current.fetchStatus).toBe("idle");
});
