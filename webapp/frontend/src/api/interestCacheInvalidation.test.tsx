import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { server } from "../test/server";
import { useAddInterest, usePersonalDashboard, useRemoveInterest } from "./hooks";

// Adding or removing a topic has to make the visible topic list refetch. That is the
// whole user-facing point of the interest picker: without the invalidation the write
// succeeds, the server state changes, and the list silently keeps showing what it
// showed before until something else happens to refetch it.
//
// Nothing covered this. Deleting BOTH `invalidateQueries` calls from `useAddInterest`
// and `useRemoveInterest` left all 145 frontend tests passing, so the mechanism could
// be removed without a single red. These tests assert the observable consequence --
// the list's content changes after the mutation -- rather than spying on the
// queryClient, so they stay honest if the invalidation is rewritten (a direct setData,
// a refetch, a different key) as long as the user still sees the new list.

const USER_ID = "00000000-0000-0000-0000-000000000042";

function personalPayload(labels: string[]) {
  return {
    has_profile: true,
    computed_at: "2026-09-20T00:00:00Z",
    window_start: "2026-09-13T00:00:00Z",
    window_end: "2026-09-20T00:00:00Z",
    blurb: "Some activity this week.",
    topics: labels.map((label, index) => ({
      topic: { id: `t${index}`, canonical_label: label },
      event_count: 3,
      new_paper: 1,
      consensus_updated: 1,
      contradiction_flagged: 1,
      retraction_detected: 0,
    })),
  };
}

/** Serves the first payload until `advance()` is called, then the second. */
function personalEndpointThatChanges(before: string[], after: string[]) {
  let current = before;
  server.use(
    http.get("/dashboard/personal", () => HttpResponse.json(personalPayload(current))),
  );
  return () => {
    current = after;
  };
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function Harness({ action }: { action: "add" | "remove" }) {
  const personal = usePersonalDashboard(USER_ID);
  const add = useAddInterest();
  const remove = useRemoveInterest();

  return (
    <div>
      <ul>
        {personal.data?.topics.map((row) => (
          <li key={row.topic.id}>{row.topic.canonical_label}</li>
        ))}
      </ul>
      <button
        type="button"
        onClick={() =>
          action === "add"
            ? add.mutate({ userId: USER_ID, freeText: "sepsis" })
            : remove.mutate({ userId: USER_ID, topicId: "t1" })
        }
      >
        go
      </button>
    </div>
  );
}

test("adding an interest refetches the personal topic list", async () => {
  const advance = personalEndpointThatChanges(["Atrial fibrillation"], [
    "Atrial fibrillation",
    "Sepsis",
  ]);
  server.use(
    http.post("/interests", () => {
      advance();
      return HttpResponse.json(
        { topic: { id: "t1", canonical_label: "Sepsis" }, created: true },
        { status: 201 },
      );
    }),
  );
  render(<Harness action="add" />, { wrapper });

  // Wait for the FIRST list before mutating, so the assertion below cannot pass
  // just because the query had not resolved yet.
  await screen.findByText("Atrial fibrillation");
  expect(screen.queryByText("Sepsis")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "go" }));

  await waitFor(() => expect(screen.getByText("Sepsis")).toBeInTheDocument());
});

test("removing an interest refetches the personal topic list", async () => {
  const advance = personalEndpointThatChanges(
    ["Atrial fibrillation", "Sepsis"],
    ["Atrial fibrillation"],
  );
  server.use(
    http.delete("/interests/:topicId", () => {
      advance();
      return new HttpResponse(null, { status: 204 });
    }),
  );
  render(<Harness action="remove" />, { wrapper });

  await screen.findByText("Sepsis");

  fireEvent.click(screen.getByRole("button", { name: "go" }));

  await waitFor(() => expect(screen.queryByText("Sepsis")).not.toBeInTheDocument());
  // The other row must still be there: proves the list refetched rather than the whole
  // query erroring or emptying, which would also remove "Sepsis".
  expect(screen.getByText("Atrial fibrillation")).toBeInTheDocument();
});
