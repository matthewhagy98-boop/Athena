import math
import uuid

from dashboard.trend import MIN_EVENTS, TopicCounts, is_eligible, rank_topics, score_topic

ID_A = uuid.UUID("9c1e77a2-4b3d-4f18-9a2b-6d5e4c3b2a10")
ID_B = uuid.UUID("2f8b41c7-9d0e-4a55-b731-8c6f5e4d3a29")


def _counts(topic_id=ID_A, event_count=24, **kw):
    base = dict(new_paper=event_count, consensus_updated=0, contradiction_flagged=0,
                paper_retracted=0)
    base.update(kw)
    return TopicCounts(topic_id=topic_id, event_count=event_count, **base)


def test_trend_score_matches_worked_example():
    # Spec 14.1's worked example, asserted exactly.
    #   b = (6+9+4+11+8+7+5+9)/8 = 7.375
    #   activity_ratio = 25 / 8.375 = 2.98507...
    #   volume_weight  = log10(25)  = 1.39794...
    #   trend_score    = round(4.17307..., 3) = 4.173
    scored = score_topic(_counts(event_count=24), [6, 9, 4, 11, 8, 7, 5, 9], weeks_tracked=8)

    assert scored.trend_score == 4.173
    assert scored.baseline_mean == 7.375
    assert scored.is_newly_tracked is False


def test_zero_baseline_does_not_divide_by_zero():
    # The +1 smoothing in numerator and denominator removes the division a raw c/b would
    # hit for any topic with a silent baseline -- the most common case in a young corpus.
    #   (10+1)/(0+1) * log10(11) = 11 * 1.04139... = 11.455
    scored = score_topic(_counts(event_count=10), [0] * 8, weeks_tracked=8)

    assert scored.trend_score == round(11 * math.log10(11), 3) == 11.455


def test_topic_below_five_events_is_ineligible():
    assert is_eligible(MIN_EVENTS) is True
    assert is_eligible(MIN_EVENTS - 1) is False
    assert MIN_EVENTS == 5


def test_fewer_than_eight_weeks_yields_no_score():
    scored = score_topic(_counts(event_count=9), [3, 4, 2], weeks_tracked=3)

    assert scored.trend_score is None
    assert scored.baseline_mean is None
    assert scored.is_newly_tracked is True
    assert scored.baseline_weeks == 3


def test_exactly_eight_weeks_yields_a_score():
    # The boundary is >= 8, not > 8.
    scored = score_topic(_counts(event_count=10), [1] * 8, weeks_tracked=8)

    assert scored.trend_score is not None
    assert scored.is_newly_tracked is False


def test_an_absent_prior_window_counts_as_zero_not_as_a_skipped_term():
    # Absence genuinely means no activity, so it must drag the mean down rather than be
    # dropped from the denominator.
    with_gap = score_topic(_counts(event_count=10), [8, 0, 8, 0, 8, 0, 8, 0], weeks_tracked=8)

    assert with_gap.baseline_mean == 4.0


def test_ranking_is_by_score_descending():
    high = score_topic(_counts(topic_id=ID_A, event_count=24), [1] * 8, weeks_tracked=8)
    low = score_topic(_counts(topic_id=ID_B, event_count=6), [5] * 8, weeks_tracked=8)

    ranked = rank_topics([low, high])

    assert [s.counts.topic_id for s in ranked] == [ID_A, ID_B]


def test_a_busy_newly_tracked_topic_is_not_buried_below_a_marginal_old_one():
    # Newly tracked topics interleave by event count rather than being segregated to the
    # bottom, so a genuinely busy new topic outranks a barely-elevated established one.
    marginal_old = score_topic(_counts(topic_id=ID_A, event_count=6), [5] * 8, weeks_tracked=8)
    busy_new = score_topic(_counts(topic_id=ID_B, event_count=40), [], weeks_tracked=0)

    ranked = rank_topics([marginal_old, busy_new])

    assert ranked[0].counts.topic_id == ID_B


def test_ranking_is_stable_for_equal_keys():
    # Two topics with identical activity must not swap order between runs, or the
    # dashboard appears to reshuffle for no reason.
    a = score_topic(_counts(topic_id=ID_A, event_count=10), [2] * 8, weeks_tracked=8)
    b = score_topic(_counts(topic_id=ID_B, event_count=10), [2] * 8, weeks_tracked=8)

    assert [s.counts.topic_id for s in rank_topics([a, b])] == [ID_A, ID_B]
    assert [s.counts.topic_id for s in rank_topics([b, a])] == [ID_B, ID_A]


def test_breakdown_counts_are_carried_through_untouched():
    counts = _counts(event_count=24, new_paper=19, consensus_updated=2,
                     contradiction_flagged=2, paper_retracted=1)

    scored = score_topic(counts, [1] * 8, weeks_tracked=8)

    assert scored.counts.new_paper == 19
    assert scored.counts.paper_retracted == 1


def test_baseline_weeks_is_reported_on_a_scored_topic_too():
    # Only the unscored branch asserted baseline_weeks, so hardcoding it in the scored
    # return -- to 0, or to BASELINE_WINDOWS, or to anything -- passed the whole file.
    # Task 4 persists this field and the widget renders it as "weeks tracked".
    scored = score_topic(_counts(event_count=24), [6, 9, 4, 11, 8, 7, 5, 9], weeks_tracked=8)

    assert scored.baseline_weeks == 8


def test_the_result_dataclasses_are_immutable():
    # frozen=True on both was unenforced by any test. These are passed between the job,
    # the ranker and the persistence layer; a caller mutating one in place would change
    # a value another step already read.
    import dataclasses

    import pytest as _pytest

    counts = _counts(event_count=10)
    scored = score_topic(counts, [1] * 8, weeks_tracked=8)

    with _pytest.raises(dataclasses.FrozenInstanceError):
        counts.event_count = 99
    with _pytest.raises(dataclasses.FrozenInstanceError):
        scored.trend_score = 99.0
