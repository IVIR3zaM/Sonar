"""Pure geometry for the dashboard's inline SVG charts (SPEC §12).

The macros in templates/components/charts.html only draw; every coordinate
is computed here so it can be tested without parsing SVG.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from math import log10

from sonar.web.display import display_date

# Non-breaking space before the currency sign, as in display.eur.
_NBSP = "\u00a0"


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


# A label like "−1.500,00 €" at text-xs takes about a quarter of the bar at 375px.
SCALE_MIN_GAP = 25
_EDGE_PERCENT = 12.5


@dataclass(frozen=True)
class ScaleMark:
    part: str  # "limit" | "zero" | "balance"
    cents: int
    percent: float
    align: str  # "start" | "center" | "end"
    row: int


def runway_scale(limit: int, balance: int, worst: int, best: int) -> list[ScaleMark]:
    """Label positions, as percentages of the runway bar, for limit, zero and balance.

    The labels are HTML under the SVG, not SVG text: the SVG uses
    preserveAspectRatio="none", which would stretch text. Positions come from
    `runway` so every label lines up with its mark.
    """
    axis = runway(limit, balance, worst, best, width=1000)
    x_by_part = {"limit": axis.limit_x, "zero": axis.zero_x, "balance": axis.balance_x}
    cents_by_part = {"limit": limit, "zero": 0, "balance": balance}
    # Equal values share one label; the first part listed wins.
    kept: dict[int, str] = {}
    for part in ("balance", "zero", "limit"):
        kept.setdefault(cents_by_part[part], part)
    parts = sorted(kept.values(), key=lambda part: x_by_part[part])

    percents = [x_by_part[part] / 10 for part in parts]
    rows = _label_rows(percents, SCALE_MIN_GAP, max_rows=len(parts))
    return [
        ScaleMark(part, cents_by_part[part], percent, _align(percent), row)
        for part, percent, row in zip(parts, percents, rows, strict=True)
    ]


def _label_rows(percents: Sequence[float], min_gap: float, max_rows: int) -> list[int | None]:
    """Greedy row per label, in ascending order: the first row whose last label is far enough left.

    A label with no free row within `max_rows` gets None.
    """
    row_ends: list[float] = []  # percent of the last label on each row
    rows: list[int | None] = []
    for percent in percents:
        row = next(
            (i for i, end in enumerate(row_ends) if percent - end >= min_gap),
            len(row_ends),
        )
        if row >= max_rows:
            rows.append(None)
            continue
        if row == len(row_ends):
            row_ends.append(percent)
        else:
            row_ends[row] = percent
        rows.append(row)
    return rows


# The scale is logarithmic because one large mortgage would otherwise crowd
# every small debt into the left edge. The gap is 20 because a compact label
# at text-xs is about 13% of a 375px slider, and a start-aligned label next
# to a centered one needs about 1.5 label widths.
TICK_MIN_GAP = 20
_TICK_MAX_ROWS = 3


@dataclass(frozen=True)
class PayoffTick:
    cents: int
    percent: float
    position: int  # the range input's value, 0-1000
    align: str  # "start" | "center" | "end"
    row: int | None  # None when no label row is free


def payoff_ticks(amounts: Sequence[int]) -> list[PayoffTick]:
    """Slider ticks for ascending, positive cumulative pay-now amounts, on a log scale."""
    if not amounts:
        return []
    low, high = log10(amounts[0]), log10(amounts[-1])
    span = high - low
    percents = [round(100 * (log10(a) - low) / span, 1) if span else 0.0 for a in amounts]
    rows = _label_rows(percents, TICK_MIN_GAP, _TICK_MAX_ROWS)
    return [
        PayoffTick(cents, percent, round(percent * 10), _align(percent), row)
        for cents, percent, row in zip(amounts, percents, rows, strict=True)
    ]


def _align(percent: float) -> str:
    if percent < _EDGE_PERCENT:
        return "start"
    if percent > 100 - _EDGE_PERCENT:
        return "end"
    return "center"


def columns(values: Sequence[int], height: int) -> list[int]:
    """Column heights, with the largest magnitude filling `height`."""
    return _scale(values, height)


def bars(values: Sequence[int], width: int) -> list[int]:
    """Bar widths, with the largest magnitude filling `width`."""
    return _scale(values, width)


def line_points(
    series: Sequence[Sequence[int]], width: int, height: int
) -> list[list[tuple[int, int]]]:
    """X,Y points for several series, sharing one y-scale so equal values land at the same height.

    Flattening every series before calling `_scale` normalizes them to one
    shared peak, so a value in one series lands at the same y as the same
    value in another. A single-point series is placed at x=0 instead of
    dividing by a zero point count.
    """
    flat = [v for s in series for v in s]
    scaled = _scale(flat, height)
    points = []
    offset = 0
    for s in series:
        heights = scaled[offset : offset + len(s)]
        offset += len(s)
        step = width / (len(s) - 1) if len(s) > 1 else 0
        points.append([(round(i * step), height - h) for i, h in enumerate(heights)])
    return points


def compact_eur(cents: int) -> str:
    """Short euro amount for chart labels: "950 €", "1,2k €", "12k €".

    Magnitude only, because columns show size, not sign. Integer arithmetic
    rounds half up, so no float ever touches money.
    """
    euros = (abs(cents) + 50) // 100
    if euros < 1000:
        return f"{euros}{_NBSP}€"
    if euros < 10_000:
        tenths = (euros + 50) // 100  # tenths of a thousand
        whole, decimal = divmod(tenths, 10)
        return f"{whole}{f',{decimal}' if decimal else ''}k{_NBSP}€"
    return f"{(euros + 500) // 1000}k{_NBSP}€"


def month_label(month: date) -> str:
    """Axis label "Sep 2026" for a first-of-month date."""
    return display_date(month).split(" ", 1)[1]


def _scale(values: Sequence[int], extent: int) -> list[int]:
    # Payments are stored as negative cents; bar length shows size, not sign.
    peak = max((abs(v) for v in values), default=0)
    if peak == 0:
        return [0 for _ in values]
    return [round(abs(v) * extent / peak) for v in values]
