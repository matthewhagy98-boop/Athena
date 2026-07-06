export function CompareTray({ count, onCompare }: { count: number; onCompare: () => void }) {
  if (count === 0) return null;
  return (
    <button
      onClick={onCompare}
      className="fixed bottom-6 right-8 flex items-center gap-2 rounded bg-primary-container px-4 py-2.5 text-xs font-semibold text-on-primary"
    >
      <span className="material-symbols-outlined text-[15px] text-secondary-container">compare_arrows</span>
      Compare ({count})
      <span className="material-symbols-outlined text-[14px] text-secondary-container">arrow_forward</span>
    </button>
  );
}
