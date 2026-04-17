"""
DCA portfolio engine.

Strategy:
- Each batch run adds $1,000 of fresh capital.
- Sell all positions whose latest valuation is "Fair Value" or "Overvalued".
- Buy the top-10 undervalued stocks by overall_score with available cash.
- Mirror every dollar invested into a virtual SPY position for apples-to-apples comparison.
"""

import logging
import time as _time
from datetime import date

import yfinance as yf
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import PortfolioSnapshot, PortfolioTrade, StockAnalysis

logger = logging.getLogger(__name__)

WEEKLY_CONTRIBUTION = 1_000.0
TOP_N_BUYS = 10

# ── price helpers ────────────────────────────────────────────────────────────

_price_cache: dict[str, tuple[float, float]] = {}
_PRICE_TTL = 300


def _get_live_price(ticker: str) -> float | None:
    now = _time.time()
    cached = _price_cache.get(ticker)
    if cached and now - cached[1] < _PRICE_TTL:
        return cached[0]
    try:
        t = yf.Ticker(ticker)
        price = t.fast_info.get("lastPrice") or t.info.get("currentPrice") or t.info.get("regularMarketPrice")
        if price:
            _price_cache[ticker] = (float(price), now)
            return float(price)
    except Exception:
        pass
    return None


def _get_live_prices_bulk(tickers: list[str]) -> dict[str, float | None]:
    now = _time.time()
    results: dict[str, float | None] = {}
    to_fetch = []
    for t in tickers:
        cached = _price_cache.get(t)
        if cached and now - cached[1] < _PRICE_TTL:
            results[t] = cached[0]
        else:
            to_fetch.append(t)

    if to_fetch:
        try:
            data = yf.download(to_fetch, period="1d", progress=False, threads=True)
            if not data.empty:
                close = data["Close"]
                if len(to_fetch) == 1:
                    try:
                        val = float(close.iloc[-1])
                    except Exception:
                        val = None
                    if val and val > 0:
                        _price_cache[to_fetch[0]] = (val, now)
                    results[to_fetch[0]] = val
                else:
                    for t in to_fetch:
                        try:
                            val = float(close[t].iloc[-1]) if t in close.columns else None
                        except Exception:
                            val = None
                        if val and val > 0:
                            _price_cache[t] = (val, now)
                        results[t] = val
            else:
                for t in to_fetch:
                    results[t] = None
        except Exception:
            for t in to_fetch:
                results[t] = None
    return results


# ── internal helpers ─────────────────────────────────────────────────────────

def _get_holdings(db: Session) -> dict[str, dict]:
    trades = db.query(PortfolioTrade).order_by(PortfolioTrade.created_at.asc()).all()
    holdings: dict[str, dict] = {}
    for t in trades:
        if t.ticker not in holdings:
            holdings[t.ticker] = {"shares": 0.0, "total_cost": 0.0, "avg_cost": 0.0, "last_price": t.price}
        pos = holdings[t.ticker]
        if t.action == "buy":
            pos["total_cost"] += t.total
            pos["shares"] += t.shares
            pos["avg_cost"] = pos["total_cost"] / pos["shares"] if pos["shares"] > 0 else 0
        elif t.action == "sell":
            pos["shares"] -= t.shares
            if pos["shares"] <= 0.001:
                del holdings[t.ticker]
                continue
            pos["total_cost"] = pos["avg_cost"] * pos["shares"]
        pos["last_price"] = t.price
    return holdings


def _get_cash(db: Session) -> float:
    trades = db.query(PortfolioTrade).all()
    cash = 0.0
    for t in trades:
        if t.action == "buy":
            cash -= t.total
        elif t.action == "sell":
            cash += t.total
    snapshots = db.query(PortfolioSnapshot).all()
    total_invested = sum(s.total_invested for s in snapshots) if snapshots else 0.0
    last = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.id.desc()).first()
    prev_invested = (last.total_invested if last else 0.0)
    cash_from_contributions = sum(s.total_invested for s in snapshots)
    return cash_from_contributions + sum(
        (t.total if t.action == "sell" else -t.total) for t in trades
    )


def _get_latest_analyses(db: Session) -> dict[str, StockAnalysis]:
    subq = (
        db.query(StockAnalysis.ticker, func.max(StockAnalysis.id).label("max_id"))
        .group_by(StockAnalysis.ticker)
        .subquery()
    )
    results = db.query(StockAnalysis).join(subq, StockAnalysis.id == subq.c.max_id).all()
    return {r.ticker: r for r in results}


def _previous_snapshot(db: Session) -> PortfolioSnapshot | None:
    return db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.id.desc()).first()


# ── rebalance (called after each batch) ──────────────────────────────────────

def rebalance_portfolio(db: Session):
    prev = _previous_snapshot(db)
    prev_total_invested = prev.total_invested if prev else 0.0
    prev_sp500_shares = prev.sp500_shares if prev else 0.0

    new_total_invested = prev_total_invested + WEEKLY_CONTRIBUTION

    holdings = _get_holdings(db)

    # Reconstruct cash: total_invested so far + sell proceeds - buy costs
    trades = db.query(PortfolioTrade).all()
    cash = prev_total_invested  # cash contributed so far (before this round)
    for t in trades:
        if t.action == "buy":
            cash -= t.total
        elif t.action == "sell":
            cash += t.total
    cash += WEEKLY_CONTRIBUTION  # add this week's contribution

    latest = _get_latest_analyses(db)

    # ── SELLS: liquidate positions at Fair Value or Overvalued ────────────
    sold_tickers = set()
    for ticker, position in list(holdings.items()):
        analysis = latest.get(ticker)
        if not analysis:
            continue
        if analysis.valuation in ("Fair Value", "Overvalued"):
            price = analysis.current_price or position.get("last_price", 0)
            if price <= 0:
                continue
            total = position["shares"] * price
            cash += total
            sold_tickers.add(ticker)
            db.add(PortfolioTrade(
                ticker=ticker,
                action="sell",
                shares=position["shares"],
                price=price,
                total=total,
                reason=f"{analysis.valuation}, score {analysis.overall_score:.0f}" if analysis.overall_score else analysis.valuation,
            ))
            logger.info(f"SELL {position['shares']:.2f} {ticker} @ ${price:.2f} ({analysis.valuation})")

    # ── BUYS: top-10 undervalued by score ────────────────────────────────
    held_tickers = set(holdings.keys()) - sold_tickers
    buy_candidates = []
    for ticker, analysis in latest.items():
        if analysis.valuation == "Undervalued" and analysis.overall_score is not None:
            buy_candidates.append((ticker, analysis))

    buy_candidates.sort(key=lambda x: x[1].overall_score or 0, reverse=True)
    buy_candidates = buy_candidates[:TOP_N_BUYS]

    if buy_candidates and cash > 10:
        per_stock = cash / len(buy_candidates)
        for ticker, analysis in buy_candidates:
            price = analysis.current_price or 0
            if price <= 0:
                continue
            shares = per_stock / price
            total = shares * price
            cash -= total
            db.add(PortfolioTrade(
                ticker=ticker,
                action="buy",
                shares=shares,
                price=price,
                total=total,
                reason=f"Top-{TOP_N_BUYS} undervalued, score {analysis.overall_score:.0f}",
            ))
            logger.info(f"BUY {shares:.4f} {ticker} @ ${price:.2f}")

    # ── Compute holdings value after trades ──────────────────────────────
    holdings_after = _get_holdings(db)
    all_tickers = list(holdings_after.keys())
    prices = _get_live_prices_bulk(all_tickers) if all_tickers else {}
    holdings_value = sum(
        pos["shares"] * (prices.get(t) or pos.get("last_price", 0))
        for t, pos in holdings_after.items()
    )

    # ── S&P 500 mirror: DCA $WEEKLY_CONTRIBUTION into SPY ────────────────
    spy_price = _get_live_price("SPY") or 550
    new_spy_shares = WEEKLY_CONTRIBUTION / spy_price
    total_sp500_shares = prev_sp500_shares + new_spy_shares
    sp500_value = total_sp500_shares * spy_price

    db.add(PortfolioSnapshot(
        date=date.today(),
        total_value=cash + holdings_value,
        cash=cash,
        holdings_value=holdings_value,
        total_invested=new_total_invested,
        sp500_shares=total_sp500_shares,
        sp500_value=sp500_value,
        num_holdings=len(holdings_after),
    ))
    db.commit()
    logger.info(
        f"Rebalance complete: invested=${new_total_invested:,.0f}, "
        f"portfolio=${cash + holdings_value:,.0f}, "
        f"S&P mirror=${sp500_value:,.0f}, "
        f"holdings={len(holdings_after)}"
    )


# ── API helpers ──────────────────────────────────────────────────────────────

def get_portfolio_state(db: Session) -> dict:
    holdings = _get_holdings(db)
    prev = _previous_snapshot(db)

    total_invested = prev.total_invested if prev else 0.0
    sp500_shares = prev.sp500_shares if prev else 0.0

    # Reconstruct cash
    trades_all = db.query(PortfolioTrade).all()
    cash = total_invested
    for t in trades_all:
        if t.action == "buy":
            cash -= t.total
        elif t.action == "sell":
            cash += t.total

    ticker_list = list(holdings.keys())
    live_prices = _get_live_prices_bulk(ticker_list) if ticker_list else {}

    positions = []
    holdings_value = 0.0
    for ticker, pos in holdings.items():
        current_price = live_prices.get(ticker) or pos.get("last_price", 0)
        value = pos["shares"] * current_price
        cost_basis = pos["avg_cost"] * pos["shares"]
        gain_loss = value - cost_basis
        holdings_value += value
        positions.append({
            "ticker": ticker,
            "shares": round(pos["shares"], 4),
            "avg_cost": round(pos["avg_cost"], 2),
            "current_price": round(current_price, 2),
            "value": round(value, 2),
            "gain_loss": round(gain_loss, 2),
            "gain_loss_pct": round((gain_loss / cost_basis) * 100, 2) if cost_basis > 0 else 0,
        })

    positions.sort(key=lambda x: x["value"], reverse=True)
    total_value = cash + holdings_value

    spy_price = _get_live_price("SPY") or 550
    sp500_value = sp500_shares * spy_price

    gain_loss = total_value - total_invested if total_invested > 0 else 0
    gain_loss_pct = (gain_loss / total_invested * 100) if total_invested > 0 else 0
    sp500_gain = sp500_value - total_invested if total_invested > 0 else 0
    sp500_gain_pct = (sp500_gain / total_invested * 100) if total_invested > 0 else 0

    trades = (
        db.query(PortfolioTrade)
        .order_by(PortfolioTrade.created_at.desc())
        .limit(50)
        .all()
    )

    return {
        "total_value": round(total_value, 2),
        "cash": round(cash, 2),
        "holdings_value": round(holdings_value, 2),
        "total_invested": round(total_invested, 2),
        "gain_loss": round(gain_loss, 2),
        "gain_loss_pct": round(gain_loss_pct, 2),
        "sp500_value": round(sp500_value, 2),
        "sp500_gain_pct": round(sp500_gain_pct, 2),
        "num_holdings": len(positions),
        "positions": positions,
        "trades": [
            {
                "ticker": t.ticker,
                "action": t.action,
                "shares": round(t.shares, 4),
                "price": round(t.price, 2),
                "total": round(t.total, 2),
                "reason": t.reason,
                "date": t.created_at.isoformat() if t.created_at else None,
            }
            for t in trades
        ],
    }


def get_portfolio_history(db: Session) -> list[dict]:
    snapshots = (
        db.query(PortfolioSnapshot)
        .order_by(PortfolioSnapshot.date.asc())
        .all()
    )
    return [
        {
            "date": s.date.isoformat(),
            "portfolio": round(s.total_value, 2),
            "sp500": round(s.sp500_value, 2),
            "invested": round(s.total_invested, 2),
        }
        for s in snapshots
    ]
