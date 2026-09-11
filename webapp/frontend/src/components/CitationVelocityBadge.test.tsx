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

test("a retracted paper qualifies the figure", () => {
  render(<CitationVelocityBadge velocity={velocity()} isRetracted={true} />);

  expect(screen.getByText(/citations after retraction/i)).toBeInTheDocument();
});

test("never uses quality language", () => {
  const { container } = render(
    <CitationVelocityBadge velocity={velocity()} isRetracted={false} />,
  );

  expect(container.textContent).not.toMatch(/impact|influence|importance|momentum|trending/i);
});
