import { Link, useParams } from "react-router-dom";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useSearch, useTierDistribution, useTimeline, useTopics } from "../api/hooks";
import { ApiError } from "../api/client";

const TEAL = "#006a61";
const NAVY = "#131b2e";

export function TopicDetailPage() {
  const { topicId } = useParams<{ topicId: string }>();
  const id = topicId ?? "";
  const { data: topics } = useTopics();
  const distribution = useTierDistribution(id);
  const timeline = useTimeline(id);
  const papers = useSearch({ topic_id: id });

  const topicName = topics?.find((t) => t.id === id)?.canonical_label ?? "Topic";

  if (distribution.error instanceof ApiError && distribution.error.status === 404) {
    return <p className="text-sm text-on-surface-variant">Topic not found.</p>;
  }

  // Any non-404 failure across the three topic queries: the charts and table would
  // otherwise render empty, which reads as "no data" rather than "request failed".
  if (distribution.isError || timeline.isError || papers.isError) {
    return <p className="text-sm text-error">Couldn't load this topic. Try again.</p>;
  }

  if (distribution.isLoading) {
    return <p className="text-sm text-on-surface-variant">Loading topic…</p>;
  }

  const distData = distribution.data
    ? [
        { tier: "Established", count: distribution.data.established },
        { tier: "Emerging", count: distribution.data.emerging },
        { tier: "Speculative", count: distribution.data.speculative },
      ]
    : [];

  const timelineByDay = (timeline.data ?? []).reduce<Record<string, Record<string, number | string>>>(
    (acc, bucket) => {
      acc[bucket.bucket_date] ??= { bucket_date: bucket.bucket_date };
      acc[bucket.bucket_date][bucket.event_type] = bucket.count;
      return acc;
    },
    {},
  );
  const timelineData = Object.values(timelineByDay);
  const eventTypes = [...new Set((timeline.data ?? []).map((b) => b.event_type))];

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{topicName}</h1>
        <Link
          to={`/compare?topic_ids=${id}`}
          className="flex items-center gap-1.5 rounded border border-outline-variant bg-surface-container-lowest px-3 py-1.5 text-xs font-semibold"
        >
          <span className="material-symbols-outlined text-[15px]" aria-hidden="true">compare_arrows</span>
          Add to compare
        </Link>
      </div>

      <div className="mb-8 grid grid-cols-[repeat(auto-fit,minmax(320px,1fr))] gap-4">
        <div className="rounded-lg border border-hairline bg-surface-container-lowest p-4">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
            Evidence tier distribution
          </p>
          <div style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={distData}>
                <XAxis dataKey="tier" tick={{ fontSize: 12 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="count" fill={TEAL} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-lg border border-hairline bg-surface-container-lowest p-4">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
            Change timeline (90 days)
          </p>
          <div style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={timelineData}>
                <XAxis dataKey="bucket_date" tick={{ fontSize: 11 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                <Tooltip />
                {eventTypes.map((eventType, i) => (
                  <Bar key={eventType} dataKey={eventType} stackId="events" fill={i % 2 === 0 ? TEAL : NAVY} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">Papers</p>
      <div className="overflow-hidden rounded-lg border border-hairline bg-surface-container-lowest">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-hairline text-left text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
              <th className="p-3">Title</th>
              <th className="p-3">Tier</th>
              <th className="p-3">Study type</th>
              <th className="p-3">Published</th>
            </tr>
          </thead>
          <tbody>
            {(papers.data?.rows ?? []).map((row) => (
              <tr key={row.paper.id} className="border-b border-surface-container-low">
                <td className="p-3 font-medium text-primary-container">{row.paper.title}</td>
                <td className="p-3">{row.score?.evidence_tier ?? "pending"}</td>
                <td className="p-3">{row.score?.study_type?.replace(/_/g, " ") ?? "—"}</td>
                <td className="p-3">{row.paper.pub_date ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {papers.data?.rows.length === 0 && (
          <p className="p-4 font-serif text-sm text-on-surface-variant">No papers for this topic yet.</p>
        )}
      </div>
    </div>
  );
}
