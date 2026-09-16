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

test("does not generate until the user asks", async () => {
  // Asserting synchronously after render proves nothing: an auto-firing useEffect would
  // not have resolved its round-trip by the time these run, so the narrative would still
  // be absent and the test would pass. The constraint here is that visiting Compare never
  // silently spends money on a model call, so the request itself is what must be counted.
  let requests = 0;
  server.use(
    http.post("/synthesis/papers", () => {
      requests += 1;
      return HttpResponse.json(READY);
    }),
  );

  renderPanel();

  expect(screen.getByRole("button", { name: /generate synthesis/i })).toBeInTheDocument();
  expect(screen.queryByText(/both studies point/i)).not.toBeInTheDocument();

  // Give an auto-fired mutation time to land before concluding none was made.
  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(requests).toBe(0);

  fireEvent.click(screen.getByRole("button", { name: /generate synthesis/i }));
  await waitFor(() => expect(screen.getByText(/both studies point the same way/i)).toBeInTheDocument());
  expect(requests).toBe(1);
});

test("renders every claim, not just the first", async () => {
  // Every other fixture carries exactly one claim, so .map could be narrowed to
  // claims[0] undetected. The claims list is the panel's grounding: each one is a
  // separate assertion the reader is meant to be able to trace to a study.
  server.use(
    http.post("/synthesis/papers", () =>
      HttpResponse.json({
        ...READY,
        claims: [
          { text: "First claim.", citations: [0] },
          { text: "Second claim.", citations: [1] },
          { text: "Third claim.", citations: [0, 1] },
        ],
      }),
    ),
  );
  renderPanel();

  fireEvent.click(screen.getByRole("button", { name: /generate synthesis/i }));

  await waitFor(() => expect(screen.getByText(/first claim/i)).toBeInTheDocument());
  expect(screen.getByText(/second claim/i)).toBeInTheDocument();
  expect(screen.getByText(/third claim/i)).toBeInTheDocument();
});

test("the trigger is disabled while a generation is in flight", async () => {
  // Generation costs money per call, so the disabled state is a spend guard, not polish.
  let requests = 0;
  server.use(
    http.post("/synthesis/papers", async () => {
      requests += 1;
      await new Promise((resolve) => setTimeout(resolve, 50));
      return HttpResponse.json(READY);
    }),
  );
  renderPanel();

  const button = screen.getByRole("button", { name: /generate synthesis/i });
  fireEvent.click(button);

  await waitFor(() => expect(screen.getByRole("button", { name: /generating/i })).toBeDisabled());
  fireEvent.click(screen.getByRole("button", { name: /generating/i }));

  await waitFor(() => expect(screen.getByText(/both studies point the same way/i)).toBeInTheDocument());
  expect(requests).toBe(1);
});

test("renders the narrative and its claims after generating", async () => {
  server.use(http.post("/synthesis/papers", () => HttpResponse.json(READY)));
  renderPanel();

  fireEvent.click(screen.getByRole("button", { name: /generate synthesis/i }));

  await waitFor(() => expect(screen.getByText(/both studies point the same way/i)).toBeInTheDocument());
  expect(screen.getByText(/consistent effect/i)).toBeInTheDocument();
});

// getByText(/retracted/i) alone cannot tell a correct warning from a wrong count, a
// broken plural, or a warning that renders for every comparison -- nothing asserted its
// absence, so dropping the length guard would render "includes 0 retracted studies"
// unchallenged. Retraction is the one thing on this panel a researcher must not miss,
// and overstating it is as damaging as hiding it.
test("names how many members are retracted, with the right plural", async () => {
  server.use(
    http.post("/synthesis/papers", () => HttpResponse.json({ ...READY, retracted_member_indices: [1] })),
  );
  renderPanel();

  fireEvent.click(screen.getByRole("button", { name: /generate synthesis/i }));

  await waitFor(() =>
    expect(screen.getByText(/includes 1 retracted study\b/i)).toBeInTheDocument(),
  );
  expect(screen.queryByText(/retracted studies/i)).not.toBeInTheDocument();
});

test("pluralises the retraction warning for more than one", async () => {
  server.use(
    http.post("/synthesis/papers", () =>
      HttpResponse.json({ ...READY, retracted_member_indices: [0, 1] }),
    ),
  );
  renderPanel();

  fireEvent.click(screen.getByRole("button", { name: /generate synthesis/i }));

  await waitFor(() =>
    expect(screen.getByText(/includes 2 retracted studies/i)).toBeInTheDocument(),
  );
});

test("shows no retraction warning when nothing is retracted", async () => {
  server.use(http.post("/synthesis/papers", () => HttpResponse.json(READY)));
  renderPanel();

  fireEvent.click(screen.getByRole("button", { name: /generate synthesis/i }));

  await waitFor(() => expect(screen.getByText(/both studies point the same way/i)).toBeInTheDocument());
  expect(screen.queryByText(/retracted/i)).not.toBeInTheDocument();
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
