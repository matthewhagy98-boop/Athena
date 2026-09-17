from datetime import datetime

from dashboard.windows import BASELINE_WINDOWS, WINDOW_DAYS, baseline_windows, window_for


def test_current_window_ends_at_midnight_utc_of_the_run_day():
    # The run time's clock time is discarded: windows are day-aligned so two runs on the
    # same day produce identical boundaries, which is what makes the daily job idempotent.
    w = window_for(datetime(2026, 8, 2, 4, 10, 22), 0)

    assert w.end == datetime(2026, 8, 2, 0, 0, 0)
    assert w.start == datetime(2026, 7, 26, 0, 0, 0)


def test_window_index_steps_back_by_whole_weeks():
    w1 = window_for(datetime(2026, 8, 2, 4, 10), 1)

    assert w1.end == datetime(2026, 7, 26, 0, 0, 0)
    assert w1.start == datetime(2026, 7, 19, 0, 0, 0)


def test_windows_do_not_overlap_and_leave_no_gap():
    as_of = datetime(2026, 8, 2, 4, 10)
    w0, w1 = window_for(as_of, 0), window_for(as_of, 1)

    assert w1.end == w0.start


def test_event_at_window_start_boundary_excluded_from_current_window():
    # The half-open rule: window_start < detected_at <= window_end. An event at exactly
    # window_start belongs to the PREVIOUS window. This matches
    # webapp/visualizations.py:51-53 and digest/aggregate.py:52-53 exactly; diverging
    # would make dashboard counts disagree with the topic timeline for the same period,
    # which a user reads as the numbers being wrong rather than as an off-by-one.
    as_of = datetime(2026, 8, 2, 4, 10)
    w0 = window_for(as_of, 0)
    w1 = window_for(as_of, 1)
    boundary = datetime(2026, 7, 26, 0, 0, 0)

    assert not (w0.start < boundary <= w0.end)
    assert w1.start < boundary <= w1.end


def test_event_at_window_end_boundary_included_in_current_window():
    as_of = datetime(2026, 8, 2, 4, 10)
    w0 = window_for(as_of, 0)
    boundary = datetime(2026, 8, 2, 0, 0, 0)

    assert w0.start < boundary <= w0.end


def test_baseline_returns_the_eight_windows_before_the_current_one():
    as_of = datetime(2026, 8, 2, 4, 10)

    windows = baseline_windows(as_of)

    assert len(windows) == BASELINE_WINDOWS == 8
    # Starts at index 1, not 0: the current window is never part of its own baseline, or
    # every topic would be compared against itself and the ratio would collapse toward 1.
    assert windows[0].end == window_for(as_of, 1).end
    assert windows[-1].end == window_for(as_of, 8).end
    assert all(w.end <= window_for(as_of, 0).start for w in windows)


def test_window_length_is_seven_days():
    w = window_for(datetime(2026, 8, 2), 0)

    assert (w.end - w.start).days == WINDOW_DAYS == 7
