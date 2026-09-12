import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useSavedSearchVelocity } from "../api/hooks";

const TEAL = "#006a61";

export function SavedSearchVelocityTrend({
  savedSearchId,
  userId,
}: {
  savedSearchId: string;
  userId: string | null;
}) {
  const { data, isError } = useSavedSearchVelocity(savedSearchId, userId);

  if (isError || !data) return null;

  // papers_with_history is a subset of papers_examined (<= the aggregate cap), not
  // of papers_total (the true, unbounded match count) -- see citations/aggregate.py.
  // When the search was truncated (papers_examined < papers_total), reporting "X of
  // papers_total" would overstate what was actually sampled, so fall back to
  // papers_examined as the denominator in that case.
  const truncated =
    typeof data.papers_examined === "number" && data.papers_examined < data.papers_total;
  const coverageLabel = truncated
    ? `${data.papers_with_history} of ${data.papers_examined} examined papers (${data.papers_total} total matches)`
    : `${data.papers_with_history} of ${data.papers_total} papers`;

  if (data.status === "insufficient_coverage") {
    // Say what is missing rather than drawing a line from a handful of papers and
    // letting it read as the whole search.
    return (
      <p className="mt-2 text-xs text-on-surface-variant">
        Citation trend needs more history — {coverageLabel} tracked so far.
      </p>
    );
  }

  return (
    <div className="mt-2">
      <p className="mb-1 text-xs text-on-surface-variant">
        Median citations per 30 days across {coverageLabel}
      </p>
      <div style={{ height: 80 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data.series}>
            <XAxis dataKey="week_start" hide />
            <YAxis hide />
            <Tooltip />
            <Line
              type="monotone"
              dataKey="median_velocity_per_30d"
              stroke={TEAL}
              strokeWidth={1.5}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
