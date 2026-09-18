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
    activity_ratio = (counts.event_count + 1) / (baseline_mean + 1)
    volume_weight = math.log10(counts.event_count + 1)
    # Rounded exactly once, at the end, so intermediate precision is not compounded.
    return ScoredTopic(
        counts=counts,
        baseline_mean=baseline_mean,
        baseline_weeks=weeks_tracked,
        trend_score=round(activity_ratio * volume_weight, 3),
        is_newly_tracked=False,
    )


def rank_topics(scored: list[ScoredTopic]) -> list[ScoredTopic]:
    """Rank by trend_score where there is one, by event_count where there is not.

    Newly tracked topics interleave by count rather than being segregated below scored
    ones, so a genuinely busy new topic is not buried under a marginally elevated old one.
    Python's sort is stable, so equal keys preserve input order and the ranking does not
    reshuffle between runs for no reason.
    """
    return sorted(
        scored,
        key=lambda s: s.trend_score if s.trend_score is not None else float(s.counts.event_count),
        reverse=True,
    )
