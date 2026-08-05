import { createSearchParams, useNavigate } from "react-router-dom";
import { useDeleteSavedSearch, useRunSavedSearch, useSavedSearches } from "../api/hooks";
import type { SavedSearch, SearchParams } from "../api/types";
import { useIdentity } from "../identity/identity";

function toUrlParams(params: SearchParams): Record<string, string> {
  return Object.fromEntries(Object.entries(params).filter(([, v]) => v)) as Record<string, string>;
}

export function SavedSearchesPage() {
  const { userId, error: identityError } = useIdentity();
  const { data, isLoading, isError } = useSavedSearches(userId);
  const runSearch = useRunSavedSearch();
  const deleteSearch = useDeleteSavedSearch();
  const navigate = useNavigate();

  function run(saved: SavedSearch) {
    if (userId === null) return;
    runSearch.mutate(
      { userId, savedSearchId: saved.id },
      {
        onSuccess: () =>
          navigate({ pathname: "/search", search: createSearchParams(toUrlParams(saved.query_params)).toString() }),
      },
    );
  }

  function remove(saved: SavedSearch) {
    if (userId === null) return;
    if (!window.confirm(`Delete "${saved.name}"?`)) return;
    deleteSearch.mutate({ userId, savedSearchId: saved.id });
  }

  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold">Saved searches</h1>
      <p className="mb-6 font-serif text-sm text-on-surface-variant">
        Re-run a saved query against current data, or remove ones you no longer need.
      </p>

      {identityError && (
        <p className="mb-4 rounded border border-error/40 bg-surface-container-lowest p-2 text-xs text-error">
          Couldn't set up your anonymous profile — saved searches are unavailable.
        </p>
      )}
      {isError && (
        <p className="mb-4 rounded border border-error/40 bg-surface-container-lowest p-2 text-xs text-error">
          Couldn't load your saved searches. Try again.
        </p>
      )}
      {(runSearch.isError || deleteSearch.isError) && (
        <p className="mb-4 rounded border border-error/40 bg-surface-container-lowest p-2 text-xs text-error">
          {runSearch.isError ? "Couldn't run that search. Try again." : "Couldn't delete that search. Try again."}
        </p>
      )}
      {isLoading && userId !== null && <p className="text-sm text-on-surface-variant">Loading…</p>}
      {data?.length === 0 && (
        <p className="rounded-lg border border-dashed border-outline-variant p-4 font-serif text-sm text-on-surface-variant">
          Nothing saved yet — run a search and use "Save search" to keep it here.
        </p>
      )}

      {(data ?? []).map((saved) => (
        <div
          key={saved.id}
          className="mb-2 flex items-center justify-between rounded-lg border border-hairline bg-surface-container-lowest p-4"
        >
          <div>
            <p className="text-sm font-bold text-primary-container">{saved.name}</p>
            <p className="text-xs text-on-surface-variant">
              {Object.entries(saved.query_params)
                .filter(([, v]) => v)
                .map(([k, v]) => `${k}: ${v}`)
                .join(" · ") || "No filters"}
            </p>
            <p className="text-xs text-on-surface-variant">
              {saved.last_run_at ? `Last run ${saved.last_run_at.slice(0, 10)}` : "Never run"}
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => run(saved)}
              className="rounded bg-secondary px-3 py-1.5 text-xs font-semibold text-on-secondary"
            >
              Run
            </button>
            <button
              onClick={() => remove(saved)}
              className="rounded border border-outline-variant px-3 py-1.5 text-xs font-semibold text-on-surface-variant"
            >
              Delete
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
