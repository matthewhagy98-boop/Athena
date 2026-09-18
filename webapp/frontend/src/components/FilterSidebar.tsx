import { useEffect, useId, useState } from "react";
import type { SearchParams } from "../api/types";
import type { TopicRef } from "../api/types";

// The fields this panel owns. `q` is deliberately absent: it belongs to the search
// box above the results, and counting it would report a filter this panel cannot
// clear.
const FILTER_KEYS = ["topic_id", "tier", "study_type", "date_from", "date_to"] as const;

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
  // Collapsed by default, and only ever collapsible below `md` -- above it the panel
  // is a permanent sidebar and this state has no effect on what renders.
  const [open, setOpen] = useState(false);
  const panelId = useId();

  // Counted from the APPLIED params, not the draft: this describes what is filtering
  // the results, not what the user is part-way through choosing. Without it,
  // collapsing by default would hide the fact that filters are active at all.
  const appliedCount = FILTER_KEYS.filter((key) => value[key]).length;

  useEffect(() => {
    setDraft(value);
  }, [value]);

  function apply() {
    onApply(draft);
    // On mobile you tapped Apply to see the effect; leaving the panel open would
    // leave you looking at the form instead of the results it just changed.
    setOpen(false);
  }

  function set<K extends keyof SearchParams>(key: K, v: SearchParams[K]) {
    setDraft((d) => ({ ...d, [key]: v || undefined }));
  }

  return (
    // w-52 is a column width, and it only makes sense beside the results. Stacked
    // above them below `md` it becomes full width, and the divider moves to the
    // edge the two panels actually meet on.
    <aside className="w-full shrink-0 border-b border-hairline bg-surface-container-lowest p-4 md:w-52 md:border-b-0 md:border-r">
      {/* The heading is the whole affordance on desktop, where the panel is always
          open; below `md` the toggle takes its place. */}
      <p className="mb-3 hidden text-xs font-semibold uppercase tracking-wider text-on-surface-variant md:block">
        Filters
      </p>

      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={panelId}
        // The accessible name carries the count; the badge beside it is the same
        // information for sighted users, so it is aria-hidden rather than read twice.
        aria-label={appliedCount > 0 ? `Filters, ${appliedCount} applied` : "Filters"}
        className="flex w-full items-center gap-2 text-xs font-semibold uppercase tracking-wider text-on-surface-variant md:hidden"
      >
        <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
          {open ? "expand_less" : "expand_more"}
        </span>
        Filters
        {appliedCount > 0 && (
          <span
            aria-hidden="true"
            className="rounded-full bg-secondary-container px-1.5 text-[11px] font-semibold normal-case tracking-normal text-on-secondary-container"
          >
            {appliedCount}
          </span>
        )}
      </button>

      <div id={panelId} className={`${open ? "block" : "hidden"} mt-3 md:mt-0 md:block`}>
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
          onClick={apply}
          className="w-full rounded bg-primary-container py-1.5 text-xs font-semibold text-on-primary"
        >
          Apply filters
        </button>
      </div>
    </aside>
  );
}
