import { Link } from "react-router-dom";
import type { ChangeFeedEvent, ChangeFeedResponse } from "../api/types";

// Retractions and contradictions are the highest-signal events and the ones that would
// otherwise be buried: in a typical window `new_paper` outnumbers the other three types
// combined. There is deliberately no type filter in v1 (OQ-C-005) -- this visual
// distinction is what does the work a filter would.
const WARNING_TYPES = new Set(["paper_retracted", "contradiction_flagged"]);

const LABELS: Record<ChangeFeedEvent["event_type"], string> = {
  new_paper: "New paper",
  consensus_updated: "Consensus updated",
  contradiction_flagged: "Contradiction flagged",
  paper_retracted: "Retracted",
};

function EventRow({ event }: { event: ChangeFeedEvent }) {
  const isWarning = WARNING_TYPES.has(event.event_type);
  return (
    <li className="flex items-baseline gap-2 text-xs">
      <span
        className={
          isWarning
            ? "shrink-0 rounded border border-error/40 px-1.5 font-semibold text-error"
            : "shrink-0 rounded bg-surface-container px-1.5 text-on-surface-variant"
        }
      >
        {LABELS[event.event_type]}
      </span>
      {/* Links to the TOPIC, not the paper: sub-project A gives papers no detail route,
          and FR-C-012 requires every row to reach a real destination. */}
      <Link to={`/topics/${event.topic.id}`} className="text-primary-container hover:underline">
        {event.topic.canonical_label}
      </Link>
      {event.paper && <span className="text-on-surface-variant">{event.paper.title}</span>}
    </li>
  );
}

export function ChangeFeedWidget({
  data,
  isLoading,
  isError,
}: {
  data: ChangeFeedResponse | undefined;
  isLoading: boolean;
  isError: boolean;
}) {
  return (
    <section className="rounded-lg border border-hairline bg-surface-container-lowest p-4">
      <h2 className="mb-3 text-sm font-semibold text-on-surface">What changed</h2>

      {isLoading && <p className="text-xs text-on-surface-variant">Loading…</p>}
      {/* Rendered here rather than thrown: one endpoint failing must not blank the
          dashboard, so every widget owns its own error surface. */}
      {isError && (
        <p className="text-xs text-error">
          Couldn&apos;t load recent changes. The rest of the dashboard is unaffected.
        </p>
      )}

      {data && data.total_events === 0 && !isLoading && (
        // "No change", never "no results" (FR-C-015).
        <p className="text-xs text-on-surface-variant">No change recorded in this period.</p>
      )}

      <div className="space-y-3">
        {data?.days.map((day) => (
          <div key={day.date}>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
              {new Date(`${day.date}T00:00:00Z`).toLocaleDateString(undefined, {
                day: "numeric",
                month: "short",
                timeZone: "UTC",
              })}
            </p>
            <ul className="space-y-1">
              {day.events.map((event, index) => (
                <EventRow key={`${event.detected_at}-${index}`} event={event} />
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
