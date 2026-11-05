"""Stock analyzer: single Gemini call per stock, fundamentals-first."""

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..collectors.news_data import get_stock_news
from ..collectors.stock_data import StockData, get_stock_data
from ..config import settings
from ..models import ApiCallLog, StockAnalysis
from .metrics import InsufficientDataError, Scores, compute_scores

logger = logging.getLogger(__name__)


def analyze_stock(ticker: str, db: Session) -> StockAnalysis:
    """Full analysis pipeline: collect data -> compute scores -> LLM synthesis -> store."""
    ticker = ticker.upper().strip()

    stock_data = get_stock_data(ticker)
    scores = compute_scores(stock_data)
    previous = None if _is_fresh_look_week() else _previous_analysis(ticker, db)
    news = get_stock_news(ticker, max_items=10)
    news_text = format_news(news, previous.analyzed_at if previous else None)

    llm_result = _call_gemini(stock_data, scores, news_text, previous)

    analysis = StockAnalysis(
        ticker=ticker,
        name=stock_data.name,
        sector=stock_data.sector,
        industry=stock_data.industry,
        market_cap=stock_data.market_cap,
        current_price=stock_data.current_price,
        pe_ratio=stock_data.pe_ratio,
        forward_pe=stock_data.forward_pe,
        peg_ratio=stock_data.peg_ratio,
        pb_ratio=stock_data.pb_ratio,
        ev_ebitda=stock_data.ev_ebitda,
        roe=stock_data.roe,
        profit_margin=stock_data.profit_margin,
        operating_margin=stock_data.operating_margin,
        debt_to_equity=stock_data.debt_to_equity,
        current_ratio=stock_data.current_ratio,
        fcf_yield=stock_data.fcf_yield,
        revenue_growth=stock_data.revenue_growth,
        earnings_growth=stock_data.earnings_growth,
        dividend_yield=stock_data.dividend_yield,
        beta=stock_data.beta,
        sma_200_pct=stock_data.sma_200_pct,
        rsi_14=stock_data.rsi_14,
        week_52_low=stock_data.week_52_low,
        week_52_high=stock_data.week_52_high,
        quality_score=scores.quality,
        value_score=scores.value,
        growth_score=scores.growth,
        momentum_score=scores.momentum,
        overall_score=llm_result.get("overall_score", scores.overall),
        fair_value=llm_result.get("fair_value"),
        buy_below=llm_result.get("buy_below"),
        sell_above=llm_result.get("sell_above"),
        valuation=llm_result.get("valuation"),
        conviction=llm_result.get("conviction"),
        summary=llm_result.get("summary"),
        risks=llm_result.get("risks"),
        catalysts=llm_result.get("catalysts"),
        outlook=llm_result.get("outlook"),
        changes_since_last=llm_result.get("changes_since_last"),
    )

    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def get_latest_analysis(ticker: str, db: Session, max_age_days: int = 7):
    """Return the most recent analysis if it's younger than max_age_days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    return (
        db.query(StockAnalysis)
        .filter(StockAnalysis.ticker == ticker.upper())
        .filter(StockAnalysis.analyzed_at >= cutoff)
        .order_by(StockAnalysis.analyzed_at.desc())
        .first()
    )


def _parse_published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def format_news(news, since: datetime | None, summary_chars: int = 240) -> str:
    """Headlines with date and summary; items published after `since` are marked [NEW]."""
    if not news:
        return "No recent news available."
    since_utc = since.replace(tzinfo=timezone.utc) if since and since.tzinfo is None else since
    lines = []
    for n in news:
        published = _parse_published(n.published)
        is_new = bool(since_utc and published and published > since_utc)
        when = published.strftime("%b %d") if published else "date unknown"
        line = f"- {'[NEW] ' if is_new else ''}{when} — {n.title} ({n.source})"
        summary = (getattr(n, "summary", None) or "").strip()
        if summary:
            line += f"\n    {summary[:summary_chars]}{'…' if len(summary) > summary_chars else ''}"
        lines.append(line)
    return "\n".join(lines)


# Every FRESH_LOOK_EVERY_WEEKS-th ISO week the analysis runs without the previous assessment,
# so a fair value can't stay locked to an old anchor indefinitely. The strategy's fair-value
# smoothing absorbs the extra noise of these weeks.
FRESH_LOOK_EVERY_WEEKS = 4


def _is_fresh_look_week(today: datetime | None = None) -> bool:
    today = today or datetime.now(timezone.utc)
    return today.isocalendar().week % FRESH_LOOK_EVERY_WEEKS == 0


def _previous_analysis(ticker: str, db: Session) -> StockAnalysis | None:
    """Most recent analysis of this ticker that produced a fair value."""
    return (
        db.query(StockAnalysis)
        .filter(StockAnalysis.ticker == ticker)
        .filter(StockAnalysis.fair_value.isnot(None))
        .order_by(StockAnalysis.analyzed_at.desc(), StockAnalysis.id.desc())
        .first()
    )


# Metrics compared against the previous analysis: (attribute, label, unit, "material" threshold).
# A change is listed when it moves by more than the threshold (absolute for %, relative for ratios).
# P/E is deliberately not compared directly: it moves with the price. Implied EPS (price / P/E)
# only moves when reported earnings or analyst estimates do.
_TRACKED_METRICS = [
    ("revenue_growth", "Revenue growth", "%", 2.0),
    ("earnings_growth", "Earnings growth", "%", 5.0),
    ("profit_margin", "Profit margin", "%", 1.0),
    ("operating_margin", "Operating margin", "%", 1.0),
    ("fcf_yield", "FCF yield", "%", 0.5),
    ("debt_to_equity", "Debt/Equity", "x", 0.15),
]
_EPS_THRESHOLD = 0.03


def _implied_eps(price, pe):
    return price / pe if price and pe and pe > 0 else None


def _metric_changes(prev: StockAnalysis, data: StockData) -> list[str]:
    out = []
    for label, pe_attr in (("Trailing EPS", "pe_ratio"), ("Forward EPS estimate", "forward_pe")):
        old = _implied_eps(prev.current_price, getattr(prev, pe_attr, None))
        new = _implied_eps(data.current_price, getattr(data, pe_attr, None))
        if old and new and abs(new / old - 1) > _EPS_THRESHOLD:
            out.append(f"{label} ${old:.2f} -> ${new:.2f} ({(new / old - 1) * 100:+.1f}%)")
    for attr, label, unit, threshold in _TRACKED_METRICS:
        old, new = getattr(prev, attr, None), getattr(data, attr, None)
        if old is None or new is None:
            continue
        if unit == "%":
            if abs(new - old) > threshold:
                out.append(f"{label} {old:.1f}% -> {new:.1f}%")
        elif old != 0 and abs(new / old - 1) > threshold:
            out.append(f"{label} {old:.2f} -> {new:.2f}")
    return out


def _previous_section(prev: StockAnalysis | None, data: StockData) -> str:
    if prev is None:
        return "PREVIOUS ASSESSMENT: none — this is the first analysis of this stock.\n"

    price = data.current_price or 0
    when = prev.analyzed_at.strftime("%B %d, %Y") if prev.analyzed_at else "unknown date"
    price_move = ""
    if prev.current_price and price:
        price_move = f" | Price then ${prev.current_price:.2f} -> now ${price:.2f} ({(price / prev.current_price - 1) * 100:+.1f}%)"
    changes = _metric_changes(prev, data)
    changes_text = "; ".join(changes) if changes else "no material change in tracked metrics"
    earnings_note = ""
    if data.last_earnings_date and prev.analyzed_at and data.last_earnings_date > prev.analyzed_at.date():
        earnings_note = (
            f"\n  >> EARNINGS SINCE THEN: {data.name} reported results on "
            f"{data.last_earnings_date:%B %d, %Y}, after the previous assessment. Re-derive fair value "
            f"from the new numbers; use the previous estimate only for comparison."
        )
    risks = "; ".join(prev.risks or []) or "n/a"
    catalysts = "; ".join(prev.catalysts or []) or "n/a"

    return f"""PREVIOUS ASSESSMENT ({when}){price_move}:
  Fair value: ${prev.fair_value:.2f} | Valuation: {prev.valuation} | Conviction: {prev.conviction} | Score: {prev.overall_score}
  Thesis: {prev.summary or "n/a"}
  Risks then: {risks}
  Catalysts then: {catalysts}
  Metric changes since then: {changes_text}{earnings_note}

HOW TO USE THE PREVIOUS ASSESSMENT:
- It is your prior, not your answer. Rebuild the view from today's data and news, then compare.
- First work out what has materially changed since then: earnings or guidance, a shift in growth,
  margins or balance sheet (see "Metric changes"), or a risk/catalyst that played out.
- Read the headlines marked [NEW] (published after the previous assessment). Material events
  justify a revision even without an earnings report: guidance changes, M&A, regulatory or legal
  rulings, major contract wins or customer losses, management changes, product failures or
  recalls, capital actions (large buybacks, dilution, dividend cuts), or a shock to this
  company's specific industry. Routine commentary, analyst chatter and price-move stories do not.
- A price move on its own does not change what the business is worth. Do not drag fair value
  toward the current price just because the price moved.
- If something material changed, update fair value, valuation and conviction decisively — do not
  anchor on the old number. If nothing material changed, keep fair value close to the previous
  estimate rather than re-estimating from scratch.
- Write the summary, risks and catalysts fresh for today; do not copy the previous wording.
- In "changes_since_last", name the specific changes (earnings, metric shifts or [NEW] headlines)
  that drove any revision in 1-2 sentences, or write "No material change" and say why the
  thesis holds despite the [NEW] headlines.
"""


def _call_gemini(data: StockData, scores: Scores, news_text: str, previous: StockAnalysis | None = None) -> dict:
    """Single LLM call that synthesizes all data into an investment thesis."""
    if not settings.gemini_api_key:
        logger.warning("No Gemini API key configured, returning empty LLM result")
        return {}

    from google import genai

    client = genai.Client(api_key=settings.gemini_api_key)

    def _fmt(v, suffix="", fallback="N/A"):
        if v is None:
            return fallback
        return f"{v}{suffix}"

    price = data.current_price or 0
    range_str = ""
    if data.week_52_low and data.week_52_high and data.week_52_high > data.week_52_low:
        pct = (price - data.week_52_low) / (data.week_52_high - data.week_52_low) * 100
        range_str = f"  52-week: ${data.week_52_low:.2f} - ${data.week_52_high:.2f} (at {pct:.0f}% of range)"

    today = datetime.now().strftime("%B %d, %Y")
    prompt = f"""You are a long-term equity analyst. Your audience invests with a 2-5 year horizon.
Today's date is {today}. All data below is current as of today.
Given the data below, produce a JSON investment analysis.

STOCK: {data.ticker} — {data.name}
Sector: {data.sector} | Industry: {data.industry}
Market Cap: ${data.market_cap / 1e9:.1f}B | Price: ${price:.2f}
{range_str}
  Last earnings report: {data.last_earnings_date.strftime("%B %d, %Y") if data.last_earnings_date else "unknown"}

VALUATION METRICS:
  P/E: {_fmt(data.pe_ratio)} | Forward P/E: {_fmt(data.forward_pe)} | PEG: {_fmt(data.peg_ratio)}
  P/B: {_fmt(data.pb_ratio)} | EV/EBITDA: {_fmt(data.ev_ebitda)}

QUALITY METRICS:
  ROE: {_fmt(data.roe, '%')} | Profit Margin: {_fmt(data.profit_margin, '%')}
  Operating Margin: {_fmt(data.operating_margin, '%')}
  Debt/Equity: {_fmt(data.debt_to_equity)} | Current Ratio: {_fmt(data.current_ratio)}
  FCF Yield: {_fmt(data.fcf_yield, '%')}

GROWTH:
  Revenue Growth (YoY): {_fmt(data.revenue_growth, '%')}
  Earnings Growth (YoY): {_fmt(data.earnings_growth, '%')}
  Dividend Yield: {_fmt(data.dividend_yield, '%')} | Beta: {_fmt(data.beta)}

TECHNICAL CONTEXT (secondary — do not overweight):
  Price vs 200-day SMA: {_fmt(data.sma_200_pct, '%')}
  RSI(14): {_fmt(data.rsi_14)}

DETERMINISTIC SCORES (0-100, based purely on reported metrics):
  Quality: {scores.quality} | Value: {scores.value} | Growth: {scores.growth}
  Momentum: {scores.momentum} | Baseline Overall: {scores.overall}
  (Metrics available: {scores.metrics_available}/{scores.metrics_total} — lower coverage means less reliable baseline)

RECENT NEWS:
{news_text}

{_previous_section(previous, data)}
INSTRUCTIONS:
- Focus on the 2-5 year investment case. Ignore short-term price noise.
- Base your fair value primarily on fundamentals (earnings power, growth trajectory, competitive position).
- Be skeptical and independent. Do not just echo market sentiment.
- Provide buy_below as a margin-of-safety entry point (~10-15% below fair value).
- Provide sell_above as a price where the stock is clearly overvalued (~15-20% above fair value).
- Conviction 1-10 reflects how confident you are in your thesis.
- Risks and catalysts should be specific and substantive, not generic.
- overall_score (0-100): Start from the baseline overall score above, then adjust it based on:
  (a) Valuation gap — if the stock trades well below your fair value, nudge the score up; well above, nudge it down.
  (b) News sentiment — material positive or negative news should shift the score.
  (c) Macro/sector risks — headwinds or tailwinds the metrics alone don't capture.
  The final score should reflect "how attractive is this stock to buy RIGHT NOW for a long-term investor?"
  A great business at a terrible price should score lower than a decent business at a bargain.

Respond ONLY with valid JSON, no markdown fences:
{{
  "fair_value": <number>,
  "buy_below": <number>,
  "sell_above": <number>,
  "valuation": "Undervalued" | "Fair Value" | "Overvalued",
  "overall_score": <0-100>,
  "conviction": <1-10>,
  "summary": "<2-3 sentence investment thesis>",
  "risks": ["<specific risk 1>", "<specific risk 2>", "<specific risk 3>"],
  "catalysts": ["<specific catalyst 1>", "<specific catalyst 2>", "<specific catalyst 3>"],
  "outlook": "<2-3 sentence 2-5 year outlook>",
  "changes_since_last": "<1-2 sentences: what changed since the previous assessment and how it moved your view>"
}}"""

    import time

    models_to_try = [settings.gemini_model]
    if settings.gemini_fallback_model and settings.gemini_fallback_model != settings.gemini_model:
        models_to_try.append(settings.gemini_fallback_model)

    from google.genai import types as genai_types

    for model_name in models_to_try:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        http_options=genai_types.HttpOptions(timeout=60_000),
                    ),
                )

                text = response.text.strip()
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)

                result = json.loads(text)

                try:
                    usage = response.usage_metadata
                    log = ApiCallLog(
                        model=model_name,
                        ticker=data.ticker,
                        prompt_tokens=getattr(usage, "prompt_token_count", None),
                        response_tokens=getattr(usage, "candidates_token_count", None),
                    )
                    from ..database import SessionLocal

                    log_db = SessionLocal()
                    log_db.add(log)
                    log_db.commit()
                    log_db.close()
                except Exception:
                    pass

                return result

            except Exception as e:
                logger.warning(f"Gemini {model_name} attempt {attempt + 1}/2 failed for {data.ticker}: {e}")
                if attempt < 1:
                    time.sleep(2)

    logger.error(f"All Gemini models failed for {data.ticker}")
    return {}
