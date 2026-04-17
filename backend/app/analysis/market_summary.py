"""On-demand AI market summary using live index data, news, + single Gemini call."""

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import yfinance as yf

from ..collectors.news_data import get_stock_news
from ..config import settings

logger = logging.getLogger(__name__)

_cache: dict = {"summary": None, "indicators": None, "generated_at": None, "generated_date": None}


@dataclass
class MarketIndicators:
    sp500: float | None = None
    sp500_change_pct: float | None = None
    vix: float | None = None
    dow_change_pct: float | None = None
    nasdaq_change_pct: float | None = None
    treasury_10y: float | None = None


def _fetch_indicators() -> MarketIndicators:
    """Fetch current levels and daily changes for major indices via yfinance."""
    tickers = {
        "sp500": "^GSPC",
        "vix": "^VIX",
        "dow": "^DJI",
        "nasdaq": "^IXIC",
        "tnx": "^TNX",
    }

    data = yf.download(
        list(tickers.values()),
        period="5d",
        group_by="ticker",
        progress=False,
        threads=True,
    )

    def _pct_change(symbol: str) -> tuple[float | None, float | None]:
        try:
            col = data[symbol]["Close"].dropna()
            if len(col) < 2:
                return (float(col.iloc[-1]) if len(col) else None, None)
            current = float(col.iloc[-1])
            prev = float(col.iloc[-2])
            change = ((current - prev) / prev) * 100 if prev else None
            return current, change
        except Exception:
            return None, None

    sp500_level, sp500_chg = _pct_change("^GSPC")
    vix_level, _ = _pct_change("^VIX")
    _, dow_chg = _pct_change("^DJI")
    _, nasdaq_chg = _pct_change("^IXIC")
    tnx_level, _ = _pct_change("^TNX")

    return MarketIndicators(
        sp500=sp500_level,
        sp500_change_pct=round(sp500_chg, 2) if sp500_chg is not None else None,
        vix=round(vix_level, 2) if vix_level is not None else None,
        dow_change_pct=round(dow_chg, 2) if dow_chg is not None else None,
        nasdaq_change_pct=round(nasdaq_chg, 2) if nasdaq_chg is not None else None,
        treasury_10y=round(tnx_level, 2) if tnx_level is not None else None,
    )


def _fetch_market_news() -> str:
    """Fetch recent news from broad market ETFs/indices for context."""
    headlines = []
    for ticker in ["SPY", "QQQ", "DIA"]:
        try:
            news = get_stock_news(ticker, max_items=5)
            for n in news:
                headlines.append(f"- {n.title} ({n.source})")
        except Exception:
            pass
    seen = set()
    unique = []
    for h in headlines:
        if h not in seen:
            seen.add(h)
            unique.append(h)
    return "\n".join(unique[:12]) or "No recent market news available."


def _call_gemini_summary(indicators: MarketIndicators, news_text: str) -> str:
    """Single Gemini call to produce a market summary paragraph."""
    if not settings.gemini_api_key:
        return "No Gemini API key configured."

    from google import genai

    client = genai.Client(api_key=settings.gemini_api_key)

    def _fmt(v, suffix=""):
        return f"{v}{suffix}" if v is not None else "N/A"

    today = datetime.now().strftime("%B %d, %Y")
    prompt = f"""You are a seasoned market analyst writing for long-term investors (2-5 year horizon).
Today's date is {today}. All data below is current as of today.

CURRENT MARKET DATA:
  S&P 500: {_fmt(indicators.sp500)} ({_fmt(indicators.sp500_change_pct, '% today')})
  VIX (Volatility Index): {_fmt(indicators.vix)}
  Dow Jones: {_fmt(indicators.dow_change_pct, '% today')}
  Nasdaq: {_fmt(indicators.nasdaq_change_pct, '% today')}
  10-Year Treasury Yield: {_fmt(indicators.treasury_10y, '%')}

RECENT MARKET NEWS:
{news_text}

Write a concise 3-4 sentence market summary. Cover:
1. Where the market stands right now (bullish/bearish/neutral tone, recent direction)
2. Key themes from the news and what they mean for the broader market
3. One actionable takeaway for long-term investors

Be direct and opinionated, not wishy-washy. No bullet points — write flowing prose.
Respond with ONLY the summary text, no JSON, no markdown."""

    models_to_try = [settings.gemini_model]
    if settings.gemini_fallback_model and settings.gemini_fallback_model != settings.gemini_model:
        models_to_try.append(settings.gemini_fallback_model)

    for model_name in models_to_try:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                text = response.text.strip()
                text = re.sub(r"^```(?:\w+)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)

                try:
                    from ..database import SessionLocal
                    from ..models import ApiCallLog

                    usage = response.usage_metadata
                    log = ApiCallLog(
                        model=model_name,
                        ticker="MARKET",
                        prompt_tokens=getattr(usage, "prompt_token_count", None),
                        response_tokens=getattr(usage, "candidates_token_count", None),
                    )
                    log_db = SessionLocal()
                    log_db.add(log)
                    log_db.commit()
                    log_db.close()
                except Exception:
                    pass

                return text

            except Exception as e:
                logger.warning(f"Gemini {model_name} attempt {attempt + 1}/2 failed for market summary: {e}")
                if attempt < 1:
                    time.sleep(2)

    return "Unable to generate market summary at this time."


def generate_market_summary() -> dict:
    """Fetch indicators, news, and produce an AI summary. Returns dict ready for API response."""
    indicators = _fetch_indicators()
    news_text = _fetch_market_news()
    summary_text = _call_gemini_summary(indicators, news_text)
    now = datetime.now(timezone.utc)

    result = {
        "summary": summary_text,
        "indicators": {
            "sp500": indicators.sp500,
            "sp500_change_pct": indicators.sp500_change_pct,
            "vix": indicators.vix,
            "dow_change_pct": indicators.dow_change_pct,
            "nasdaq_change_pct": indicators.nasdaq_change_pct,
            "treasury_10y": indicators.treasury_10y,
        },
        "generated_at": now.isoformat(),
        "generated_date": now.strftime("%Y-%m-%d"),
    }

    _cache.update(result)
    return result


def get_cached_summary() -> dict | None:
    """Return cached summary if available, otherwise None."""
    if _cache["summary"]:
        return {
            "summary": _cache["summary"],
            "indicators": _cache["indicators"],
            "generated_at": _cache["generated_at"],
        }
    return None


def get_or_generate_summary() -> dict:
    """Return today's cached summary, or generate a fresh one if stale/missing."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _cache["summary"] and _cache.get("generated_date") == today:
        return {
            "summary": _cache["summary"],
            "indicators": _cache["indicators"],
            "generated_at": _cache["generated_at"],
        }
    return generate_market_summary()
