from dataclasses import dataclass
from datetime import datetime, timedelta

WINDOW_DAYS = 7
# Eight complete prior weeks are required before a topic gets a trend score (FR-C-003).
BASELINE_WINDOWS = 8


@dataclass(frozen=True)
class Window:
    """A half-open interval: start < detected_at <= end."""

    start: datetime
    end: datetime


def _midnight_utc(value: datetime) -> datetime:
    return datetime(value.year, value.month, value.day)


def window_for(as_of: datetime, index: int) -> Window:
    """The window `index` weeks back from the run day. Index 0 is the current window.

    Day-aligned on purpose: the run's clock time is discarded so two runs on the same day
    produce identical boundaries, which is what makes the daily job idempotent.
    """
    end = _midnight_utc(as_of) - timedelta(days=index * WINDOW_DAYS)
    return Window(start=end - timedelta(days=WINDOW_DAYS), end=end)


def baseline_windows(as_of: datetime) -> list[Window]:
    """The eight windows immediately preceding the current one, newest first.

    Starts at index 1: the current window is never part of its own baseline, or every
    topic would be compared against itself and the ratio would collapse toward 1.
    """
    return [window_for(as_of, index) for index in range(1, BASELINE_WINDOWS + 1)]
