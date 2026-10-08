const STALE_AFTER_HOURS = 36;

export function StalenessBanner({ computedAt }: { computedAt: string | null }) {
  if (!computedAt) return null;
  const ageHours = (Date.now() - new Date(computedAt).getTime()) / 3_600_000;
  if (ageHours <= STALE_AFTER_HOURS) return null;

  // FR-C-011. The job runs daily, so 36 hours means at least one run was missed. Saying
  // so is the difference between a user distrusting the numbers and distrusting the app.
  return (
    <p role="status" className="mb-4 rounded border border-outline-variant bg-surface-container-low p-2 text-xs text-on-surface-variant">
      Data as of {new Date(computedAt).toLocaleString()} — the daily refresh has not run since.
    </p>
  );
}
