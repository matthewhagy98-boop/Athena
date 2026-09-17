import type { PaperVelocity } from "../api/types";
import { VelocitySparkline } from "./VelocitySparkline";

const AGING_DAYS = 3;
const SUPPRESS_DAYS = 21;

function daysSince(iso: string | null): number | null {
  if (!iso) return null;
  const ms = Date.now() - new Date(iso).getTime();
  return Math.floor(ms / 86400000);
}

function formatDate(iso: string | null): string {
  if (!iso) return "recently";
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

// A fixed-height wrapper in every branch: the region is reserved from first paint,
// so a velocity arriving (or never arriving) cannot shift the card around it.
//
// `truncate` (nowrap + overflow-hidden + ellipsis) is what actually makes that
// true, and min-h-5 alone did not. min-h-5 reserves ONE line, but nothing stopped
// the content from wrapping onto a second: a ready velocity emits the figure, a
// percentile clause and an "as of N days ago" suffix, and measured in Chromium
// that wrapped -- and grew the row by 13px -- at every width at or below 900px,
// which is an ordinary laptop-with-a-sidebar width, not just mobile. The sparkline
// was a red herring here; the text wrapped on its own (32px of the 33px). Pinning
// the region to a single line makes the reserved height hold at every width, and
// the badge is supplementary enough that clipping its tail beats moving the page.
// e2e/velocity-badge-layout.spec.ts measures this in a real browser; jsdom cannot.
function Region({ children }: { children: React.ReactNode }) {
  return (
    <div
      data-testid="citation-velocity-region"
      className="min-h-5 truncate text-xs text-on-surface-variant"
    >
      {children}
    </div>
  );
}

export function CitationVelocityBadge({
  velocity,
  isRetracted,
}: {
  velocity: PaperVelocity | undefined;
  isRetracted: boolean;
}) {
  // Loading or errored: an empty reserved region, deliberately not a shimmer --
  // most papers legitimately have no history, and a shimmer would promise data
  // that is never going to arrive.
  if (!velocity) return <Region>{null}</Region>;

  const age = daysSince(velocity.computed_at);

  if (age !== null && age > SUPPRESS_DAYS) {
    return <Region>Citation trend unavailable</Region>;
  }

  if (velocity.status !== "ready" || velocity.velocity_per_30d === null) {
    return (
      <Region>
        Not enough history yet
        {velocity.first_observed_at && ` · tracking since ${formatDate(velocity.first_observed_at)}`}
      </Region>
    );
  }

  const figure = Math.round(velocity.velocity_per_30d);

  // A tracked paper can legitimately gain nothing in the window. Rendering the
  // figure would produce "0 citations in the last 30 days", which is both a
  // forbidden phrase and actively misleading: it reads as "this paper has zero
  // citations" when the paper may have hundreds and simply gained none. Velocity
  // measures *change*, so at zero the honest statement is about change.
  if (figure === 0) {
    return (
      <Region>
        <span>No change in the last 30 days</span>
        {age !== null && age >= AGING_DAYS && <span> · as of {age} days ago</span>}
      </Region>
    );
  }

  const label = isRetracted ? "citations after retraction" : "citations in the last 30 days";

  return (
    <Region>
      <span className={isRetracted ? "font-semibold text-error" : "font-semibold text-secondary"}>
        {figure}
      </span>{" "}
      <span>{label}</span>{" "}
      {/* Decorative: aria-hidden, and it self-suppresses below 3 points rather than
          drawing a straight segment that would imply a trend from one interval. */}
      <VelocitySparkline points={velocity.recent_counts} />
      {velocity.percentile !== null && (
        <>
          {" · "}
          <span
            tabIndex={0}
            title={`Compared with ${velocity.cohort_size} papers of similar age in this topic`}
          >
            top {100 - velocity.percentile}% for its age in this topic
          </span>
        </>
      )}
      {age !== null && age >= AGING_DAYS && <span> · as of {age} days ago</span>}
    </Region>
  );
}
