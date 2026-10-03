import { useState } from "react";
import { ApiError } from "../api/client";
import { useAddInterest, useFeatures } from "../api/hooks";
import { useIdentity } from "../identity/identity";

type FeedbackTone = "confirmed" | "error";

interface Feedback {
  tone: FeedbackTone;
  message: string;
}

// POST /interests has five distinct outcomes and they mean genuinely different things to
// the user: 201 (added), 200 (already had it -- not an error), 404 (their stored identity
// is stale, not their input), 429 (well-formed request, try later), and 422 (the one
// outcome that is actually about what they typed). Collapsing these into one error message
// would misrepresent at least three of the five.
export function InterestTopicPicker() {
  const { userId, error: identityError } = useIdentity();
  const { data: features } = useFeatures();
  // Fail closed, matching the sidebar and the root route: only an explicit `true` counts.
  const dashboardEnabled = features?.dashboard_enabled === true;
  // Identity is minted by POST /users/anonymous on first visit. While it is in flight,
  // and permanently if it fails, there is no user to add a topic for.
  const noIdentityYet = userId === null;
  const [freeText, setFreeText] = useState("");
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const addInterest = useAddInterest();

  function submit() {
    const text = freeText.trim();
    if (!text || userId === null || addInterest.isPending) return;

    addInterest.mutate(
      { userId, freeText: text },
      {
        onSuccess: (result) => {
          if (result.created) {
            setFeedback({ tone: "confirmed", message: `Added "${result.topic.canonical_label}" to your topics.` });
            setFreeText("");
            return;
          }
          // 200: nothing went wrong -- the topic was already there.
          setFeedback({
            tone: "confirmed",
            message: `"${result.topic.canonical_label}" is already one of your topics.`,
          });
        },
        onError: (error) => {
          if (error instanceof ApiError && error.status === 404) {
            setFeedback({
              tone: "error",
              message: "We couldn't find your profile. Reloading the page usually fixes this.",
            });
            return;
          }
          if (error instanceof ApiError && error.status === 429) {
            // The request was well-formed and will work later -- never worded as a
            // problem with what was typed.
            setFeedback({
              tone: "error",
              message: "You've added a lot of topics in the last hour. Try again later.",
            });
            return;
          }
          if (error instanceof ApiError && error.status === 422) {
            setFeedback({
              tone: "error",
              message: "We couldn't match that to a research topic. Try a different term.",
            });
            return;
          }
          setFeedback({ tone: "error", message: "Something went wrong adding that topic. Try again." });
        },
      },
    );
  }

  return (
    <section className="rounded-lg border border-hairline bg-surface-container-lowest p-4">
      <label htmlFor="interest-topic-input" className="mb-1 block text-xs font-medium text-on-surface-variant">
        Add a topic to follow
      </label>
      <div className="flex gap-2">
        <input
          id="interest-topic-input"
          className="flex-1 rounded border border-outline-variant p-1.5 text-sm disabled:opacity-50"
          value={freeText}
          onChange={(e) => setFreeText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
          placeholder="e.g. atrial fibrillation"
          disabled={addInterest.isPending || noIdentityYet || !dashboardEnabled}
        />
        <button
          type="button"
          onClick={submit}
          disabled={addInterest.isPending || !freeText.trim() || noIdentityYet || !dashboardEnabled}
          className="rounded bg-secondary px-3 py-1.5 text-xs font-semibold text-on-secondary disabled:opacity-50"
        >
          {addInterest.isPending ? "Adding…" : "Add"}
        </button>
      </div>
      {/* Why the control can be inert, said out loud. Previously the button stayed enabled
          with no identity: the user typed, pressed Add, and absolutely nothing happened --
          no request, no message, no disabled state. `useIdentity().error` was set on
          failure and consumed by nothing.

          The flag-off case is separate and needs its own wording. With DASHBOARD_ENABLED
          off, /#/dashboard stays routable by design and POST /interests returns 404,
          which the 404 branch below reports as a stale profile and tells the user to
          reload -- advice that can never work. The two cases are indistinguishable to the
          client on purpose (that is what the 404 is for), so the picker has to know from
          /features rather than from the response. */}
      {!dashboardEnabled && (
        <p className="mt-2 text-xs text-on-surface-variant" role="status">
          Following topics isn&apos;t available on this deployment.
        </p>
      )}
      {dashboardEnabled && identityError && (
        <p className="mt-2 text-xs text-error" role="alert">
          We couldn&apos;t set up a profile for this browser, so topics can&apos;t be saved.
        </p>
      )}

      {feedback && (
        <p
          role={feedback.tone === "error" ? "alert" : "status"}
          className={`mt-2 text-xs ${feedback.tone === "error" ? "text-error" : "text-on-surface-variant"}`}
        >
          {feedback.message}
        </p>
      )}
    </section>
  );
}
