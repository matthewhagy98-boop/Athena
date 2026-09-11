import { render, screen } from "@testing-library/react";
import type { PaperVelocity } from "../api/types";
import { CitationVelocityBadge } from "./CitationVelocityBadge";

function velocity(overrides: Partial<PaperVelocity> = {}): PaperVelocity {
  return {
    status: "ready",
    velocity_per_30d: 14,
    window_start_observed_at: "2026-07-03T04:20:11Z",
    window_end_observed_at: "2026-08-02T04:18:52Z",
    observation_count: 6,
    first_observed_at: "2026-06-28T04:15:02Z",
    percentile: 88,
    cohort_size: 34,
    is_retracted: false,
    computed_at: new Date().toISOString(),
    ...overrides,
  };
}

test("renders the figure with an explicit unit in text", () => {
  render(<CitationVelocityBadge velocity={velocity()} isRetracted={false} />);

  expect(screen.getByText(/14/)).toBeInTheDocument();
  // Units are spelled out for screen readers, not implied by a compact glyph.
  expect(screen.getByText(/citations in the last 30 days/i)).toBeInTheDocument();
});

test("shows the percentile with age-and-topic scoping", () => {
  render(<CitationVelocityBadge velocity={velocity()} isRetracted={false} />);

  expect(screen.getByText(/top 12% for its age in this topic/i)).toBeInTheDocument();
});

test("the percentile tooltip is keyboard-reachable", () => {
  render(<CitationVelocityBadge velocity={velocity()} isRetracted={false} />);

  const percentileEl = screen.getByText(/top 12% for its age in this topic/i);
  expect(percentileEl).toHaveAttribute("tabIndex", "0");
});

test("omits the percentile when the cohort is too small", () => {
  render(
    <CitationVelocityBadge
      velocity={velocity({ percentile: null, cohort_size: 4 })}
      isRetracted={false}
    />,
  );

  expect(screen.queryByText(/for its age in this topic/i)).not.toBeInTheDocument();
  expect(screen.getByText(/citations in the last 30 days/i)).toBeInTheDocument();
});

test("insufficient history shows the tracking-since date and no number", () => {
  render(
    <CitationVelocityBadge
      velocity={velocity({
        status: "insufficient_history",
        velocity_per_30d: null,
        observation_count: 1,
        percentile: null,
      })}
      isRetracted={false}
    />,
  );

  expect(screen.getByText(/not enough history yet/i)).toBeInTheDocument();
  expect(screen.getByText(/tracking since/i)).toBeInTheDocument();
  expect(screen.queryByText(/citations in the last 30 days/i)).not.toBeInTheDocument();
});

test("the true empty-block shape (no cache row at all) renders with no tracking-since clause", () => {
  // _empty_block() in citations/read.py emits status: insufficient_history with
  // BOTH computed_at and first_observed_at null -- this is what every paper gets
  // today, since collection started 2026-09-08 and nothing has two observations
  // yet. The "tracking since" clause is correctly absent here: there is no date
  // to show, and inventing one would be false. A future reader seeing no clause
  // should not "fix" this by fabricating a first_observed_at.
  render(
    <CitationVelocityBadge
      velocity={velocity({
        status: "insufficient_history",
        velocity_per_30d: null,
        observation_count: 0,
        first_observed_at: null,
        percentile: null,
        cohort_size: 0,
        computed_at: null,
      })}
      isRetracted={false}
    />,
  );

  expect(screen.getByText(/not enough history yet/i)).toBeInTheDocument();
  expect(screen.queryByText(/tracking since/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/\d/)).not.toBeInTheDocument();
  expect(screen.queryByText(/for its age in this topic/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/as of \d+ days ago/i)).not.toBeInTheDocument();
});

test("undefined velocity renders an element rather than collapsing", () => {
  // The region's height is reserved from first paint; returning null would shift layout.
  const { container } = render(
    <CitationVelocityBadge velocity={undefined} isRetracted={false} />,
  );

  expect(container.firstChild).not.toBeNull();
});

test("an aging computation is labelled with its age", () => {
  const tenDaysAgo = new Date(Date.now() - 10 * 86400000).toISOString();

  render(
    <CitationVelocityBadge velocity={velocity({ computed_at: tenDaysAgo })} isRetracted={false} />,
  );

  expect(screen.getByText(/as of 10 days ago/i)).toBeInTheDocument();
});

test("a computation over 21 days old is suppressed entirely", () => {
  const longAgo = new Date(Date.now() - 30 * 86400000).toISOString();

  render(<CitationVelocityBadge velocity={velocity({ computed_at: longAgo })} isRetracted={false} />);

  expect(screen.getByText(/citation trend unavailable/i)).toBeInTheDocument();
  expect(screen.queryByText(/citations in the last 30 days/i)).not.toBeInTheDocument();
});

test("at exactly AGING_DAYS (3), the age label already appears", () => {
  const threeDaysAgo = new Date(Date.now() - 3 * 86400000).toISOString();

  render(
    <CitationVelocityBadge velocity={velocity({ computed_at: threeDaysAgo })} isRetracted={false} />,
  );

  expect(screen.getByText(/as of 3 days ago/i)).toBeInTheDocument();
  expect(screen.getByText(/citations in the last 30 days/i)).toBeInTheDocument();
});

test("at exactly 21 days old, the computation is still shown, not suppressed", () => {
  // age > SUPPRESS_DAYS (21) is the suppress condition, so age === 21 must not suppress.
  const twentyOneDaysAgo = new Date(Date.now() - 21 * 86400000).toISOString();

  render(
    <CitationVelocityBadge velocity={velocity({ computed_at: twentyOneDaysAgo })} isRetracted={false} />,
  );

  expect(screen.getByText(/as of 21 days ago/i)).toBeInTheDocument();
  expect(screen.queryByText(/citation trend unavailable/i)).not.toBeInTheDocument();
});

test("at 22 days old, the computation is suppressed", () => {
  const twentyTwoDaysAgo = new Date(Date.now() - 22 * 86400000).toISOString();

  render(
    <CitationVelocityBadge velocity={velocity({ computed_at: twentyTwoDaysAgo })} isRetracted={false} />,
  );

  expect(screen.getByText(/citation trend unavailable/i)).toBeInTheDocument();
  expect(screen.queryByText(/citations in the last 30 days/i)).not.toBeInTheDocument();
});

test("a retracted paper qualifies the figure", () => {
  render(<CitationVelocityBadge velocity={velocity()} isRetracted={true} />);

  expect(screen.getByText(/citations after retraction/i)).toBeInTheDocument();
});

test("never uses quality language", () => {
  const { container } = render(
    <CitationVelocityBadge velocity={velocity()} isRetracted={false} />,
  );

  expect(container.textContent).not.toMatch(
    /impact|influence|importance|momentum|trending|highly cited|no citations|0 citations/i,
  );
});
