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

test("renders the disagreement list with resolved card positions", async () => {
  // Disagreements travelled through the tool schema, validator, DB column, serializer and
  // TS interface and were then dropped at the last step. Where studies conflict is the
  // most decision-relevant thing a comparison can report.
  server.use(
    http.post("/synthesis/papers", () =>
      HttpResponse.json({
        ...READY,
        subject_ids: ["p2", "p1"],
        disagreements: [{ indices: [0, 1], description: "Effect direction differs." }],
      }),
    ),
  );
  render(<SynthesisPanel paperIds={["p1", "p2"]} />, { wrapper });

  fireEvent.click(screen.getByRole("button", { name: /generate synthesis/i }));

  await waitFor(() => expect(screen.getByText(/points of disagreement/i)).toBeInTheDocument());
  expect(screen.getByText(/effect direction differs/i)).toBeInTheDocument();
  // subject_ids[0]="p2" -> card 2; subject_ids[1]="p1" -> card 1. Positional rendering
  // would show "1 vs 2".
  expect(screen.getByText("[2 vs 1]")).toBeInTheDocument();
});

test("names which study is retracted, not just how many", async () => {
  // A count with no identity tells a researcher something is wrong and gives them no way
  // to find it. Retracted indices are positions in subject_ids, like citations.
  server.use(
    http.post("/synthesis/papers", () =>
      HttpResponse.json({
        ...READY,
        subject_ids: ["p2", "p1"],
        retracted_member_indices: [0],
      }),
    ),
  );
  render(<SynthesisPanel paperIds={["p1", "p2"]} />, { wrapper });

  fireEvent.click(screen.getByRole("button", { name: /generate synthesis/i }));

  // subject_ids[0] = "p2", which the grid displays second.
  await waitFor(() => expect(screen.getByText(/includes 1 retracted study \(2\)/i)).toBeInTheDocument());
});

test("shows a provenance line naming the model and date", async () => {
  server.use(
    http.post("/synthesis/papers", () =>
      HttpResponse.json({ ...READY, model_id: "claude-sonnet-4-6", generated_at: "2026-09-15T12:00:00Z" }),
    ),
  );
  renderPanel();

  fireEvent.click(screen.getByRole("button", { name: /generate synthesis/i }));

  await waitFor(() => expect(screen.getByText(/written by claude-sonnet-4-6/i)).toBeInTheDocument());
  expect(screen.getByText(/ai-generated; verify against the studies/i)).toBeInTheDocument();
});

test("omits the provenance line when the payload lacks it", async () => {
  // Velocity taught this lesson: an added field that an older or partial payload lacks
  // must not take the panel down with it.
  server.use(http.post("/synthesis/papers", () => HttpResponse.json(READY)));
  renderPanel();

  fireEvent.click(screen.getByRole("button", { name: /generate synthesis/i }));

  await waitFor(() => expect(screen.getByText(/both studies point the same way/i)).toBeInTheDocument());
  expect(screen.queryByText(/written by/i)).not.toBeInTheDocument();
});
