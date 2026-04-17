"""Collect stock fundamentals and price data from yfinance."""

from dataclasses import dataclass, fields
from typing import Optional

import yfinance as yf


@dataclass
class StockData:
    ticker: str
    name: str
    sector: str
    industry: str
    market_cap: float
    current_price: float

    # Valuation
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    ev_ebitda: Optional[float] = None

    # Quality
    roe: Optional[float] = None
    profit_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    fcf_yield: Optional[float] = None

    # Growth
    revenue_growth: Optional[float] = None
    earnings_growth: Optional[float] = None

    # Other
    dividend_yield: Optional[float] = None
    beta: Optional[float] = None

    # Technical context
    sma_200_pct: Optional[float] = None
    rsi_14: Optional[float] = None
    week_52_low: Optional[float] = None
    week_52_high: Optional[float] = None


def get_stock_data(ticker: str) -> StockData:
    """Collect all fundamental and technical data for a stock via yfinance."""
    t = yf.Ticker(ticker)
    info = t.info

    if not info or info.get("quoteType") == "NONE":
        raise ValueError(f"Ticker '{ticker}' not found")

    hist = t.history(period="1y")

    sma_200_pct = None
    rsi_14 = None
    if not hist.empty and len(hist) > 20:
        closes = hist["Close"]
        current = closes.iloc[-1]

        if len(closes) >= 200:
            sma200 = closes.rolling(200).mean().iloc[-1]
            if sma200 and sma200 > 0:
                sma_200_pct = round(((current - sma200) / sma200) * 100, 2)

        delta = closes.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        last_loss = loss.iloc[-1]
        if last_loss and last_loss != 0:
            rs = gain.iloc[-1] / last_loss
            rsi_14 = round(100 - (100 / (1 + rs)), 1)

    market_cap = info.get("marketCap", 0) or 0
    fcf = info.get("freeCashflow")
    fcf_yield = None
    if fcf and market_cap > 0:
        fcf_yield = round((fcf / market_cap) * 100, 2)

    de_raw = info.get("debtToEquity")

    return StockData(
        ticker=ticker.upper(),
        name=info.get("longName") or info.get("shortName") or ticker,
        sector=info.get("sector") or "Unknown",
        industry=info.get("industry") or "Unknown",
        market_cap=market_cap,
        current_price=info.get("currentPrice") or info.get("regularMarketPrice") or 0,
        pe_ratio=info.get("trailingPE"),
        forward_pe=info.get("forwardPE"),
        peg_ratio=info.get("pegRatio"),
        pb_ratio=info.get("priceToBook"),
        ev_ebitda=info.get("enterpriseToEbitda"),
        roe=_to_pct(info.get("returnOnEquity")),
        profit_margin=_to_pct(info.get("profitMargins")),
        operating_margin=_to_pct(info.get("operatingMargins")),
        debt_to_equity=round(de_raw / 100, 2) if de_raw is not None else None,
        current_ratio=info.get("currentRatio"),
        fcf_yield=fcf_yield,
        revenue_growth=_to_pct(info.get("revenueGrowth")),
        earnings_growth=_to_pct(info.get("earningsGrowth")),
        dividend_yield=_to_pct(info.get("trailingAnnualDividendYield")),
        beta=info.get("beta"),
        sma_200_pct=sma_200_pct,
        rsi_14=rsi_14,
        week_52_low=info.get("fiftyTwoWeekLow"),
        week_52_high=info.get("fiftyTwoWeekHigh"),
    )


def _to_pct(value) -> Optional[float]:
    if value is None:
        return None
    return round(value * 100, 2)
