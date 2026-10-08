import { Link } from "react-router-dom";
import { useRemoveInterest } from "../api/hooks";
import type { PersonalDashboardResponse } from "../api/types";
import { useIdentity } from "../identity/identity";

export function PersonalTopicsWidget({
  data,
  isLoading,
  isError,
}: {
  data: PersonalDashboardResponse | undefined;
  isLoading: boolean;
  isError: boolean;
}) {
  const { userId } = useIdentity();
  const removeInterest = useRemoveInterest();

  return (
    <section className="rounded-lg border border-hairline bg-surface-container-lowest p-4">
      <h2 className="mb-3 text-sm font-semibold text-on-surface">Your topics</h2>

      {isLoading && <p className="text-xs text-on-surface-variant">Loading…</p>}
      {isError && (
        <p className="text-xs text-error">
          Couldn&apos;t load your topics. The rest of the dashboard is unaffected.
        </p>
      )}

      {/* Deterministic, not model-written (OQ-C-002). Rendered as plain text with no
          "AI" framing, because it is not AI -- claiming otherwise in either direction
          would misrepresent it. */}
      {data?.blurb && (
        <p className="mb-3 font-serif text-sm leading-relaxed text-on-surface">{data.blurb}</p>
      )}

      <ul className="space-y-1">
        {data?.topics.map((row) => (
          <li key={row.topic.id} className="flex items-baseline justify-between gap-2 text-xs">
            <Link
              to={`/topics/${row.topic.id}`}
              className="text-primary-container hover:underline"
            >
              {row.topic.canonical_label}
            </Link>
            <span className="flex items-center gap-2">
              <span className="text-on-surface-variant">
                {/* A quiet topic is listed with a zero count (FR-C-008), not dropped:
                    dropping it would make the widget look like the user has fewer
                    interests than they do, and "no change" is itself information. */}
                {row.event_count === 0
                  ? "No change this week"
                  : `${row.event_count} ${row.event_count === 1 ? "change" : "changes"}`}
              </span>
              <button
                type="button"
                onClick={() => userId && removeInterest.mutate({ userId, topicId: row.topic.id })}
                // Names WHICH topic this removes -- without it, a screen-reader user
                // hears a list of identical "Remove" buttons.
                aria-label={`Remove ${row.topic.canonical_label}`}
                className="text-on-surface-variant hover:text-error"
              >
                <span className="material-symbols-outlined text-[14px]" aria-hidden="true">
                  close
                </span>
              </button>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
