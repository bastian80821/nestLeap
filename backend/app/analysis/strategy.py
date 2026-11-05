"""
Portfolio strategy rules — pure functions, no database or network access.

The live weekly rebalance (portfolio.py) and the backtester (app/backtest) both
drive these functions, so a replay exercises exactly the code that trades.

Flow per rebalance round:
    states = update_states(states, round_signals, round_idx, cfg)   # once per round, in order
    orders = decide(cfg, holdings, cash, states, round_idx, coverage, market)

Two presets:
    LEGACY — the original rules: sell anything Gemini labels Fair Value/Overvalued,
             buy the top-10 Gemini "Undervalued" by score, equal weight, no caps.
    V2     — smoothed fair value, buy/sell zones with a hold band in between,
             two-round sell confirmation, trims instead of full exits,
             conviction-weighted sizing with a per-stock cap, and a trend filter
             that holds cash while SPY is below its 200-day average.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace


# ── configuration ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StrategyConfig:
    name: str = "v2"

    # "gemini_label": act on Gemini's Undervalued/Fair Value/Overvalued label (legacy)
    # "smoothed":     act on smoothed fair value vs price (v2)
    signal: str = "smoothed"

    # Fair-value smoothing: EMA weight on the newest estimate (1.0 = no smoothing).
    # Off by default: the prompt now carries last week's assessment, which removed the
    # week-to-week noise (A/B: 0.0% median move with no news vs 6.3% without the prior),
    # and an EMA on top only delays sells by a week or more.
    fv_ema_alpha: float = 1.0
    # Ignore a ticker's signal if its last valid fair value is older than this many rounds.
    max_signal_age: int = 4

    # Zones on smoothed upside = smoothed_fair_value / price - 1.
    # Calibrated to Gemini's own labels: "Undervalued" starts near +12% upside.
    buy_upside: float = 0.12
    # Sell once the stock is no longer cheap: upside to smoothed fair value <= +5%.
    # The 29-week replay showed waiting for real overvaluation (e.g. -10%) almost never
    # sells, because Gemini's fair values drift up with the price; this keeps a
    # 7-point hold band between buy (+12%) and sell (+5%) to absorb noise.
    sell_upside: float = 0.05
    # Exits, at most `confirm_rounds` rounds after entering the sell zone:
    #   round 1 in the zone: sell `trim_fraction` (frees cash now, hedges a one-week blip)
    #   round `confirm_rounds`: sell the rest
    # With trim_fraction = 1.0 the whole position goes as soon as the zone is confirmed.
    confirm_rounds: int = 2
    trim_fraction: float = 0.5
    # Exit fully at once if this overvalued.
    full_exit_upside: float = -0.25
    # Close out a position rather than leave a remainder smaller than this.
    min_position_value: float = 50.0

    # Sizing
    top_n: int = 10
    weighting: str = "conviction"  # "equal" | "conviction"
    # Per-stock cap as a fraction of total portfolio value (1.0 = uncapped).
    max_position_pct: float = 0.10
    # Trim a position back to max_position_pct once it grows past this.
    cap_trim_pct: float = 0.12
    # Never cap a position below this dollar value: a small, young portfolio
    # (e.g. $200 a week into 2 stocks) could otherwise not deploy its cash.
    cap_floor: float = 0.0

    # Market regime: while SPY < its 200-day SMA, keep this much of the portfolio in cash.
    # Never sells holdings to raise cash — it only stops deploying new money.
    trend_filter: bool = True
    risk_off_cash_pct: float = 0.30

    # Safety: skip trading in a round where fewer than this fraction of analyses
    # produced a fair value (e.g. a Gemini outage).
    min_coverage: float = 0.90

    min_trade_value: float = 10.0

    def with_(self, **changes) -> "StrategyConfig":
        return replace(self, **changes)


LEGACY = StrategyConfig(
    name="legacy",
    signal="gemini_label",
    fv_ema_alpha=1.0,
    confirm_rounds=1,
    trim_fraction=1.0,
    full_exit_upside=math.inf,
    weighting="equal",
    max_position_pct=1.0,
    cap_trim_pct=math.inf,
    trend_filter=False,
    min_coverage=0.0,
)

V2 = StrategyConfig()

# Planned live setup: $200 a week, at most 2 buys a week to keep fees down.
V2_LIVE = V2.with_(name="v2-live", top_n=2, cap_floor=500.0, min_trade_value=50.0)

PRESETS = {"legacy": LEGACY, "v2": V2, "v2-live": V2_LIVE}


# ── data types ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Signal:
    """One analysis of one ticker in one round."""
    ticker: str
    price: float | None
    fair_value: float | None = None
    label: str | None = None  # Gemini valuation label
    score: float | None = None
    conviction: int | None = None


@dataclass
class TickerState:
    last_price: float | None = None
    last_label: str | None = None
    last_score: float | None = None
    last_conviction: int | None = None
    ema_fv: float | None = None
    fv_round: int | None = None  # round of the last valid fair value
    sell_streak: int = 0

    def upside(self) -> float | None:
        if self.ema_fv is None or not self.last_price:
            return None
        return self.ema_fv / self.last_price - 1

    def fresh(self, round_idx: int, cfg: StrategyConfig) -> bool:
        return self.fv_round is not None and round_idx - self.fv_round <= cfg.max_signal_age


@dataclass(frozen=True)
class Position:
    shares: float
    cost_basis: float = 0.0


@dataclass(frozen=True)
class MarketState:
    spy_price: float
    spy_sma200: float | None

    @property
    def risk_off(self) -> bool:
        return self.spy_sma200 is not None and self.spy_price < self.spy_sma200


@dataclass(frozen=True)
class Order:
    ticker: str
    action: str  # "buy" | "sell"
    shares: float
    price: float
    reason: str

    @property
    def total(self) -> float:
        return self.shares * self.price


# ── state ────────────────────────────────────────────────────────────────────

def update_states(
    states: dict[str, TickerState],
    signals: dict[str, Signal],
    round_idx: int,
    cfg: StrategyConfig,
) -> dict[str, TickerState]:
    """Fold one round of analyses into per-ticker state (mutates and returns `states`)."""
    for ticker, sig in signals.items():
        st = states.setdefault(ticker, TickerState())
        if sig.price and sig.price > 0:
            st.last_price = sig.price
        # Legacy semantics: the latest analysis row wins, even if Gemini failed (label None).
        st.last_label = sig.label
        st.last_score = sig.score
        st.last_conviction = sig.conviction

        if sig.fair_value and sig.fair_value > 0:
            if st.ema_fv is None or cfg.fv_ema_alpha >= 1.0:
                st.ema_fv = sig.fair_value
            else:
                st.ema_fv = cfg.fv_ema_alpha * sig.fair_value + (1 - cfg.fv_ema_alpha) * st.ema_fv
            st.fv_round = round_idx

            up = st.upside()
            st.sell_streak = st.sell_streak + 1 if (up is not None and up <= cfg.sell_upside) else 0
    return states


def coverage(signals: dict[str, Signal]) -> float:
    if not signals:
        return 0.0
    return sum(1 for s in signals.values() if s.fair_value and s.fair_value > 0) / len(signals)


# ── decisions ────────────────────────────────────────────────────────────────

def decide(
    cfg: StrategyConfig,
    holdings: dict[str, Position],
    cash: float,
    states: dict[str, TickerState],
    round_idx: int,
    round_coverage: float,
    market: MarketState | None = None,
) -> list[Order]:
    """Return this round's orders. `cash` must already include this round's contribution."""
    if round_coverage < cfg.min_coverage:
        return []

    def price_of(t: str) -> float | None:
        st = states.get(t)
        return st.last_price if st and st.last_price and st.last_price > 0 else None

    shares = {t: p.shares for t, p in holdings.items() if p.shares > 1e-9}
    total_value = cash + sum(s * (price_of(t) or 0) for t, s in shares.items())
    orders: list[Order] = []

    def sell(t: str, qty: float, reason: str):
        px = price_of(t)
        qty = min(qty, shares.get(t, 0))
        if not px or qty <= 1e-9 or qty * px < cfg.min_trade_value:
            return 0.0
        orders.append(Order(t, "sell", qty, px, reason))
        shares[t] -= qty
        return qty * px

    proceeds = 0.0

    # ── sells ────────────────────────────────────────────────────────────
    for t in sorted(shares):
        st = states.get(t)
        px = price_of(t)
        if not st or not px:
            continue

        if cfg.signal == "gemini_label":
            if st.last_label in ("Fair Value", "Overvalued"):
                score = f", score {st.last_score:.0f}" if st.last_score is not None else ""
                proceeds += sell(t, shares[t], f"{st.last_label}{score}")
            continue

        up = st.upside()
        if up is None or not st.fresh(round_idx, cfg) or st.sell_streak < 1:
            continue
        if up <= cfg.full_exit_upside or st.sell_streak >= cfg.confirm_rounds or cfg.trim_fraction >= 1.0:
            if st.sell_streak < cfg.confirm_rounds and up > cfg.full_exit_upside:
                continue  # trim_fraction 1.0: wait for confirmation, then sell everything
            qty, full = shares[t], True
        else:
            qty, full = shares[t] * cfg.trim_fraction, False
            if (shares[t] - qty) * px < cfg.min_position_value:
                qty, full = shares[t], True
        verb = "Exit" if full else f"Trim {cfg.trim_fraction:.0%}"
        proceeds += sell(t, qty, f"{verb}: {up:+.0%} upside to fair value, week {st.sell_streak} in sell zone")

    # ── cap trims ────────────────────────────────────────────────────────
    cap_value = max(cfg.max_position_pct * total_value, cfg.cap_floor)
    if cfg.max_position_pct < 1.0 and total_value > 0:
        trim_line = max(cfg.cap_trim_pct * total_value, cap_value * cfg.cap_trim_pct / cfg.max_position_pct)
        for t in sorted(shares):
            px = price_of(t)
            if not px:
                continue
            value = shares[t] * px
            if value > trim_line:
                proceeds += sell(t, (value - cap_value) / px, f"Trim to {cfg.max_position_pct:.0%} position cap")

    cash += proceeds

    # ── how much to deploy ───────────────────────────────────────────────
    deployable = cash
    if cfg.trend_filter and market is not None and market.risk_off:
        deployable = max(0.0, cash - cfg.risk_off_cash_pct * total_value)
    if deployable <= cfg.min_trade_value:
        return orders

    # ── buy candidates ───────────────────────────────────────────────────
    sold = {o.ticker for o in orders}
    candidates: list[tuple[str, TickerState, float]] = []  # (ticker, state, headroom)
    for t, st in states.items():
        px = price_of(t)
        if not px or st.last_score is None or t in sold:
            continue
        if cfg.signal == "gemini_label":
            if st.last_label != "Undervalued":
                continue
        else:
            up = st.upside()
            if up is None or not st.fresh(round_idx, cfg) or up < cfg.buy_upside:
                continue
        headroom = math.inf if cfg.max_position_pct >= 1.0 else cap_value - shares.get(t, 0) * px
        if headroom <= cfg.min_trade_value:
            continue
        candidates.append((t, st, headroom))

    candidates.sort(key=lambda c: (-(c[1].last_score or 0), c[0]))
    candidates = candidates[: cfg.top_n]
    if not candidates:
        return orders

    if cfg.weighting == "conviction":
        weights = {t: (st.last_score or 0) * ((st.last_conviction or 5) / 10) for t, st, _ in candidates}
    else:
        weights = {t: 1.0 for t, _, _ in candidates}
    alloc = _water_fill(deployable, weights, {t: h for t, _, h in candidates})

    for t, st, _ in candidates:
        amount = alloc.get(t, 0.0)
        px = price_of(t)
        if amount < cfg.min_trade_value or not px:
            continue
        if cfg.signal == "gemini_label":
            reason = f"Top-{cfg.top_n} undervalued, score {st.last_score:.0f}"
        else:
            reason = f"Buy: {st.upside():+.0%} upside to fair value, score {st.last_score:.0f}"
        orders.append(Order(t, "buy", amount / px, px, reason))
    return orders


def _water_fill(budget: float, weights: dict[str, float], caps: dict[str, float]) -> dict[str, float]:
    """Split `budget` proportionally to `weights`, never exceeding `caps`; redistribute spill."""
    alloc = {t: 0.0 for t in weights}
    active = {t for t, w in weights.items() if w > 0}
    remaining = budget
    while remaining > 1e-9 and active:
        wsum = sum(weights[t] for t in active)
        if wsum <= 0:
            break
        spilled = 0.0
        for t in list(active):
            share = remaining * weights[t] / wsum
            room = caps[t] - alloc[t]
            if share >= room:
                alloc[t] += room
                spilled += share - room
                active.discard(t)
            else:
                alloc[t] += share
        remaining = spilled
    return alloc


# ── helpers for callers ──────────────────────────────────────────────────────

def apply_orders(
    holdings: dict[str, Position], cash: float, orders: list[Order]
) -> tuple[dict[str, Position], float]:
    """Apply orders to holdings/cash (average-cost basis). Returns new copies."""
    out = dict(holdings)
    for o in orders:
        pos = out.get(o.ticker, Position(0.0, 0.0))
        if o.action == "buy":
            out[o.ticker] = Position(pos.shares + o.shares, pos.cost_basis + o.total)
            cash -= o.total
        else:
            frac = o.shares / pos.shares if pos.shares > 0 else 1.0
            left = pos.shares - o.shares
            if left <= 1e-6:
                out.pop(o.ticker, None)
            else:
                out[o.ticker] = Position(left, pos.cost_basis * (1 - frac))
            cash += o.total
    return out, cash


def build_rounds(records) -> list[tuple[object, dict[str, Signal]]]:
    """Group analysis records into rebalance rounds, one per calendar day (UTC).

    `records` yields (ticker, analyzed_at: datetime, price, fair_value, label, score, conviction)
    in chronological order; within a day the latest analysis of a ticker wins.
    Returns [(date, {ticker: Signal})] sorted by date.
    """
    rounds: dict[object, dict[str, Signal]] = {}
    for ticker, analyzed_at, price, fv, label, score, conviction in records:
        rounds.setdefault(analyzed_at.date(), {})[ticker] = Signal(
            ticker=ticker, price=price, fair_value=fv, label=label, score=score, conviction=conviction
        )
    return sorted(rounds.items(), key=lambda kv: kv[0])
