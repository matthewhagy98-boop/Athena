import type { PaperVelocity } from "../api/types";

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
function Region({ children }: { children: React.ReactNode }) {
  return <div className="min-h-5 text-xs text-on-surface-variant">{children}</div>;
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
  const label = isRetracted ? "citations after retraction" : "citations in the last 30 days";

  return (
    <Region>
      <span className={isRetracted ? "font-semibold text-error" : "font-semibold text-secondary"}>
        {figure}
      </span>{" "}
      <span>{label}</span>
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
