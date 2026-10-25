"""Time splits for the SMA replay.

The split is a fixed fraction of the sorted unique candle timestamps.
It is not chosen by looking at profits. Train is the first 60 percent,
validation the next 20 percent, and forward the remainder. One timestamp
is left unscored between train and validation, and another between
validation and forward, so a signal in one period cannot fill on a scored
bar of the next period.

Parameters are not estimated here. The caller passes the already fixed
windows. Earlier closes may warm up a later period's moving average.
Later closes are not passed into that period's replay.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

TRAIN_PERCENT = 60
VALIDATION_PERCENT = 20
GAP_BARS = 1


@dataclass(frozen=True)
class PeriodWindow:
    name: str
    signal_start: datetime
    signal_end: datetime
    fill_end: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "period": self.name,
            "signal_start": _iso(self.signal_start),
            "signal_end": _iso(self.signal_end),
            "fill_end": _iso(self.fill_end),
            "gap_bars": GAP_BARS,
            "train_percent": TRAIN_PERCENT,
            "validation_percent": VALIDATION_PERCENT,
            "parameters_fit_on_period": False,
        }


def plan_splits(timestamps: list[datetime]) -> list[PeriodWindow] | None:
    """Return train, validation, and forward windows, or None if the series is too short."""
    unique = sorted(set(timestamps))
    count = len(unique)
    train_n = (count * TRAIN_PERCENT) // 100
    validation_n = (count * VALIDATION_PERCENT) // 100
    forward_n = count - train_n - validation_n - (2 * GAP_BARS)
    if train_n < 1 or validation_n < 1 or forward_n < 1:
        return None
    gap1 = train_n
    validation_start = train_n + GAP_BARS
    validation_end = validation_start + validation_n - 1
    gap2 = validation_end + 1
    forward_start = gap2 + 1
    if forward_start >= count or gap2 >= count:
        return None
    return [
        PeriodWindow("train", unique[0], unique[train_n - 1], unique[gap1]),
        PeriodWindow("validation", unique[validation_start], unique[validation_end], unique[gap2]),
        PeriodWindow("forward", unique[forward_start], unique[count - 1], unique[count - 1]),
    ]


def full_window(timestamps: list[datetime]) -> PeriodWindow:
    unique = sorted(set(timestamps))
    if not unique:
        raise ValueError("no timestamps to split")
    return PeriodWindow("full_window", unique[0], unique[-1], unique[-1])


def _iso(value: datetime) -> str:
    from sollab.timeutil import iso_z

    return iso_z(value)
