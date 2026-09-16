import { ApiError } from "../api/client";
import { useSynthesis } from "../api/hooks";
import { useIdentity } from "../identity/identity";
import type { SynthesisClaim } from "../api/types";

// Citation indices are positions in the backend's canonical UUID-sorted member order
// (`subject_ids`), not positions in the order the Compare grid displays cards
// (`paperIds`, selection order). The two orders coincide only by accident, so a
// citation must be resolved through subject_ids and re-indexed into paperIds before
// it is safe to display. An index that is out of range, or a subject id that isn't
// among the currently displayed cards, is dropped rather than rendered as
// undefined/NaN.
function resolveCitationPositions(
  citations: number[],
  subjectIds: string[],
  paperIds: string[],
): number[] {
  const positions: number[] = [];
  for (const index of citations) {
    if (index < 0 || index >= subjectIds.length) continue;
    const paperId = subjectIds[index];
    const displayIndex = paperIds.indexOf(paperId);
    if (displayIndex === -1) continue;
    positions.push(displayIndex + 1);
  }
  return positions;
}

function ClaimRow({
  claim,
  subjectIds,
  paperIds,
}: {
  claim: SynthesisClaim;
  subjectIds: string[];
  paperIds: string[];
}) {
  const positions = resolveCitationPositions(claim.citations, subjectIds, paperIds);
  return (
    <li className="text-xs text-on-surface-variant">
      {claim.text}
      {positions.length > 0 && (
        <>
          {" "}
          <span className="text-secondary">[{positions.join(", ")}]</span>
        </>
      )}
    </li>
  );
}

export function SynthesisPanel({ paperIds }: { paperIds: string[] }) {
  const { userId } = useIdentity();
  const synthesis = useSynthesis();
  const result = synthesis.data;

  const isUnavailable = synthesis.error instanceof ApiError && synthesis.error.status === 503;

  return (
    <section className="mb-6 rounded-lg border border-hairline bg-surface-container-lowest p-4">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
          AI comparison synthesis
        </p>
        <button
          onClick={() => synthesis.mutate({ paperIds, userId })}
          disabled={synthesis.isPending || paperIds.length === 0}
          className="rounded bg-secondary px-3 py-1.5 text-xs font-semibold text-on-secondary disabled:opacity-50"
        >
          {synthesis.isPending ? "Generating…" : "Generate synthesis"}
        </button>
      </div>

      {synthesis.isError && isUnavailable && (
        <p className="text-sm text-error">Synthesis is not available right now. Try again later.</p>
      )}

      {synthesis.isError && !isUnavailable && (
        <p className="text-sm text-error">Couldn't generate a synthesis. Try again.</p>
      )}

      {result?.status === "failed" && (
        <p className="text-sm text-on-surface-variant">
          Couldn't produce a grounded summary for these studies. Every claim has to be
          traceable to one of them, and this comparison didn't meet that bar.
        </p>
      )}

      {result?.status === "ready" && (
        <>
          {result.retracted_member_indices.length > 0 && (
            <p className="mb-2 rounded border border-error/40 p-2 text-xs text-error">
              This comparison includes {result.retracted_member_indices.length} retracted
              {result.retracted_member_indices.length === 1 ? " study" : " studies"}
              {/* Naming the count without naming the study tells a researcher something
                  is wrong and gives them no way to find it. These are indices into
                  subject_ids, exactly like citations, so the same resolver applies. */}
              {(() => {
                const positions = resolveCitationPositions(
                  result.retracted_member_indices,
                  result.subject_ids,
                  paperIds,
                );
                return positions.length > 0 ? <> ({positions.join(", ")})</> : null;
              })()}
              .
            </p>
          )}
          <p className="mb-3 font-serif text-sm leading-relaxed text-on-surface">{result.narrative}</p>
          <ul className="space-y-1">
            {result.claims.map((claim, i) => (
              <ClaimRow key={i} claim={claim} subjectIds={result.subject_ids} paperIds={paperIds} />
            ))}
          </ul>
          {/* FR-B-005 makes disagreements a MUST, and they travelled through the tool
              schema, the validator, a DB column, the serializer and the TS interface only
              to be dropped here. Where studies conflict is the most decision-relevant
              thing a comparison can tell a researcher -- more so than where they agree. */}
          {result.disagreements.length > 0 && (
            <div className="mt-3">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
                Points of disagreement
              </p>
              <ul className="space-y-1">
                {result.disagreements.map((d, i) => {
                  const positions = resolveCitationPositions(
                    d.indices,
                    result.subject_ids,
                    paperIds,
                  );
                  return (
                    <li key={i} className="text-xs text-on-surface-variant">
                      {d.description}
                      {positions.length > 0 && (
                        <>
                          {" "}
                          <span className="text-secondary">[{positions.join(" vs ")}]</span>
                        </>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          <p className="mt-3 text-xs text-on-surface-variant">
            Generated from the {result.subject_ids.length} studies compared here. Bracketed
            numbers refer to their position in the comparison below.
          </p>
          {/* Provenance, per spec line 16. A reader weighing AI-written prose needs to
              know which model wrote it and how stale it is. */}
          {result.model_id && (
            <p className="mt-1 text-xs text-on-surface-variant">
              Written by {result.model_id}
              {result.generated_at && <> on {new Date(result.generated_at).toLocaleDateString()}</>}.
              AI-generated; verify against the studies before relying on it.
            </p>
          )}
        </>
      )}
    </section>
  );
}
