import { Link } from "react-router-dom";
import type { ActivityResponse } from "../api/types";

// FR-C-016: the ranking measures how much new evidence was indexed, which is not a claim
// about whether that evidence matters. The tooltip is the only thing standing between the
// list and being read as an editorial judgement.
const EXPLANATION =
  "Ranked by volume of newly indexed and changed evidence in the last 7 days, not by scientific significance.";

export function ActivityWidget({
  data,
  isLoading,
  isError,
}: {
  data: ActivityResponse | undefined;
  isLoading: boolean;
  isError: boolean;
}) {
  return (
    <section className="rounded-lg border border-hairline bg-surface-container-lowest p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-on-surface">Most active topics</h2>
        <span
          tabIndex={0}
          title={EXPLANATION}
          className="text-xs text-on-surface-variant underline decoration-dotted"
        >
          What does this mean?
        </span>
      </div>

      {isLoading && <p className="text-xs text-on-surface-variant">Loading…</p>}
      {isError && (
        <p className="text-xs text-error">
          Couldn&apos;t load topic activity. The rest of the dashboard is unaffected.
        </p>
      )}

      {data && data.topics.length === 0 && !isLoading && (
        <p className="text-xs text-on-surface-variant">
          No topic reached the activity threshold this week.
        </p>
      )}

      <ol className="space-y-2">
        {data?.topics.map((row) => (
          <li key={row.topic.id} className="flex items-baseline gap-2 text-xs">
            <span className="w-5 text-on-surface-variant">{row.rank}.</span>
            <Link
              to={`/topics/${row.topic.id}`}
              className="font-medium text-primary-container hover:underline"
            >
              {row.topic.canonical_label}
            </Link>
            {/* The raw count is always shown (FR-C-004): a derived score alone is
                unauditable, since the reader cannot tell 24 events from 5. */}
            <span className="text-on-surface-variant">
              {row.event_count} {row.event_count === 1 ? "change" : "changes"}
            </span>
            {row.is_newly_tracked && (
              // "Newly tracked", never "new topic" -- the topic may be decades old; it is
              // our tracking of it that is new.
              <span className="rounded bg-surface-container px-1.5 text-on-surface-variant">
                Newly tracked
              </span>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
