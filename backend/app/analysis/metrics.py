"""Deterministic scoring of stock fundamentals. No LLM needed."""

from dataclasses import dataclass
from ..collectors.stock_data import StockData

MIN_METRICS_REQUIRED = 8


@dataclass
class Scores:
    quality: float
    value: float
    growth: float
    momentum: float
    overall: float
    metrics_available: int
    metrics_total: int


class InsufficientDataError(Exception):
    """Raised when a stock has too few metrics for a reliable score."""
    pass


def compute_scores(data: StockData) -> Scores:
    available = _count_available_metrics(data)
    total = 16
    if available < MIN_METRICS_REQUIRED:
        raise InsufficientDataError(
            f"{data.ticker} has only {available}/{total} metrics available "
            f"(minimum {MIN_METRICS_REQUIRED} required)"
        )

    quality = _quality_score(data)
    value = _value_score(data)
    growth = _growth_score(data)
    momentum = _momentum_score(data)

    overall = round(
        quality * 0.35 + value * 0.30 + growth * 0.25 + momentum * 0.10, 1
    )

    return Scores(
        quality=quality,
        value=value,
        growth=growth,
        momentum=momentum,
        overall=overall,
        metrics_available=available,
        metrics_total=total,
    )


def _count_available_metrics(d: StockData) -> int:
    """Count how many of the key scoring metrics are present."""
    metrics = [
        d.roe, d.operating_margin, d.debt_to_equity, d.current_ratio,
        d.fcf_yield, d.pe_ratio, d.peg_ratio, d.pb_ratio, d.ev_ebitda,
        d.revenue_growth, d.earnings_growth, d.forward_pe,
        d.sma_200_pct, d.rsi_14, d.current_price, d.beta,
    ]
    return sum(1 for m in metrics if m is not None)


def _quality_score(d: StockData) -> float:
    """Always uses full weight denominator -- missing metrics get neutral (50th pct) score."""
    points = 0.0
    total = 100.0

    # ROE (25 pts)
    if d.roe is not None:
        if d.roe >= 25:
            points += 25
        elif d.roe >= 15:
            points += 20
        elif d.roe >= 10:
            points += 12
        elif d.roe >= 0:
            points += 5
    else:
        points += 12  # neutral

    # Operating margin (22 pts)
    if d.operating_margin is not None:
        if d.operating_margin >= 25:
            points += 22
        elif d.operating_margin >= 15:
            points += 17
        elif d.operating_margin >= 8:
            points += 10
        elif d.operating_margin >= 0:
            points += 4
    else:
        points += 10  # neutral

    # Debt/Equity (20 pts)
    if d.debt_to_equity is not None:
        if d.debt_to_equity <= 0.3:
            points += 20
        elif d.debt_to_equity <= 0.7:
            points += 16
        elif d.debt_to_equity <= 1.0:
            points += 12
        elif d.debt_to_equity <= 2.0:
            points += 6
        else:
            points += 2
    else:
        points += 10  # neutral

    # Current ratio (13 pts)
    if d.current_ratio is not None:
        if d.current_ratio >= 2.0:
            points += 13
        elif d.current_ratio >= 1.5:
            points += 10
        elif d.current_ratio >= 1.0:
            points += 7
        else:
            points += 2
    else:
        points += 6  # neutral

    # FCF yield (20 pts)
    if d.fcf_yield is not None:
        if d.fcf_yield >= 8:
            points += 20
        elif d.fcf_yield >= 5:
            points += 16
        elif d.fcf_yield >= 3:
            points += 10
        elif d.fcf_yield >= 0:
            points += 4
    else:
        points += 10  # neutral

    return round(points / total * 100, 1)


def _value_score(d: StockData) -> float:
    """Always uses full weight denominator -- missing metrics get neutral score."""
    points = 0.0
    total = 100.0

    # P/E (25 pts)
    if d.pe_ratio is not None and d.pe_ratio > 0:
        if d.pe_ratio <= 12:
            points += 25
        elif d.pe_ratio <= 18:
            points += 20
        elif d.pe_ratio <= 25:
            points += 14
        elif d.pe_ratio <= 35:
            points += 8
        else:
            points += 3
    else:
        points += 12  # neutral

    # PEG (25 pts)
    if d.peg_ratio is not None and d.peg_ratio > 0:
        if d.peg_ratio <= 1.0:
            points += 25
        elif d.peg_ratio <= 1.5:
            points += 20
        elif d.peg_ratio <= 2.0:
            points += 14
        elif d.peg_ratio <= 3.0:
            points += 8
        else:
            points += 3
    else:
        points += 12  # neutral

    # P/B (20 pts)
    if d.pb_ratio is not None and d.pb_ratio > 0:
        if d.pb_ratio <= 1.5:
            points += 20
        elif d.pb_ratio <= 3.0:
            points += 15
        elif d.pb_ratio <= 5.0:
            points += 10
        elif d.pb_ratio <= 10.0:
            points += 5
        else:
            points += 2
    else:
        points += 10  # neutral

    # EV/EBITDA (15 pts)
    if d.ev_ebitda is not None and d.ev_ebitda > 0:
        if d.ev_ebitda <= 10:
            points += 15
        elif d.ev_ebitda <= 15:
            points += 12
        elif d.ev_ebitda <= 20:
            points += 8
        elif d.ev_ebitda <= 30:
            points += 4
        else:
            points += 1
    else:
        points += 7  # neutral

    # FCF yield (15 pts)
    if d.fcf_yield is not None:
        if d.fcf_yield >= 8:
            points += 15
        elif d.fcf_yield >= 5:
            points += 12
        elif d.fcf_yield >= 3:
            points += 8
        elif d.fcf_yield >= 0:
            points += 3
    else:
        points += 7  # neutral

    return round(points / total * 100, 1)


def _growth_score(d: StockData) -> float:
    """Always uses full weight denominator -- missing metrics get neutral score."""
    points = 0.0
    total = 100.0

    # Revenue growth (35 pts)
    if d.revenue_growth is not None:
        if d.revenue_growth >= 25:
            points += 35
        elif d.revenue_growth >= 15:
            points += 28
        elif d.revenue_growth >= 8:
            points += 20
        elif d.revenue_growth >= 3:
            points += 12
        elif d.revenue_growth >= 0:
            points += 5
    else:
        points += 17  # neutral

    # Earnings growth (35 pts)
    if d.earnings_growth is not None:
        if d.earnings_growth >= 25:
            points += 35
        elif d.earnings_growth >= 15:
            points += 28
        elif d.earnings_growth >= 8:
            points += 20
        elif d.earnings_growth >= 3:
            points += 12
        elif d.earnings_growth >= 0:
            points += 5
    else:
        points += 17  # neutral

    # P/E compression (30 pts)
    if d.forward_pe is not None and d.pe_ratio is not None and d.pe_ratio > 0:
        compression = (d.pe_ratio - d.forward_pe) / d.pe_ratio * 100
        if compression >= 20:
            points += 30
        elif compression >= 10:
            points += 22
        elif compression >= 0:
            points += 14
        else:
            points += 5
    else:
        points += 14  # neutral

    return round(points / total * 100, 1)


def _momentum_score(d: StockData) -> float:
    """Always uses full weight denominator -- missing metrics get neutral score."""
    points = 0.0
    total = 100.0

    # SMA 200 (35 pts)
    if d.sma_200_pct is not None:
        if d.sma_200_pct >= 10:
            points += 35
        elif d.sma_200_pct >= 3:
            points += 28
        elif d.sma_200_pct >= -3:
            points += 20
        elif d.sma_200_pct >= -10:
            points += 12
        else:
            points += 4
    else:
        points += 17  # neutral

    # RSI (25 pts)
    if d.rsi_14 is not None:
        if 40 <= d.rsi_14 <= 60:
            points += 25
        elif 30 <= d.rsi_14 <= 70:
            points += 20
        elif d.rsi_14 < 30:
            points += 15  # oversold can be opportunity
        else:
            points += 8
    else:
        points += 12  # neutral

    # 52-week range position (40 pts)
    if (
        d.week_52_low is not None
        and d.week_52_high is not None
        and d.current_price
        and d.week_52_high > d.week_52_low
    ):
        range_pct = (d.current_price - d.week_52_low) / (
            d.week_52_high - d.week_52_low
        )
        if 0.4 <= range_pct <= 0.75:
            points += 40
        elif 0.25 <= range_pct <= 0.85:
            points += 30
        elif range_pct < 0.25:
            points += 18  # beaten down, could be value
        else:
            points += 15
    else:
        points += 20  # neutral

    return round(points / total * 100, 1)
