import { Line, LineChart, ResponsiveContainer } from "recharts";

const TEAL = "#006a61";

// Must not exceed the badge region's reserved height (min-h-5 = 20px) or the row grows
// when a velocity arrives. Exported so the test can assert the two stay in step.
export const SPARKLINE_HEIGHT_CLASS = "h-4";

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

  const data = points.map((value, index) => ({ index, value }));
  return (
    // Sized to sit INSIDE the badge's reserved line box rather than stretch it. The
    // region is min-h-5 (20px) around text-xs (12px on a 16px line box). A 20px
    // inline-block on align-middle produces a line box of roughly 24px, so the whole row
    // grew ~4px the moment a ready velocity arrived -- the layout shift the plan forbids
    // ("height is reserved from first paint"), on the highest-traffic page, and worse
    // because rows with history ended up taller than rows without.
    //
    // h-4 (16px) matches the line box and align-text-bottom keeps it on the baseline
    // instead of recentring it. jsdom does not do layout, so no test can measure this;
    // the test asserts the class instead, and the reasoning lives here.
    <span aria-hidden="true" className={`inline-block ${SPARKLINE_HEIGHT_CLASS} w-16 align-text-bottom`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <Line type="monotone" dataKey="value" stroke={TEAL} strokeWidth={1.5} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </span>
  );
}
