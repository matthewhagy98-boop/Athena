import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useCreateSavedSearch, useSearch, useTopics } from "../api/hooks";
import type { SearchParams } from "../api/types";
import { CompareTray } from "../components/CompareTray";
import { FilterSidebar } from "../components/FilterSidebar";
import { SaveSearchDialog } from "../components/SaveSearchDialog";
import { TierSection } from "../components/TierSection";
import { useIdentity } from "../identity/identity";

const PARAM_KEYS = ["q", "topic_id", "tier", "study_type", "date_from", "date_to"] as const;

function paramsFromUrl(searchParams: URLSearchParams): SearchParams {
  const out: SearchParams = {};
  for (const key of PARAM_KEYS) {
    const v = searchParams.get(key);
    if (v) out[key] = v;
  }
  return out;
}

export function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const params = useMemo(() => paramsFromUrl(searchParams), [searchParams]);
  const [queryDraft, setQueryDraft] = useState(params.q ?? "");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [saveOpen, setSaveOpen] = useState(false);
  const navigate = useNavigate();
  const { userId, error: identityError } = useIdentity();

  const { data, isLoading, isError } = useSearch(params);
  const { data: topics } = useTopics();
  const createSavedSearch = useCreateSavedSearch();

  function applyParams(next: SearchParams) {
    const entries = Object.entries(next).filter(([, v]) => v);
    setSearchParams(Object.fromEntries(entries));
    setSelected(new Set());
  }

  function toggleSelect(paperId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(paperId)) next.delete(paperId);
      else next.add(paperId);
      return next;
    });
  }

  const byTier = useMemo(() => {
    const rows = data?.rows ?? [];
    const pick = (tier: string) => rows.filter((r) => r.score?.evidence_tier === tier);
    return {
      established: pick("established"),
      emerging: pick("emerging"),
      speculative: pick("speculative"),
      unscored: rows.filter((r) => r.score === null),
    };
  }, [data]);

  return (
    <div className="flex gap-6">
      <FilterSidebar topics={topics ?? []} value={params} onApply={(p) => applyParams({ ...p, q: params.q })} />
      <div className="min-w-0 flex-1 pb-20">
        <form
          className="mb-5 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            applyParams({ ...params, q: queryDraft || undefined });
          }}
        >
          <input
            className="flex-1 rounded border border-hairline bg-surface-container-lowest px-3 py-2 text-sm"
            placeholder="Search papers"
            value={queryDraft}
            onChange={(e) => setQueryDraft(e.target.value)}
          />
          <button
            type="button"
            onClick={() => setSaveOpen(true)}
            className="flex items-center gap-1.5 rounded border border-outline-variant bg-surface-container-lowest px-3 text-xs font-semibold"
          >
            <span className="material-symbols-outlined text-[15px]" aria-hidden="true">bookmark_add</span>
            Save search
          </button>
        </form>

        {identityError && (
          <p className="mb-4 rounded border border-error/40 bg-surface-container-lowest p-2 text-xs text-error">
            Couldn't set up your anonymous profile — saved searches are unavailable. Search and compare still work.
          </p>
        )}
        {isError && <p className="text-sm text-error">Search failed. Adjust your query and try again.</p>}
        {isLoading && <p className="text-sm text-on-surface-variant">Loading results…</p>}

        {data && (
          <>
            <TierSection title="Established evidence" papers={byTier.established} emptyMessage="No established papers match the current filters." selectedIds={selected} onToggleSelect={toggleSelect} />
            <TierSection title="Emerging evidence" papers={byTier.emerging} emptyMessage="No emerging papers match the current filters." selectedIds={selected} onToggleSelect={toggleSelect} />
            <TierSection title="Speculation and hypotheses" papers={byTier.speculative} emptyMessage="No speculative papers match the current filters." selectedIds={selected} onToggleSelect={toggleSelect} />
            <TierSection title="Not yet scored" papers={byTier.unscored} emptyMessage="All matching papers have been scored." selectedIds={selected} onToggleSelect={toggleSelect} />
          </>
        )}
      </div>

      <CompareTray
        count={selected.size}
        onCompare={() => navigate(`/compare?${[...selected].map((id) => `paper_ids=${id}`).join("&")}`)}
      />
      <SaveSearchDialog
        open={saveOpen}
        disabled={userId === null || createSavedSearch.isPending}
        onClose={() => setSaveOpen(false)}
        onSave={(name) => {
          if (userId === null) return;
          createSavedSearch.mutate(
            { userId, name, queryParams: params },
            { onSuccess: () => setSaveOpen(false) },
          );
        }}
      />
    </div>
  );
}
