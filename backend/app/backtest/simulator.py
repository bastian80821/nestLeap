"""Weekly DCA simulator that drives the live strategy rules round by round."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from ..analysis.strategy import (
    MarketState,
    Order,
    Position,
    Signal,
    StrategyConfig,
    apply_orders,
    coverage,
    decide,
    update_states,
)


@dataclass
class RoundRecord:
    date: date
    nav: float
    cash: float
    invested: float
    spy_value: float
    holdings: int
    trades: int
    risk_off: bool
    skipped: bool
    fees: float = 0.0  # cumulative
    dead_pct: float = 0.0  # share of NAV in holdings that are no longer a buy


@dataclass
class TradeRecord:
    date: date
    order: Order
    realized_pnl: float = 0.0
    holding_days: int | None = None


@dataclass
class SimResult:
    name: str
    rounds: list[RoundRecord] = field(default_factory=list)
    trades: list[TradeRecord] = field(default_factory=list)

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame([r.__dict__ for r in self.rounds])


class SpyMarket:
    """SPY close and 200-day SMA as of a date (uses the last close on or before it).
    For weekly series pass window=40 (~200 trading days)."""

    def __init__(self, closes: pd.Series, window: int = 200):
        closes = closes.dropna().sort_index()
        self.close = closes
        self.sma = closes.rolling(window, min_periods=window).mean()

    def at(self, d) -> MarketState | None:
        ts = pd.Timestamp(d)
        px = self.close[:ts]
        if px.empty:
            return None
        sma = self.sma[:ts].iloc[-1]
        return MarketState(spy_price=float(px.iloc[-1]), spy_sma200=None if np.isnan(sma) else float(sma))


def simulate(
    cfg: StrategyConfig,
    rounds: list[tuple[object, dict[str, Signal]]],
    spy: SpyMarket,
    contribution: float = 1_000.0,
    min_round_size: int = 150,
    end: date | None = None,
    schedule: list[date] | None = None,
    fee_per_order: float = 0.0,
    dead_line: float = 0.12,
) -> SimResult:
    """Replay `rounds` in order and rebalance on each date in `schedule`.

    Default schedule: every round with at least `min_round_size` analyses (a batch), as in
    the live system where a rebalance follows each batch. Pass the real snapshot dates to
    reproduce the actual paper record exactly. Each rebalance sees every analysis dated on
    or before it; smaller rounds (one-off manual analyses) only update signal state."""
    if schedule is None:
        schedule = [d for d, sigs in rounds if len(sigs) >= min_round_size]
    schedule = sorted(d for d in schedule if end is None or d <= end)

    res = SimResult(cfg.name)
    states: dict = {}
    holdings: dict[str, Position] = {}
    first_buy: dict[str, date] = {}
    cash = invested = spy_shares = fees = 0.0
    ptr = 0

    for d in schedule:
        while ptr < len(rounds) and rounds[ptr][0] <= d:
            update_states(states, rounds[ptr][1], ptr, cfg)
            ptr += 1
        if ptr == 0:
            continue
        idx = ptr - 1
        market = spy.at(d)
        if market is None:
            continue
        cash += contribution
        invested += contribution
        spy_shares += contribution / market.spy_price

        cov = coverage(rounds[idx][1])
        orders = decide(cfg, holdings, cash, states, idx, cov, market)

        for o in orders:
            rec = TradeRecord(d, o)
            if o.action == "sell":
                pos = holdings[o.ticker]
                rec.realized_pnl = o.total - pos.cost_basis * (o.shares / pos.shares)
                rec.holding_days = (d - first_buy[o.ticker]).days if o.ticker in first_buy else None
            else:
                first_buy.setdefault(o.ticker, d)
            res.trades.append(rec)
        holdings, cash = apply_orders(holdings, cash, orders)
        cash -= fee_per_order * len(orders)
        fees += fee_per_order * len(orders)
        for t in list(first_buy):
            if t not in holdings:
                del first_buy[t]

        values = {t: p.shares * (states[t].last_price or 0) for t, p in holdings.items()}
        nav = cash + sum(values.values())
        dead = sum(v for t, v in values.items() if (u := states[t].upside()) is not None and u < dead_line)
        res.rounds.append(RoundRecord(
            date=d, nav=nav, cash=cash, invested=invested, spy_value=spy_shares * market.spy_price,
            holdings=len(holdings), trades=len(orders),
            risk_off=bool(cfg.trend_filter and market.risk_off), skipped=cov < cfg.min_coverage,
            fees=fees, dead_pct=dead / nav if nav > 0 else 0.0,
        ))
    return res


# ── metrics ──────────────────────────────────────────────────────────────────

def _twr_index(nav: np.ndarray, flows: np.ndarray) -> np.ndarray:
    """Time-weighted return index; flows arrive at the start of each period."""
    idx = [1.0]
    for i in range(1, len(nav)):
        base = nav[i - 1] + flows[i]
        idx.append(idx[-1] * (nav[i] / base if base > 0 else 1.0))
    return np.array(idx)


def _max_drawdown(index: np.ndarray) -> float:
    peak = np.maximum.accumulate(index)
    return float((index / peak - 1).min())


def _irr_annual(dates: list[date], flows: list[float], final_value: float) -> float | None:
    """Money-weighted annualized return: contributions in, final value out."""
    t0 = dates[0]
    years = np.array([(d - t0).days / 365.25 for d in dates])
    cf = -np.array(flows, dtype=float)
    t_end = years[-1]

    def npv(r):
        return (cf / (1 + r) ** years).sum() + final_value / (1 + r) ** t_end

    lo, hi = -0.99, 10.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def summarize(res: SimResult) -> dict:
    df = res.frame()
    if df.empty:
        return {"strategy": res.name}
    flows = df["invested"].diff().fillna(df["invested"].iloc[0]).to_numpy()
    nav, spy = df["nav"].to_numpy(), df["spy_value"].to_numpy()
    sells = [t for t in res.trades if t.order.action == "sell"]
    sold = sum(t.order.total for t in sells)
    final, inv = nav[-1], df["invested"].iloc[-1]
    irr = _irr_annual(list(df["date"]), list(flows), final)
    spy_irr = _irr_annual(list(df["date"]), list(flows), spy[-1])
    return {
        "strategy": res.name,
        "final_value": round(final),
        "invested": round(inv),
        "gain_pct": round((final / inv - 1) * 100, 2),
        "spy_gain_pct": round((spy[-1] / inv - 1) * 100, 2),
        "excess_vs_spy": round(final - spy[-1]),
        "irr_pct": None if irr is None else round(irr * 100, 1),
        "spy_irr_pct": None if spy_irr is None else round(spy_irr * 100, 1),
        "max_drawdown_pct": round(_max_drawdown(_twr_index(nav, flows)) * 100, 2),
        "spy_max_drawdown_pct": round(_max_drawdown(_twr_index(spy, flows)) * 100, 2),
        "trades": len(res.trades),
        "sells": len(sells),
        "turnover_pct": round(sold / max(nav.mean(), 1) * 100, 1),
        "avg_cash_pct": round(float((df["cash"] / df["nav"]).mean() * 100), 1),
        "holdings_end": int(df["holdings"].iloc[-1]),
        "realized_pnl": round(sum(t.realized_pnl for t in sells)),
        "rounds_risk_off": int(df["risk_off"].sum()),
        "fees": round(float(df["fees"].iloc[-1]), 2),
        "avg_dead_money_pct": round(float(df["dead_pct"].mean() * 100), 1),
        "rounds_skipped": int(df["skipped"].sum()),
    }


# ── pool money model (matches app/trading: deposit pool, weekly draw cap, proceeds) ──

@dataclass
class PoolRound:
    date: date
    nav: float
    pool: float
    proceeds: float
    drawn_total: float
    spy_value: float
    holdings: int
    buys: int
    sells: int
    fees: float
    risk_off: bool
    dead_pct: float


def simulate_pool(
    cfg: StrategyConfig,
    rounds: list[tuple[object, dict[str, Signal]]],
    spy: SpyMarket,
    pool: float,
    weekly: float,
    fee_per_order: float = 1.0,
    fx_fee_every: float = 1000.0,
    fx_fee: float = 2.0,
    schedule: list[date] | None = None,
    min_round_size: int = 150,
    dead_line: float = 0.12,
) -> list[PoolRound]:
    """Live money model: each round may draw at most `weekly` from `pool`; sale proceeds
    are spent first and otherwise held. The benchmark buys SPY with exactly the new money
    drawn and holds the rest of the pool as cash, like the live audit. An FX fee is charged
    per `fx_fee_every` of new money converted."""
    if schedule is None:
        schedule = [d for d, sigs in rounds if len(sigs) >= min_round_size]
    states: dict = {}
    holdings: dict[str, Position] = {}
    proceeds, pool_left, drawn_total, spy_shares, fees, converted = 0.0, pool, 0.0, 0.0, 0.0, 0.0
    out: list[PoolRound] = []
    ptr = 0
    for d in sorted(schedule):
        while ptr < len(rounds) and rounds[ptr][0] <= d:
            update_states(states, rounds[ptr][1], ptr, cfg)
            ptr += 1
        if ptr == 0:
            continue
        idx = ptr - 1
        market = spy.at(d)
        if market is None:
            continue
        allowance = min(weekly, max(pool_left, 0.0))
        orders = decide(cfg, holdings, proceeds + allowance, states, idx, coverage(rounds[idx][1]), market)
        holdings, _ = apply_orders(holdings, 0.0, orders)
        sells = sum(o.total for o in orders if o.action == "sell")
        buys = sum(o.total for o in orders if o.action == "buy")
        f = fee_per_order * len(orders)
        fees += f
        available = proceeds + sells
        cost = buys + f
        from_proceeds = min(available, cost)
        draw = cost - from_proceeds
        proceeds = available - from_proceeds
        if draw > 0:
            converted += draw
            while converted >= fx_fee_every:  # one conversion per fx_fee_every drawn
                converted -= fx_fee_every
                pool_left -= fx_fee
                fees += fx_fee
        pool_left -= draw
        drawn_total += draw
        spy_shares += draw / market.spy_price
        values = {t: p.shares * (states[t].last_price or 0) for t, p in holdings.items()}
        nav = proceeds + pool_left + sum(values.values())
        dead = sum(v for t, v in values.items() if (u := states[t].upside()) is not None and u < dead_line)
        out.append(PoolRound(d, nav, pool_left, proceeds, drawn_total,
                             spy_shares * market.spy_price + (pool - drawn_total),
                             len(holdings), sum(o.action == "buy" for o in orders),
                             sum(o.action == "sell" for o in orders), fees,
                             bool(cfg.trend_filter and market.risk_off), dead / max(nav, 1e-9)))
    return out


def summarize_pool(name: str, rows: list[PoolRound], pool: float) -> dict:
    if not rows:
        return {"strategy": name}
    nav = np.array([r.nav for r in rows])
    invested = np.array([r.nav - r.pool - r.proceeds for r in rows])
    empty = next((i + 1 for i, r in enumerate(rows) if r.pool < 50.0), None)  # below a minimum order
    last = rows[-1]
    return {
        "strategy": name,
        "weeks": len(rows),
        "final_value": round(last.nav),
        "gain_pct_of_pool": round((last.nav / pool - 1) * 100, 2),
        "spy_same_draws": round(last.spy_value),
        "vs_spy_pct_of_pool": round((last.nav - last.spy_value) / pool * 100, 2),
        "max_drawdown_pct": round(float((nav / np.maximum.accumulate(nav) - 1).min()) * 100, 2),
        "pool_empty_week": empty,
        "new_money_drawn": round(last.drawn_total),
        "avg_idle_proceeds": round(float(np.mean([r.proceeds for r in rows]))),
        "max_idle_proceeds": round(float(max(r.proceeds for r in rows))),
        "buys": sum(r.buys for r in rows),
        "sells": sum(r.sells for r in rows),
        "max_buys_in_a_week": max(r.buys for r in rows),
        "fees": round(last.fees, 2),
        "fees_pct_of_pool": round(last.fees / pool * 100, 2),
        "avg_dead_money_pct": round(float(np.mean([r.dead_pct for r in rows])) * 100, 1),
        "rounds_risk_off": sum(r.risk_off for r in rows),
        "holdings_end": last.holdings,
        "invested_end": round(float(invested[-1])),
    }
