import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { server } from "../test/server";
import {
  useActivityRanking,
  useChangeFeed,
  usePersonalDashboard,
  useRemoveInterest,
} from "./hooks";

// These four hooks were migrated from hand-built query strings to buildUrl params, and
// three of the four migrations survived mutation: the parameters could be dropped
// entirely and all 157 tests still passed. The worst was /dashboard/personal losing
// `user_id`, which the endpoint requires -- production would have answered 422 on every
// dashboard load while the suite stayed green.
//
// Nothing asserted the outgoing request, only the decoded response, so the URL was
// invisible. These tests capture what actually goes over the wire.

const USER_ID = "00000000-0000-0000-0000-000000000077";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** Records the search params of the next request to `path`. */
// `body` is typed Record<string, unknown>, not unknown: HttpResponse.json takes a
// JsonBodyType and `unknown` does not satisfy it. vitest does not typecheck, so the first
// version of this file passed 164 tests and failed `npm run build` -- the third time that
// exact pairing has caught me on this branch, which is why the build belongs in the done
// criteria rather than after it.
function captureParams(
  method: "get" | "delete",
  path: string,
  body: Record<string, unknown> = {},
) {
  const seen: { url?: URL } = {};
  const handler = ({ request }: { request: Request }) => {
    seen.url = new URL(request.url);
    return method === "delete" ? new HttpResponse(null, { status: 204 }) : HttpResponse.json(body);
  };
  server.use(method === "get" ? http.get(path, handler) : http.delete(path, handler));
  return seen;
}

test("the activity ranking sends its limit", async () => {
  const seen = captureParams("get", "/dashboard/activity", { topics: [], computed_at: null });

  renderHook(() => useActivityRanking(7), { wrapper });

  await waitFor(() => expect(seen.url).toBeDefined());
  expect(seen.url!.searchParams.get("limit")).toBe("7");
});

test("the change feed sends both days and limit", async () => {
  const seen = captureParams("get", "/dashboard/changes", { days: [], total_events: 0 });

  renderHook(() => useChangeFeed(14, 33), { wrapper });

  await waitFor(() => expect(seen.url).toBeDefined());
  expect(seen.url!.searchParams.get("days")).toBe("14");
  expect(seen.url!.searchParams.get("limit")).toBe("33");
});

test("the personal dashboard sends user_id, which the endpoint requires", async () => {
  // The one that mattered most: without it the endpoint 422s on every load.
  const seen = captureParams("get", "/dashboard/personal", { has_profile: false });

  renderHook(() => usePersonalDashboard(USER_ID), { wrapper });

  await waitFor(() => expect(seen.url).toBeDefined());
  expect(seen.url!.searchParams.get("user_id")).toBe(USER_ID);
});

test("removing an interest sends user_id and encodes the topic id in the path", async () => {
  const seen = captureParams("delete", "/interests/:topicId");

  const { result } = renderHook(() => useRemoveInterest(), { wrapper });
  result.current.mutate({ userId: USER_ID, topicId: "topic/with slash" });

  await waitFor(() => expect(seen.url).toBeDefined());
  expect(seen.url!.searchParams.get("user_id")).toBe(USER_ID);
  // Encoded rather than interpolated raw, so an id containing a slash cannot change
  // which path is requested.
  expect(seen.url!.pathname).toBe("/interests/topic%2Fwith%20slash");
});
