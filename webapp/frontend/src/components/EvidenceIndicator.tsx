export function EvidenceIndicator({ finalScore }: { finalScore: number }) {
  const filled = Math.max(0, Math.min(5, Math.round(finalScore / 20)));
  return (
    <span className="flex gap-0.5" aria-label={`Evidence strength ${filled} of 5`}>
      {Array.from({ length: 5 }, (_, i) => (
        <span
          key={i}
          className={`h-1 w-3.5 rounded ${i < filled ? "bg-secondary" : "bg-surface-container-highest"}`}
        />
      ))}
    </span>
  );
}
