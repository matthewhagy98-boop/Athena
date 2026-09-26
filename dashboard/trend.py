import math
import uuid
from dataclasses import dataclass

from dashboard.windows import BASELINE_WINDOWS

# A topic below this never appears in the ranking (FR-C-002). Enforced here rather than
# left to the caller, so there is exactly one place the floor can be wrong.
MIN_EVENTS = 5


@dataclass(frozen=True)
class TopicCounts:
    topic_id: uuid.UUID
    event_count: int
    new_paper: int
    consensus_updated: int
    contradiction_flagged: int
    paper_retracted: int


@dataclass(frozen=True)
class ScoredTopic:
    counts: TopicCounts
    baseline_mean: float | None
    baseline_weeks: int
    trend_score: float | None
    is_newly_tracked: bool


def _activity_score(event_count: int, baseline: float) -> float:
    """The scoring formula itself, in one place.

    score_topic and rank_topics both need it -- the first for a topic's real baseline,
    the second for a newly-tracked topic's provisional one -- and they had independently
    typed-out copies. That is precisely the drift the provisional-baseline amendment
    exists to prevent: its whole purpose is keeping scored and newly-tracked topics on
    ONE scale, which two copies of the arithmetic cannot guarantee.

    Laplace smoothing on both sides removes the division by zero a raw c/b would hit for
    any topic with a silent baseline -- the common case in a young corpus. Rounded once,
    at the end, so intermediate precision is not compounded.
    """
    activity_ratio = (event_count + 1) / (baseline + 1)
    volume_weight = math.log10(event_count + 1)
    return round(activity_ratio * volume_weight, 3)


def is_eligible(event_count: int) -> bool:
    return event_count >= MIN_EVENTS


def score_topic(counts: TopicCounts, prior_counts: list[int], weeks_tracked: int) -> ScoredTopic:
    """Score one topic against its own recent history.

    What this measures: the volume of newly indexed and changed evidence for a topic
    relative to that topic's own recent history. A topic can rank highly because an
    adapter backfilled older papers, because one consensus regeneration fired, or because
    retractions were detected -- none of which is a scientific development. It is NOT a
    measure of importance, quality, novelty, or clinical relevance. FR-C-015 and FR-C-016
    exist to stop the interface implying otherwise.
    """
    if weeks_tracked < BASELINE_WINDOWS:
        # Not enough history to compare against. Ranked by raw count instead, and the UI
        # shows no change-versus-baseline figure (FR-C-003, FR-C-004).
        return ScoredTopic(
            counts=counts,
            baseline_mean=None,
            baseline_weeks=weeks_tracked,
            trend_score=None,
            is_newly_tracked=True,
        )

    baseline_mean = sum(prior_counts) / len(prior_counts)
    # Laplace smoothing on both sides: removes the division by zero a raw c/b would hit
    # for any topic with a silent baseline, which is the common case in a young corpus.
    return ScoredTopic(
        counts=counts,
        baseline_mean=baseline_mean,
        baseline_weeks=weeks_tracked,
        trend_score=_activity_score(counts.event_count, baseline_mean),
        is_newly_tracked=False,
    )


def rank_topics(scored: list[ScoredTopic], provisional_baseline: float) -> list[ScoredTopic]:
    """Rank scored and newly-tracked topics together, on one scale.

    A newly-tracked topic has no baseline, so it cannot have a real trend_score. Ranking
    it on raw event_count instead put the two kinds on different scales -- a smoothed
    log-ratio of typically 4-5 against an unbounded integer -- so any newly-tracked topic
    with about 9 events outranked a scored topic with 30. The widget shows raw counts, so
    that read as "9 changes" above "30 changes" under a heading saying Most active topics.

    Instead it is scored with the same formula against `provisional_baseline`: the median
    baseline of the scored topics in this generation. "We do not know this topic's
    history, so assume it is typical."

    This is a RANKING KEY ONLY. FR-C-003 requires trend_score to stay null for a
    newly-tracked topic, and it does -- on the row, in the API, and in the UI. The
    provisional value is never stored or displayed; it exists solely to order the list.

    Python's sort is stable, so equal keys preserve input order and the ranking does not
    reshuffle between runs for no reason.
    """

    def key(topic: ScoredTopic) -> float:
        if topic.trend_score is not None:
            return topic.trend_score
        return _activity_score(topic.counts.event_count, provisional_baseline)

    return sorted(scored, key=key, reverse=True)
