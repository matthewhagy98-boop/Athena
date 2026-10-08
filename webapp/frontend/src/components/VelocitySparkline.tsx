const TEAL = "#006a61";

// The drawing box, in CSS pixels, matching the wrapper's w-16 h-4. The viewBox is
// 1:1 with it, so the 1.5px stroke is neither scaled nor distorted.
const WIDTH = 64;
const HEIGHT = 16;
// Keeps the stroke (1.5 wide, so 0.75 either side of the path) clear of the edges
// at the series' extremes, where the polyline touches the top and the bottom.
const PAD = 1;

// Must not exceed the badge region's reserved height (min-h-5 = 20px) or the row grows
// when a velocity arrives. Exported so the test can assert the two stay in step.
export const SPARKLINE_HEIGHT_CLASS = "h-4";

/** Rounded so the emitted geometry is stable enough to assert on. */
function round(n: number): number {
  return Math.round(n * 100) / 100;
}

/**
 * Maps a series onto the drawing box: oldest point at the left edge, newest at the
 * right, lowest value at the bottom. Deliberately not exported -- the test reads the
 * geometry off the rendered `<polyline>`, which is the surface that actually has to
 * be right, and which (unlike the chart library this replaced) jsdom can see.
 */
function sparklinePoints(values: number[]): string {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  const stepX = (WIDTH - 2 * PAD) / (values.length - 1);
  const plotHeight = HEIGHT - 2 * PAD;

  return values
    .map((value, index) => {
      const x = PAD + index * stepX;
      // A flat series has no range to scale against. Drawing it down the middle is
      // both the honest picture and the only option that avoids dividing by zero.
      const y = span === 0 ? HEIGHT / 2 : HEIGHT - PAD - ((value - min) / span) * plotHeight;
      return `${round(x)},${round(y)}`;
    })
    .join(" ");
}

export function VelocitySparkline({ points }: { points?: number[] }) {
  // Below three points a "line" is a single straight segment, which implies a trend
  // from one interval. Better to draw nothing than to imply a shape that isn't there.
  //
  // The `points` guard is belt-and-braces, not a contract gap. get_paper_velocities
  // emits recent_counts on every branch -- ready, insufficient_history, unrefreshable and
  // the empty block -- so a well-formed payload always carries it, and the type is
  // correctly non-optional. What the guard actually protects against is a TEST fixture or
  // a future partial payload: this renders inside CitationVelocityBadge on every search
  // result, any throw here blanks the entire results list, and velocity is supplementary
  // enough that it must never be able to do that. The earlier version of this comment
  // claimed a payload "would otherwise arrive without it", which overstated the case.
  if (!points || points.length < 3) return null;

  return (
    // Sized to sit INSIDE the badge's reserved line box rather than stretch it. The
    // region is min-h-5 (20px) around text-xs (12px on a 16px line box). A 20px
    // inline-block on align-middle produces a line box of roughly 24px, so the whole row
    // grew ~4px the moment a ready velocity arrived -- the layout shift the plan forbids
    // ("height is reserved from first paint"), on the highest-traffic page, and worse
    // because rows with history ended up taller than rows without.
    //
    // h-4 (16px) matches the line box and align-text-bottom keeps it on the baseline
    // instead of recentring it.
    <span aria-hidden="true" className={`inline-block ${SPARKLINE_HEIGHT_CLASS} w-16 align-text-bottom`}>
      {/* A hand-drawn polyline rather than a Recharts ResponsiveContainer. The chart
          library is the right tool elsewhere -- CitationHistoryChart keeps it, and should:
          that is one large interactive chart. This is a 3-12 point decoration on EVERY
          search-result row, so a full page mounted 50 containers, each installing a
          ResizeObserver and re-measuring on every window resize. Measured on a 50-row
          page that was 1250 DOM nodes, 54% of the page's entire element count, to
          decorate. The polyline draws the same picture in two nodes with no observers,
          and -- unlike ResponsiveContainer, which needs a layout engine -- it renders in
          jsdom, so the geometry above is unit-tested rather than just its class names. */}
      <svg width="100%" height="100%" viewBox={`0 0 ${WIDTH} ${HEIGHT}`}>
        <polyline points={sparklinePoints(points)} fill="none" stroke={TEAL} strokeWidth={1.5} />
      </svg>
    </span>
  );
}
