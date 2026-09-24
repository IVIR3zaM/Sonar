"""Pure geometry for the dashboard's inline SVG charts (SPEC §12).

The macros in templates/components/charts.html only draw; every coordinate
is computed here so it can be tested without parsing SVG.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sonar.display import display_date


@dataclass(frozen=True)
class Runway:
    limit_x: int
    zero_x: int
    balance_x: int
    band_start_x: int
    band_end_x: int


def runway(limit: int, balance: int, worst: int, best: int, width: int) -> Runway:
    """Place the overdraft limit, zero, balance and projected band on one axis.

    The axis spans every value shown, so a projection below the limit or a
    balance far above zero still fits inside [0, width].
    """
    low = min(limit, 0, balance, worst, best)
    high = max(limit, 0, balance, worst, best)
    span = high - low

    def x(cents: int) -> int:
        if span == 0:
            return 0
        return round((cents - low) * width / span)

    band_start, band_end = sorted((x(worst), x(best)))
    return Runway(x(limit), x(0), x(balance), band_start, band_end)


def columns(values: Sequence[int], height: int) -> list[int]:
    """Column heights, with the largest magnitude filling `height`."""
    return _scale(values, height)


def bars(values: Sequence[int], width: int) -> list[int]:
    """Bar widths, with the largest magnitude filling `width`."""
    return _scale(values, width)


def month_label(month: date) -> str:
    """Axis label "Sep 2026" for a first-of-month date."""
    return display_date(month).split(" ", 1)[1]


def _scale(values: Sequence[int], extent: int) -> list[int]:
    # Payments are stored as negative cents; bar length shows size, not sign.
    peak = max((abs(v) for v in values), default=0)
    if peak == 0:
        return [0 for _ in values]
    return [round(abs(v) * extent / peak) for v in values]
