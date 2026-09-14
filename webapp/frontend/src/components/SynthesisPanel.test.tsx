import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { server } from "../test/server";
import { SynthesisPanel } from "./SynthesisPanel";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const READY = {
  id: "s1",
  status: "ready",
  narrative: "Both studies point the same way.",
  claims: [{ text: "Consistent effect.", citations: [0, 1] }],
  disagreements: [],
  strength_ranking: [0, 1],
  retracted_member_indices: [],
  failure_reason: null,
  subject_ids: ["p1", "p2"],
};

function renderPanel() {
  return render(<SynthesisPanel paperIds={["p1", "p2"]} />, { wrapper });
}

test("does not generate until the user asks", () => {
  renderPanel();
  expect(screen.getByRole("button", { name: /generate synthesis/i })).toBeInTheDocument();
  expect(screen.queryByText(/both studies point/i)).not.toBeInTheDocument();
});

test("renders the narrative and its claims after generating", async () => {
  server.use(http.post("/synthesis/papers", () => HttpResponse.json(READY)));
  renderPanel();

  fireEvent.click(screen.getByRole("button", { name: /generate synthesis/i }));

  await waitFor(() => expect(screen.getByText(/both studies point the same way/i)).toBeInTheDocument());
  expect(screen.getByText(/consistent effect/i)).toBeInTheDocument();
});

test("shows a retraction warning when a member is retracted", async () => {
  server.use(
    http.post("/synthesis/papers", () => HttpResponse.json({ ...READY, retracted_member_indices: [1] })),
  );
  renderPanel();

  fireEvent.click(screen.getByRole("button", { name: /generate synthesis/i }));

  await waitFor(() => expect(screen.getByText(/retracted/i)).toBeInTheDocument());
});

test("explains a failed synthesis instead of showing nothing", async () => {
  server.use(
    http.post("/synthesis/papers", () =>
      HttpResponse.json({ ...READY, status: "failed", narrative: null, failure_reason: "citation_density" }),
    ),
  );
  renderPanel();

  fireEvent.click(screen.getByRole("button", { name: /generate synthesis/i }));

  await waitFor(() => expect(screen.getByText(/couldn't produce a grounded summary/i)).toBeInTheDocument());
});

test("shows an unavailable message when synthesis is disabled", async () => {
  server.use(http.post("/synthesis/papers", () => HttpResponse.text("off", { status: 503 })));
  renderPanel();

  fireEvent.click(screen.getByRole("button", { name: /generate synthesis/i }));

  await waitFor(() => expect(screen.getByText(/not available right now/i)).toBeInTheDocument());
});

test("shows a generic error message for failures other than disabled (e.g. an unknown paper id)", async () => {
  server.use(http.post("/synthesis/papers", () => HttpResponse.text("no such paper", { status: 404 })));
  renderPanel();

  fireEvent.click(screen.getByRole("button", { name: /generate synthesis/i }));

  await waitFor(() => expect(screen.getByText(/couldn't generate a synthesis/i)).toBeInTheDocument());
  expect(screen.queryByText(/not available right now/i)).not.toBeInTheDocument();
});

// The point of this test: the backend sorts synthesis members by str(uuid) before
// building the prompt, so a citation index is a position in that sorted order
// (`subject_ids`), not a position in the order the Compare grid displays cards
// (`paperIds`, selection order). Here the two orders are deliberately different, so
// citing by raw index position (claim.citations.map(c => c + 1)) would label the
// wrong card. This test picks a shuffle where the naive approach and the correct
// approach produce different, unambiguous bracket numbers.
test("resolves citations through subject_ids so a shuffled paperIds prop still cites the correct card", async () => {
  const displayOrder = ["p2", "p1", "p3"]; // how the Compare grid renders cards
  const sortedOrder = ["p3", "p1", "p2"]; // canonical order the backend's indices refer to

  server.use(
    http.post("/synthesis/papers", () =>
      HttpResponse.json({
        ...READY,
        subject_ids: sortedOrder,
        // citation 0 -> sortedOrder[0] = "p3" -> displayOrder index 2 -> card #3
        // citation 2 -> sortedOrder[2] = "p2" -> displayOrder index 0 -> card #1
        claims: [{ text: "Effect confirmed across studies.", citations: [0, 2] }],
      }),
    ),
  );

  render(<SynthesisPanel paperIds={displayOrder} />, { wrapper });
  fireEvent.click(screen.getByRole("button", { name: /generate synthesis/i }));

  await waitFor(() => expect(screen.getByText(/effect confirmed across studies/i)).toBeInTheDocument());

  // Correct: citations resolved through subject_ids then re-indexed into display order.
  expect(screen.getByText("[3, 1]")).toBeInTheDocument();
  // The brief's rejected approach (claim.citations.map(c => c + 1)) would render "[1, 3]".
  expect(screen.queryByText("[1, 3]")).not.toBeInTheDocument();
});
