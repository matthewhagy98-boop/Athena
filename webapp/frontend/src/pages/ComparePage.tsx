import { useSearchParams } from "react-router-dom";
import { useComparePapers, useCompareTopics, useTopics } from "../api/hooks";
import { EvidenceIndicator } from "../components/EvidenceIndicator";

function UnresolvedNotice({ ids }: { ids: string[] }) {
  if (ids.length === 0) return null;
  return (
    <p className="mb-4 rounded border border-outline-variant bg-surface-container-low p-2 text-xs text-on-surface-variant">
      {ids.length} id(s) could not be found and were left out of this comparison.
    </p>
  );
}

export function ComparePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const paperIds = searchParams.getAll("paper_ids");
  const topicIds = searchParams.getAll("topic_ids");

  const papers = useComparePapers(paperIds);
  const topicsCompare = useCompareTopics(topicIds);
  const { data: allTopics } = useTopics();

  if (paperIds.length === 0 && topicIds.length === 0) {
    return (
      <div>
        <h1 className="mb-4 text-2xl font-semibold">Compare</h1>
        <p className="font-serif text-sm text-on-surface-variant">
          Select papers from Search using the checkboxes, or add a topic from its detail page, to build a comparison.
        </p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="mb-4 text-2xl font-semibold">Compare</h1>

      {paperIds.length > 0 && (
        <>
          {papers.isLoading && <p className="text-sm text-on-surface-variant">Loading comparison…</p>}
          {papers.isError && (
            <p className="text-sm text-error">Couldn't load this comparison. Try again.</p>
          )}
          {papers.data && (
            <>
              <UnresolvedNotice ids={papers.data.unresolved_ids} />
              <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-4">
                {papers.data.rows.map((row) => (
                  <div key={row.paper.id} className="rounded-lg border border-hairline bg-surface-container-lowest p-4">
                    <p className="mb-2 text-sm font-bold text-primary-container">{row.paper.title}</p>
                    {row.paper.pub_date && (
                      <p className="mb-2 text-xs text-on-surface-variant">{row.paper.pub_date}</p>
                    )}
                    {row.score ? (
                      <div className="mb-2 flex items-center gap-2 text-xs">
                        <span className="rounded bg-secondary-container px-1.5 font-semibold text-on-secondary-container">
                          {row.score.evidence_tier}
                        </span>
                        <span>{row.score.study_type?.replace(/_/g, " ") ?? "—"}</span>
                        <EvidenceIndicator finalScore={row.score.final_score} />
                      </div>
                    ) : (
                      <p className="mb-2 text-xs text-on-surface-variant">Not yet scored</p>
                    )}
                    {row.paper.abstract && (
                      <p className="font-serif text-sm leading-relaxed text-on-surface-variant">{row.paper.abstract}</p>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}

      {topicIds.length > 0 && (
        <>
          {topicsCompare.isLoading && <p className="text-sm text-on-surface-variant">Loading comparison…</p>}
          {topicsCompare.isError && (
            <p className="text-sm text-error">Couldn't load this comparison. Try again.</p>
          )}
          {topicsCompare.data && (
            <>
              <UnresolvedNotice ids={topicsCompare.data.unresolved_ids} />
              <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-4">
                {topicsCompare.data.rows.map((row) => (
                  <div key={row.topic.id} className="rounded-lg border border-hairline bg-surface-container-lowest p-4">
                    <p className="mb-2 text-sm font-bold text-primary-container">{row.topic.canonical_label}</p>
                    {row.consensus ? (
                      <p className="font-serif text-sm leading-relaxed text-on-surface-variant">
                        {row.consensus.consensus_text}
                      </p>
                    ) : (
                      <p className="text-xs text-on-surface-variant">No consensus snapshot yet.</p>
                    )}
                  </div>
                ))}
              </div>
              <div className="mt-4">
                <label className="mr-2 text-xs font-medium text-on-surface-variant" htmlFor="add-topic">
                  Add topic
                </label>
                <select
                  id="add-topic"
                  className="rounded border border-outline-variant p-1.5 text-xs"
                  value=""
                  onChange={(e) => {
                    if (!e.target.value) return;
                    const next = new URLSearchParams(searchParams);
                    next.append("topic_ids", e.target.value);
                    setSearchParams(next);
                  }}
                >
                  <option value="">Choose a topic…</option>
                  {(allTopics ?? [])
                    .filter((t) => !topicIds.includes(t.id))
                    .map((t) => (
                      <option key={t.id} value={t.id}>{t.canonical_label}</option>
                    ))}
                </select>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
