import { useState } from "react";
import type { SearchParams } from "../api/types";
import type { TopicRef } from "../api/types";

const TIERS = ["established", "emerging", "speculative"];
const STUDY_TYPES = [
  "meta_analysis",
  "systematic_review",
  "rct",
  "cohort",
  "case_control",
  "case_series",
  "opinion_editorial",
  "unknown",
];

export function FilterSidebar({
  topics,
  value,
  onApply,
}: {
  topics: TopicRef[];
  value: SearchParams;
  onApply: (params: SearchParams) => void;
}) {
  const [draft, setDraft] = useState<SearchParams>(value);

  function set<K extends keyof SearchParams>(key: K, v: SearchParams[K]) {
    setDraft((d) => ({ ...d, [key]: v || undefined }));
  }

  return (
    <aside className="w-52 shrink-0 border-r border-hairline bg-surface-container-lowest p-4">
      <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">Filters</p>

      <label className="mb-1 block text-xs font-medium text-on-surface-variant" htmlFor="filter-topic">Topic</label>
      <select
        id="filter-topic"
        className="mb-3 w-full rounded border border-outline-variant p-1.5 text-xs"
        value={draft.topic_id ?? ""}
        onChange={(e) => set("topic_id", e.target.value)}
      >
        <option value="">All topics</option>
        {topics.map((t) => (
          <option key={t.id} value={t.id}>{t.canonical_label}</option>
        ))}
      </select>

      <label className="mb-1 block text-xs font-medium text-on-surface-variant" htmlFor="filter-tier">Evidence tier</label>
      <select
        id="filter-tier"
        className="mb-3 w-full rounded border border-outline-variant p-1.5 text-xs"
        value={draft.tier ?? ""}
        onChange={(e) => set("tier", e.target.value)}
      >
        <option value="">All tiers</option>
        {TIERS.map((t) => (
          <option key={t} value={t}>{t}</option>
        ))}
      </select>

      <label className="mb-1 block text-xs font-medium text-on-surface-variant" htmlFor="filter-study-type">Study type</label>
      <select
        id="filter-study-type"
        className="mb-3 w-full rounded border border-outline-variant p-1.5 text-xs"
        value={draft.study_type ?? ""}
        onChange={(e) => set("study_type", e.target.value)}
      >
        <option value="">All types</option>
        {STUDY_TYPES.map((t) => (
          <option key={t} value={t}>{t.replace(/_/g, " ")}</option>
        ))}
      </select>

      <label className="mb-1 block text-xs font-medium text-on-surface-variant" htmlFor="filter-date-from">Published after</label>
      <input
        id="filter-date-from"
        type="date"
        className="mb-3 w-full rounded border border-outline-variant p-1.5 text-xs"
        value={draft.date_from ?? ""}
        onChange={(e) => set("date_from", e.target.value)}
      />

      <label className="mb-1 block text-xs font-medium text-on-surface-variant" htmlFor="filter-date-to">Published before</label>
      <input
        id="filter-date-to"
        type="date"
        className="mb-4 w-full rounded border border-outline-variant p-1.5 text-xs"
        value={draft.date_to ?? ""}
        onChange={(e) => set("date_to", e.target.value)}
      />

      <button
        onClick={() => onApply(draft)}
        className="w-full rounded bg-primary-container py-1.5 text-xs font-semibold text-on-primary"
      >
        Apply filters
      </button>
    </aside>
  );
}
