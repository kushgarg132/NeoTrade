"""Shared walk-forward folds: one fold per calendar test year."""

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date
from typing import Sequence


@dataclass(frozen=True)
class Fold:
    year: int
    train_start: date
    train_end: date   # exclusive
    test_start: date
    test_end: date    # exclusive


def yearly_folds(dates: Sequence[date], min_train_years: int, window_years: int | None = None,
                 purge_days: int = 0, embargo_days: int = 0) -> list[Fold]:
    """One fold per calendar year after the first `min_train_years` years of `dates`.

    Train is [test_start - window_years, test_start), or from the first date when
    `window_years` is None. `purge_days` trading days (from `dates`) are cut off the end
    of train. `embargo_days` trading days are skipped after the earlier test year's end
    that a rolling window starts on.
    ponytail: embargo only trims train_start (a Fold holds one contiguous range), holes inside train are not expressed.
    """
    days = sorted(dates)
    years = sorted({d.year for d in days})
    folds = []
    for year in years[min_train_years:]:
        test_start, test_end = date(year, 1, 1), date(year + 1, 1, 1)
        train_start = days[0] if window_years is None else date(year - window_years, 1, 1)
        train_end = test_start
        if purge_days:
            train_end = days[max(bisect_left(days, test_start) - purge_days, 0)]
        i = bisect_left(days, train_start)
        if embargo_days and window_years is not None and train_start.year > years[0] and i < len(days):
            train_start = days[min(i + embargo_days, len(days) - 1)]
        folds.append(Fold(year, train_start, train_end, test_start, test_end))
    return folds
