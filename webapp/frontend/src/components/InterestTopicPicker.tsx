import { useState } from "react";
import { ApiError } from "../api/client";
import { useAddInterest } from "../api/hooks";
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
  const { userId } = useIdentity();
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
          disabled={addInterest.isPending}
        />
        <button
          type="button"
          onClick={submit}
          disabled={addInterest.isPending || !freeText.trim()}
          className="rounded bg-secondary px-3 py-1.5 text-xs font-semibold text-on-secondary disabled:opacity-50"
        >
          {addInterest.isPending ? "Adding…" : "Add"}
        </button>
      </div>
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
