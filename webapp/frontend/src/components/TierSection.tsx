import type { PaperRow } from "../api/types";
import { ResearchCard } from "./ResearchCard";

export function TierSection({
  title,
  papers,
  emptyMessage,
  selectedIds,
  onToggleSelect,
}: {
  title: string;
  papers: PaperRow[];
  emptyMessage: string;
  selectedIds: Set<string>;
  onToggleSelect: (paperId: string) => void;
}) {
  return (
    <section className="mb-4">
      <p className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
        {title}
        <span className="h-px flex-1 bg-hairline" />
        <span className="normal-case tracking-normal">
          {papers.length} paper{papers.length === 1 ? "" : "s"}
        </span>
      </p>
      {papers.length === 0 ? (
        <div className="rounded-lg border border-dashed border-outline-variant px-4 py-2.5 font-serif text-sm text-on-surface-variant">
          {emptyMessage}
        </div>
      ) : (
        papers.map((row) => (
          <ResearchCard key={row.paper.id} row={row} checked={selectedIds.has(row.paper.id)} onToggleSelect={onToggleSelect} />
        ))
      )}
    </section>
  );
}
