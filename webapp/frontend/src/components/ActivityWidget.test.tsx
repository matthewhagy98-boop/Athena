import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ActivityResponse } from "../api/types";
import { ActivityWidget } from "./ActivityWidget";

function row(overrides = {}) {
  return {
    topic: { id: "t1", canonical_label: "Atrial fibrillation" },
    rank: 1,
    event_count: 24,
    breakdown: { new_paper: 19, consensus_updated: 2, contradiction_flagged: 2, paper_retracted: 1 },
    baseline_mean: 7.375,
    baseline_weeks: 8,
    trend_score: 4.173,
    is_newly_tracked: false,
    ...overrides,
  };
}

function renderWidget(data: Partial<ActivityResponse> = {}) {
  const payload: ActivityResponse = {
    computed_at: "2026-08-02T04:10:22Z",
    window_start: "2026-07-26T00:00:00Z",
    window_end: "2026-08-02T00:00:00Z",
    topics: [row()],
    ...data,
  };
  return render(
    <MemoryRouter>
      <ActivityWidget data={payload} isLoading={false} isError={false} />
    </MemoryRouter>,
  );
}

test("shows each topic's raw event count, not only a score", () => {
  // FR-C-004. A derived score alone is unauditable -- the reader cannot tell whether
  // "4.173" came from 24 events or from 5.
  renderWidget();

  expect(screen.getByText(/24/)).toBeInTheDocument();
});

test("a newly tracked topic shows no change-versus-baseline figure", () => {
  // FR-C-003/004: with fewer than 8 weeks there is no honest baseline to compare against,
  // so showing a percentage would invent one.
  renderWidget({
    topics: [row({ is_newly_tracked: true, trend_score: null, baseline_mean: null, baseline_weeks: 3 })],
  });

  expect(screen.getByText(/newly tracked/i)).toBeInTheDocument();
  expect(screen.queryByText(/%/)).not.toBeInTheDocument();
});

test("every topic row links to its topic detail page", () => {
  // FR-C-012: the dashboard must add no dead ends.
  renderWidget();

  expect(screen.getByRole("link", { name: /atrial fibrillation/i })).toHaveAttribute(
    "href",
    "/topics/t1",
  );
});

test("explains that the ranking measures volume, not significance, reachably", () => {
  // FR-C-016. Without this the ranking reads as an editorial judgement about which
  // science matters, which is exactly what it is not.
  //
  // Asserts the caveat is REACHABLE, not merely present. This used to be getByTitle,
  // which passed for a `title` attribute on a focusable <span> -- not announced reliably
  // by screen readers, and invisible on touch. The attribute was pinned; its
  // reachability was not. Now it is a real disclosure button that reveals real text.
  renderWidget();

  const toggle = screen.getByRole("button", { name: /what does this mean/i });
  expect(toggle).toHaveAttribute("aria-expanded", "false");

  // aria-controls is an IDREF, so the element it names must exist even while collapsed --
  // otherwise the attribute points at nothing. It was conditionally mounted, so it did
  // not. Asserted by resolving the reference rather than by its presence, because only
  // resolving it can fail when the target is unmounted.
  const controlled = document.getElementById(toggle.getAttribute("aria-controls") ?? "");
  expect(controlled).not.toBeNull();
  // Not `queryByText(...).not.toBeInTheDocument()`: the paragraph is now always in the
  // DOM so the IDREF resolves, so presence is the wrong question. Visibility is the one
  // the user experiences, and `hidden` also keeps it out of the accessibility tree.
  expect(controlled).not.toBeVisible();

  fireEvent.click(toggle);

  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(controlled).toBeVisible();
  expect(
    screen.getByText(/volume of newly indexed and changed evidence/i),
  ).toBeInTheDocument();
});

const FORBIDDEN = /trending|hot|popular|breakthrough|important|momentum|real-time|\blive\b/i;

test("never uses quality or hype language", () => {
  // FR-C-015. The ranking is volume-based; any of these words claims something about
  // the science itself that the metric cannot support.
  const { container } = renderWidget();

  expect(container.textContent).not.toMatch(FORBIDDEN);
});

test("the empty state says no change rather than no results", () => {
  const { container } = renderWidget({ topics: [], computed_at: null });

  // The positive assertion first. Without it this test asserted only an absence, so
  // deleting the empty-state paragraph entirely satisfied it -- a test that passes when
  // the thing it is named for does not render at all.
  expect(screen.getByText(/no topic reached the activity threshold/i)).toBeInTheDocument();
  expect(container.textContent).not.toMatch(/no results|nothing found/i);
});
