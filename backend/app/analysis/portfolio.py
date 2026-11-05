"""
DCA portfolio engine.

Each batch run adds $1,000 of fresh capital, then the rules in strategy.py decide
the trades (settings.portfolio_strategy selects the preset: "v2" or "legacy").
Every dollar contributed is mirrored into a virtual SPY position for an
apples-to-apples comparison.
"""

import logging
import time as _time
from datetime import date

import yfinance as yf
from sqlalchemy.orm import Session

from ..config import settings
from ..models import PortfolioSnapshot, PortfolioTrade, StockAnalysis
from .strategy import PRESETS, MarketState, Position, build_rounds, coverage, decide, update_states

logger = logging.getLogger(__name__)

WEEKLY_CONTRIBUTION = 1_000.0

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


def _compute_realized_pnl(db: Session) -> dict[int, dict]:
    """Replay trade history chronologically to compute realized P&L per sell."""
    trades = (
        db.query(PortfolioTrade)
        .order_by(PortfolioTrade.created_at.asc(), PortfolioTrade.id.asc())
        .all()
    )
    positions: dict[str, dict] = {}
    realized: dict[int, dict] = {}
    for t in trades:
        pos = positions.setdefault(t.ticker, {"shares": 0.0, "avg_cost": 0.0})
        if t.action == "buy":
            new_shares = pos["shares"] + t.shares
            if new_shares > 0:
                pos["avg_cost"] = (pos["avg_cost"] * pos["shares"] + t.total) / new_shares
            pos["shares"] = new_shares
        elif t.action == "sell":
            cost_basis = pos["avg_cost"] * t.shares
            pnl = t.total - cost_basis
            realized[t.id] = {
                "realized_pnl": round(pnl, 2),
                "realized_pnl_pct": round(pnl / cost_basis * 100, 2) if cost_basis > 0 else 0.0,
            }
            pos["shares"] -= t.shares
            if pos["shares"] <= 0.001:
                pos["shares"] = 0.0
                pos["avg_cost"] = 0.0
    return realized


def _previous_snapshot(db: Session) -> PortfolioSnapshot | None:
    return db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.id.desc()).first()


# ── rebalance (called after each batch) ──────────────────────────────────────

def _signal_rounds(db: Session, max_analysis_id: int | None = None):
    q = (
        db.query(
            StockAnalysis.ticker,
            StockAnalysis.analyzed_at,
            StockAnalysis.current_price,
            StockAnalysis.fair_value,
            StockAnalysis.valuation,
            StockAnalysis.overall_score,
            StockAnalysis.conviction,
        )
        .order_by(StockAnalysis.analyzed_at.asc(), StockAnalysis.id.asc())
    )
    if max_analysis_id is not None:
        q = q.filter(StockAnalysis.id <= max_analysis_id)
    return build_rounds(q.all())


def _spy_market_state() -> MarketState:
    """Current SPY price and 200-day SMA. Raises if SPY data is unavailable —
    better to skip a rebalance than to benchmark against a made-up price."""
    hist = yf.Ticker("SPY").history(period="14mo", auto_adjust=False)["Close"].dropna()
    if hist.empty:
        raise RuntimeError("No SPY price history available")
    price = _get_live_price("SPY") or float(hist.iloc[-1])
    sma = float(hist.iloc[-200:].mean()) if len(hist) >= 200 else None
    return MarketState(spy_price=price, spy_sma200=sma)


def rebalance_portfolio(db: Session):
    cfg = PRESETS[settings.portfolio_strategy]
    market = _spy_market_state()

    prev = _previous_snapshot(db)
    prev_total_invested = prev.total_invested if prev else 0.0
    prev_sp500_shares = prev.sp500_shares if prev else 0.0
    new_total_invested = prev_total_invested + WEEKLY_CONTRIBUTION

    # Cash = contributions so far - buys + sells, plus this round's contribution.
    trades = db.query(PortfolioTrade).all()
    cash = prev_total_invested + WEEKLY_CONTRIBUTION
    for t in trades:
        cash += t.total if t.action == "sell" else -t.total

    holdings = {
        t: Position(shares=p["shares"], cost_basis=p["total_cost"])
        for t, p in _get_holdings(db).items()
    }

    # Rebuild signal state from the full analysis history; the last round is this batch.
    rounds = _signal_rounds(db)
    states: dict = {}
    for idx, (_, signals) in enumerate(rounds):
        update_states(states, signals, idx, cfg)
    current_idx = len(rounds) - 1
    current_cov = coverage(rounds[-1][1]) if rounds else 0.0

    orders = decide(cfg, holdings, cash, states, current_idx, current_cov, market)
    if current_cov < cfg.min_coverage:
        logger.warning(
            f"Skipping trades: only {current_cov:.0%} of this round's analyses have a fair value "
            f"(minimum {cfg.min_coverage:.0%})"
        )
    if market.risk_off and cfg.trend_filter:
        logger.info(f"Risk-off: SPY {market.spy_price:.2f} < 200d SMA {market.spy_sma200:.2f}")

    for o in orders:
        cash += o.total if o.action == "sell" else -o.total
        db.add(PortfolioTrade(
            ticker=o.ticker, action=o.action, shares=o.shares,
            price=o.price, total=o.total, reason=o.reason[:250],
        ))
        logger.info(f"{o.action.upper()} {o.shares:.4f} {o.ticker} @ ${o.price:.2f} ({o.reason})")
    db.flush()

    # ── Compute holdings value after trades ──────────────────────────────
    holdings_after = _get_holdings(db)
    all_tickers = list(holdings_after.keys())
    prices = _get_live_prices_bulk(all_tickers) if all_tickers else {}
    holdings_value = sum(
        pos["shares"] * (prices.get(t) or pos.get("last_price", 0))
        for t, pos in holdings_after.items()
    )

    # ── S&P 500 mirror: DCA $WEEKLY_CONTRIBUTION into SPY ────────────────
    new_spy_shares = WEEKLY_CONTRIBUTION / market.spy_price
    total_sp500_shares = prev_sp500_shares + new_spy_shares
    sp500_value = total_sp500_shares * market.spy_price

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
        f"Rebalance ({cfg.name}) complete: invested=${new_total_invested:,.0f}, "
        f"portfolio=${cash + holdings_value:,.0f}, cash=${cash:,.0f}, "
        f"S&P mirror=${sp500_value:,.0f}, holdings={len(holdings_after)}, trades={len(orders)}"
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

    realized = _compute_realized_pnl(db)
    total_realized_gains = round(sum(r["realized_pnl"] for r in realized.values()), 2)
    trades = (
        db.query(PortfolioTrade)
        .order_by(PortfolioTrade.created_at.desc(), PortfolioTrade.id.desc())
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
        "total_realized_gains": total_realized_gains,
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
                "realized_pnl": realized.get(t.id, {}).get("realized_pnl"),
                "realized_pnl_pct": realized.get(t.id, {}).get("realized_pnl_pct"),
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
