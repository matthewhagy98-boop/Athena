import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useCitationHistory } from "../api/hooks";

const TEAL = "#006a61";

export function CitationHistoryChart({ paperId }: { paperId: string }) {
  const { data, isError } = useCitationHistory(paperId);

  // Supplementary: on failure the section disappears rather than shouting.
  if (isError) return null;
  if (!data) return <div className="min-h-[220px]" />;

  if (data.observations.length === 0) {
    return (
      <div className="rounded-lg border border-hairline bg-surface-container-lowest p-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
          Citation history
        </p>
        <p className="font-serif text-sm text-on-surface-variant">Not enough history yet</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-hairline bg-surface-container-lowest p-4">
      <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
        Citation history
      </p>
      <div style={{ height: 220 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data.observations}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="observed_on" tick={{ fontSize: 11 }} />
            <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
            <Tooltip />
            <Line type="monotone" dataKey="citation_count" stroke={TEAL} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2 text-xs text-on-surface-variant">
        Counts as reported by {data.source.replace(/_/g, " ")}. A dip usually reflects a
        provider record merge rather than lost citations.
      </p>
    </div>
  );
}
