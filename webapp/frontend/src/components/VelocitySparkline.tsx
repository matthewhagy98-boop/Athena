import { Line, LineChart, ResponsiveContainer } from "recharts";

const TEAL = "#006a61";

export function VelocitySparkline({ points }: { points: number[] }) {
  // Below three points a "line" is a single straight segment, which implies a trend
  // from one interval. Better to draw nothing than to imply a shape that isn't there.
  if (points.length < 3) return null;

  const data = points.map((value, index) => ({ index, value }));
  return (
    <span aria-hidden="true" className="inline-block h-5 w-20 align-middle">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <Line type="monotone" dataKey="value" stroke={TEAL} strokeWidth={1.5} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </span>
  );
}
