import { Link } from "react-router-dom";
import type { PaperRow } from "../api/types";
import { EvidenceIndicator } from "./EvidenceIndicator";

export function ResearchCard({
  row,
  checked,
  onToggleSelect,
}: {
  row: PaperRow;
  checked: boolean;
  onToggleSelect: (paperId: string) => void;
}) {
  return (
    <div className="mb-2 flex gap-3 rounded-lg border border-hairline bg-surface-container-lowest p-4">
      <input
        type="checkbox"
        checked={checked}
        onChange={() => onToggleSelect(row.paper.id)}
        className="mt-1 h-4 w-4 shrink-0 accent-secondary"
        aria-label={`Select ${row.paper.title}`}
      />
      <div className="min-w-0">
        <p className="mb-1 text-sm font-bold text-primary-container">{row.paper.title}</p>
        {row.paper.abstract && (
          <p className="mb-2 line-clamp-2 font-serif text-sm leading-relaxed text-on-surface-variant">
            {row.paper.abstract}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3 text-xs">
          {row.score && (
            <span className="rounded bg-secondary-container px-1.5 font-semibold text-on-secondary-container">
              {row.score.study_type?.replace(/_/g, " ") ?? "—"}
            </span>
          )}
          {row.paper.pub_date && <span className="text-on-surface-variant">{row.paper.pub_date}</span>}
          {row.score && <EvidenceIndicator finalScore={row.score.final_score} />}
          {row.topics.map((topic) => (
            <Link key={topic.id} to={`/topics/${topic.id}`} className="font-semibold text-secondary hover:underline">
              {topic.canonical_label}
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
