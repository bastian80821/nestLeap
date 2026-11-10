import math

import pytest

from app.analysis.strategy import (
    LEGACY,
    V2,
    MarketState,
    Position,
    Signal,
    _water_fill,
    apply_orders,
    coverage,
    decide,
    update_states,
)


def sig(t, price, fv=None, label=None, score=70, conviction=5):
    return Signal(ticker=t, price=price, fair_value=fv, label=label, score=score, conviction=conviction)


# Cash alongside a $1,000 test position so it stays under the 10% cap; no other
# candidates exist in these tests, so the cash is never deployed.
CASH = 19_000


def run_rounds(cfg, rounds):
    states = {}
    for i, r in enumerate(rounds):
        update_states(states, {s.ticker: s for s in r}, i, cfg)
    return states, len(rounds) - 1


# ── legacy ───────────────────────────────────────────────────────────────────

def test_legacy_sells_fair_value_and_buys_top_n_equal_weight():
    universe = [sig(f"U{i}", 10, fv=15, label="Undervalued", score=90 - i) for i in range(12)]
    universe.append(sig("HELD", 10, fv=10.5, label="Fair Value", score=60))
    states, idx = run_rounds(LEGACY, [universe])
    orders = decide(LEGACY, {"HELD": Position(10, 100)}, 1000, states, idx, 1.0)

    sells = [o for o in orders if o.action == "sell"]
    buys = [o for o in orders if o.action == "buy"]
    assert [(o.ticker, o.shares) for o in sells] == [("HELD", 10)]
    assert [o.ticker for o in buys] == [f"U{i}" for i in range(10)]
    assert all(o.total == pytest.approx(110) for o in buys)  # (1000 + 100) / 10


def test_legacy_does_nothing_when_gemini_failed():
    states, idx = run_rounds(LEGACY, [[sig("A", 10, label=None), sig("B", 10, label=None)]])
    assert decide(LEGACY, {"A": Position(5, 50)}, 1000, states, idx, 0.0) == []


# ── v2 zones ─────────────────────────────────────────────────────────────────

def test_v2_hold_band_does_not_trade():
    # +8% upside: not cheap enough to buy (+12%), not expensive enough to sell (+5%).
    states, idx = run_rounds(V2, [[sig("A", 100, fv=108)]] * 3)
    orders = decide(V2, {"A": Position(1, 100)}, 1900, states, idx, 1.0)
    assert [o for o in orders if o.ticker == "A"] == []


def test_v2_sell_trims_half_in_week_one_and_exits_in_week_two():
    expensive = [sig("A", 100, fv=85)]  # 15% below price: in the sell zone
    states, idx = run_rounds(V2, [expensive])
    (trim,) = decide(V2, {"A": Position(10, 900)}, CASH, states, idx, 1.0)
    assert trim.action == "sell" and trim.shares == pytest.approx(5) and trim.reason.startswith("Trim")

    states, idx = run_rounds(V2, [expensive, expensive])
    (exit_,) = decide(V2, {"A": Position(5, 450)}, CASH, states, idx, 1.0)
    assert exit_.shares == pytest.approx(5) and exit_.reason.startswith("Exit")


def test_v2_full_exit_mode_waits_for_confirmation():
    cfg = V2.with_(trim_fraction=1.0)
    expensive = [sig("A", 100, fv=85)]
    states, idx = run_rounds(cfg, [expensive])
    assert decide(cfg, {"A": Position(10, 900)}, CASH, states, idx, 1.0) == []
    states, idx = run_rounds(cfg, [expensive, expensive])
    (o,) = decide(cfg, {"A": Position(10, 900)}, CASH, states, idx, 1.0)
    assert o.shares == pytest.approx(10)


def test_v2_one_week_blip_only_costs_half():
    states, idx = run_rounds(V2, [[sig("A", 100, fv=130)], [sig("A", 100, fv=85)], [sig("A", 100, fv=130)]])
    assert states["A"].sell_streak == 0  # back out of the zone: the remaining half is kept
    assert all(o.action != "sell" for o in decide(V2, {"A": Position(5, 450)}, CASH, states, idx, 1.0))


def test_v2_full_exit_when_deeply_overvalued():
    deep = [sig("A", 100, fv=60)]
    states, idx = run_rounds(V2, [deep, deep])
    (order,) = decide(V2, {"A": Position(10, 900)}, CASH, states, idx, 1.0)
    assert order.shares == pytest.approx(10)
    assert order.reason.startswith("Exit")


def test_v2_small_remainder_is_closed_out():
    expensive = [sig("A", 100, fv=85)]
    states, idx = run_rounds(V2, [expensive, expensive])
    (order,) = decide(V2, {"A": Position(0.8, 80)}, CASH, states, idx, 1.0)  # half would leave $40
    assert order.shares == pytest.approx(0.8)


def test_v2_stale_signal_is_ignored():
    rounds = [[sig("A", 100, fv=60)], [sig("A", 100, fv=60)]] + [[sig("B", 10, fv=10)]] * 5
    states, idx = run_rounds(V2, rounds)
    assert not states["A"].fresh(idx, V2)
    assert all(o.ticker != "A" for o in decide(V2, {"A": Position(10, 900)}, CASH, states, idx, 1.0))


# ── smoothing ────────────────────────────────────────────────────────────────

def test_fair_value_ema():
    states, _ = run_rounds(V2.with_(fv_ema_alpha=0.4), [[sig("A", 100, fv=100)], [sig("A", 100, fv=150)]])
    assert states["A"].ema_fv == pytest.approx(0.4 * 150 + 0.6 * 100)


def test_failed_analysis_keeps_previous_fair_value():
    states, _ = run_rounds(V2, [[sig("A", 100, fv=130)], [sig("A", 95, fv=None)]])
    assert states["A"].ema_fv == 130 and states["A"].last_price == 95


# ── sizing ───────────────────────────────────────────────────────────────────

def test_v2_buys_respect_position_cap_and_spill_over():
    universe = [sig(f"U{i}", 10, fv=20, score=90 - i) for i in range(12)]
    states, idx = run_rounds(V2, [universe])
    # $10k portfolio, all cash: cap is $1k per stock, so 10 candidates absorb at most $10k.
    orders = decide(V2, {}, 10_000, states, idx, 1.0)
    assert all(o.total <= 1000 + 1e-6 for o in orders)
    assert sum(o.total for o in orders) == pytest.approx(10_000)


def test_v2_conviction_weighting():
    universe = [sig("HI", 10, fv=20, score=80, conviction=10), sig("LO", 10, fv=20, score=80, conviction=5)]
    states, idx = run_rounds(V2.with_(max_position_pct=1.0), [universe])
    orders = {o.ticker: o.total for o in decide(V2.with_(max_position_pct=1.0), {}, 300, states, idx, 1.0)}
    assert orders["HI"] == pytest.approx(200) and orders["LO"] == pytest.approx(100)


def test_v2_skips_capped_names_and_buys_next_best():
    universe = [sig("BIG", 10, fv=20, score=99)] + [sig(f"U{i}", 10, fv=20, score=50) for i in range(10)]
    states, idx = run_rounds(V2, [universe])
    # BIG is already 11% of a $10k portfolio: over the 10% cap but under the 12% trim line.
    orders = decide(V2, {"BIG": Position(110, 1100)}, 8900, states, idx, 1.0)
    assert "BIG" not in {o.ticker for o in orders}
    assert len([o for o in orders if o.action == "buy"]) == 10


def test_v2_trims_oversized_position_back_to_cap():
    states, idx = run_rounds(V2, [[sig("A", 10, fv=10.5)]])
    # A is $1,500 of a $10k portfolio (15%) -> trim to $1,000.
    (order,) = decide(V2, {"A": Position(150, 1000)}, 8500, states, idx, 1.0)
    assert order.action == "sell" and order.total == pytest.approx(500)


# ── safety & regime ──────────────────────────────────────────────────────────

def test_v2_skips_round_with_low_coverage():
    universe = [sig("A", 10, fv=20)] + [sig(f"X{i}", 10, fv=None) for i in range(9)]
    states, idx = run_rounds(V2, [universe])
    cov = coverage({s.ticker: s for s in universe})
    assert cov == pytest.approx(0.1)
    assert decide(V2, {}, 1000, states, idx, cov) == []


def test_v2_trend_filter_holds_cash_but_does_not_sell():
    universe = [sig(f"U{i}", 10, fv=20) for i in range(10)]
    states, idx = run_rounds(V2, [universe])
    risk_off = MarketState(spy_price=90, spy_sma200=100)
    # $10k portfolio: $8k invested in U0..U7 at cap ($1k each is 10%), $2k cash.
    holdings = {f"U{i}": Position(100, 1000) for i in range(8)}
    assert decide(V2, holdings, 2000, states, idx, 1.0, risk_off) == []  # 30% reserve > $2k cash

    orders = decide(V2, holdings, 2000, states, idx, 1.0, MarketState(110, 100))
    assert sum(o.total for o in orders) == pytest.approx(2000)


# ── helpers ──────────────────────────────────────────────────────────────────

def test_cap_floor_lets_small_portfolio_deploy():
    from app.analysis.strategy import V2_LIVE
    universe = [sig(f"U{i}", 10, fv=20, score=90 - i) for i in range(5)]
    states, idx = run_rounds(V2_LIVE, [universe])
    orders = decide(V2_LIVE, {}, 200, states, idx, 1.0)
    assert [o.ticker for o in orders] == ["U0", "U1"]
    assert sum(o.total for o in orders) == pytest.approx(200)


def test_water_fill_redistributes():
    alloc = _water_fill(100, {"a": 1, "b": 1, "c": 1}, {"a": 10, "b": math.inf, "c": math.inf})
    assert alloc["a"] == pytest.approx(10) and alloc["b"] == pytest.approx(45)


def test_apply_orders_tracks_cost_basis():
    states, idx = run_rounds(V2, [[sig("A", 100, fv=60)], [sig("A", 100, fv=60)]])
    orders = decide(V2, {"A": Position(10, 800)}, CASH, states, idx, 1.0)
    holdings, cash = apply_orders({"A": Position(10, 800)}, CASH, orders)
    assert "A" not in holdings and cash == pytest.approx(CASH + 1000)


# ── whole shares ─────────────────────────────────────────────────────────────

WHOLE = V2.with_(top_n=2, whole_shares=True, cap_floor=500.0, min_trade_value=50.0)


def _ranked(prices):
    """Tickers in rank order (first = best score), all in the buy zone."""
    return [sig(t, px, fv=px * 1.3, score=99 - i) for i, (t, px) in enumerate(prices)]


def test_whole_shares_buys_expensive_top_pick_then_fills_remainder():
    # This week's real situation: TSM $375 tops the ranking, ~$450 to spend.
    uni = _ranked([("TSM", 375), ("VLO", 346), ("EOG", 147), ("PSX", 246), ("NFLX", 63)])
    states, idx = run_rounds(WHOLE, [uni])
    orders = decide(WHOLE, {}, 450, states, idx, 1.0)
    assert [(o.ticker, o.shares) for o in orders] == [("TSM", 1.0), ("NFLX", 1.0)]
    assert sum(o.total for o in orders) <= 450


def test_whole_shares_split_evenly_when_affordable():
    uni = _ranked([("EOG", 147), ("PSX", 246), ("COP", 136)])
    states, idx = run_rounds(WHOLE, [uni])
    orders = decide(WHOLE, {}, 450, states, idx, 1.0)
    assert [(o.ticker, o.shares) for o in orders] == [("EOG", 1.0), ("PSX", 1.0)]
    assert all(float(o.shares).is_integer() for o in orders)


def test_whole_shares_skip_unaffordable_and_use_more_shares_when_cheap():
    uni = _ranked([("COST", 1046), ("NFLX", 63), ("KO", 70)])
    states, idx = run_rounds(WHOLE, [uni])
    orders = {o.ticker: o.shares for o in decide(WHOLE, {}, 450, states, idx, 1.0)}
    assert "COST" not in orders  # one share costs more than the whole budget
    assert orders == {"NFLX": 3.0, "KO": 3.0}  # ~$225 each: 3 x 63 = 189, then 3 x 70 = 210


def test_whole_shares_respect_position_cap():
    uni = _ranked([("AAA", 300)])
    states, idx = run_rounds(WHOLE, [uni])
    # $500 cap floor: already holding $400 of AAA leaves room for no further $300 share.
    assert decide(WHOLE, {"AAA": Position(4 / 3, 400)}, 450, states, idx, 1.0) == []
