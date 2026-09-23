import { render, screen } from "@testing-library/react";
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

test("explains that the ranking measures volume, not significance", () => {
  // FR-C-016. Without this the ranking reads as an editorial judgement about which
  // science matters, which is exactly what it is not.
  renderWidget();

  expect(
    screen.getByTitle(/volume of newly indexed and changed evidence/i),
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

  expect(container.textContent).not.toMatch(/no results|nothing found/i);
});
