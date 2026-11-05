"""
Stress tests and synthetic markets for the trading rules.

    python -m app.backtest.stress --db ../backtest_data/nestleap-2026-11-05.db

What this can and cannot tell you
---------------------------------
There are no real Gemini analyses for 2000-2023 (and asking Gemini now would leak
hindsight: it knows how those years ended). So signals here come from signal_model.py,
calibrated to Gemini's live behaviour. That makes these tests good at answering
"do the RULES behave sensibly under stress?" — drawdowns, cash handling, turnover,
whipsaw, the trend filter — and bad at answering "does Gemini pick winners?".
Each test runs at two skill levels:
    IC 0      — Gemini has no predictive power (the null hypothesis)
    IC live   — the predictive power measured in the 29 live weeks (weak, not significant)

1. Historical crises: real weekly prices of today's universe through past crashes.
   Survivorship bias: only companies that exist today are included, which flatters
   every strategy in crash windows (the ones that went bust are missing).
2. Synthetic markets: 2-year paths stitched from random 8-week blocks of real
   2006-2026 weekly returns (all stocks moved together, keeping correlations), with
   and without a forced 2008-style crash block.
"""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from ..analysis.strategy import LEGACY, V2
from .data import daily_closes, load_latest_signals
from .signal_model import Calibration, calibrate, generate_rounds
from .simulator import SpyMarket, simulate, summarize

# No-signal baseline: DCA equally into every stock in the universe, never sell.
# The universe is today's large caps, so it carries survivorship bias; comparing each
# strategy against this baseline (same universe, same bias) isolates what the rules add.
BASELINE = V2.with_(
    name="baseline: equal-weight universe", buy_upside=-10.0, sell_upside=-10.0, confirm_rounds=1,
    top_n=10_000, weighting="equal", max_position_pct=1.0, cap_trim_pct=float("inf"),
    trend_filter=False, min_coverage=0.0,
)

STRATEGIES = [
    LEGACY,
    V2,  # half in week 1 of the sell zone, the rest in week 2
    V2.with_(name="v2 sticky (EMA + wait 2wk)", fv_ema_alpha=0.4, trim_fraction=1.0),  # ~3-week delay
    V2.with_(name="v2 exit at once", confirm_rounds=1, trim_fraction=1.0),
    V2.with_(name="v2 no trend filter", trend_filter=False),
]

# (contribution per week, fee per order, strategy overrides). The baseline never pays fees:
# DCA-ing equally into 200 stocks weekly isn't a real option at $200, it's a yardstick.
SETUPS = {
    "$1000/wk top10": (1000.0, 0.0, {}),
    "$200/wk top2 $1 fee": (200.0, 1.0, {"top_n": 2, "cap_floor": 500.0, "min_trade_value": 50.0}),
}

SCENARIOS = {
    "Dot-com bust": ("2000-03-24", "2003-03-28"),
    "Global financial crisis": ("2007-10-12", "2010-03-26"),
    "COVID crash + rebound": ("2020-01-03", "2020-12-31"),
    "2022 rate shock": ("2022-01-07", "2023-06-30"),
    "Calm bull (control)": ("2017-01-06", "2017-12-29"),
}

GFC_BLOCK = ("2008-09-05", "2009-03-06")
WARMUP_WEEKS = 40
PATH_WEEKS = 104

# Each default nudged both ways; a robust rule set shouldn't fall off a cliff.
SENSITIVITY = [
    V2,
    V2.with_(name="ema 0.25", fv_ema_alpha=0.25), V2.with_(name="ema 0.6", fv_ema_alpha=0.6),
    V2.with_(name="buy +9%", buy_upside=0.09), V2.with_(name="buy +15%", buy_upside=0.15),
    V2.with_(name="sell +2%", sell_upside=0.02), V2.with_(name="sell +8%", sell_upside=0.08),
    V2.with_(name="cap 7%", max_position_pct=0.07, cap_trim_pct=0.09),
    V2.with_(name="cap 15%", max_position_pct=0.15, cap_trim_pct=0.18),
    V2.with_(name="risk-off cash 15%", risk_off_cash_pct=0.15),
    V2.with_(name="risk-off cash 50%", risk_off_cash_pct=0.50),
    V2.with_(name="top 5", top_n=5), V2.with_(name="top 20", top_n=20),
]

_G: dict = {}  # per-process globals for the worker pool


def _init_worker(daily: pd.DataFrame, cal: Calibration, noise: str = "new"):
    _G["daily"], _G["cal"], _G["noise"] = daily, cal, noise
    _G["weekly"] = daily.resample("W-FRI").last()
    _G["spy_daily"] = SpyMarket(daily["SPY"])


def _run_strategies(rounds, spy, schedule, tag: dict, strategies=None) -> list[dict]:
    out = []
    for setup, (contrib, fee, tweak) in SETUPS.items():
        rows = []
        cfgs = [(BASELINE, 0.0)] + [(c.with_(**{k: v for k, v in tweak.items() if c is not LEGACY or k == "top_n"}), fee)
                                     for c in (strategies or STRATEGIES)]
        for cfg, f in cfgs:
            r = summarize(simulate(cfg, rounds, spy, schedule=schedule, contribution=contrib, fee_per_order=f))
            r.update(tag)
            r["setup"] = setup
            r["excess_pct"] = round(r["excess_vs_spy"] / r["invested"] * 100, 2)
            rows.append(r)
        base = rows[0]["final_value"]
        for r in rows:
            r["vs_baseline_pct"] = round((r["final_value"] - base) / r["invested"] * 100, 2)
        out.extend(rows)
    return out


def _historical_job(args) -> list[dict]:
    scenario, start, end, ic, seed = args
    weekly, cal = _G["weekly"], _G["cal"]
    w = weekly.loc[start:end]
    stocks = [c for c in w.columns if c != "SPY" and pd.notna(w[c].iloc[0])]
    rounds = generate_rounds(w[stocks].ffill(), cal, np.random.default_rng(seed), target_ic=ic, noise=_G["noise"])
    return _run_strategies(rounds, _G["spy_daily"], [d for d, _ in rounds],
                           {"scenario": scenario, "ic": ic, "seed": seed})


def _bootstrap_path(rets: np.ndarray, n_weeks: int, rng, block: int = 8) -> np.ndarray:
    """Stationary bootstrap of whole cross-sectional weeks (keeps correlations)."""
    idx = np.empty(n_weeks, dtype=int)
    i = rng.integers(len(rets))
    for k in range(n_weeks):
        idx[k] = i
        i = rng.integers(len(rets)) if rng.random() < 1 / block else (i + 1) % len(rets)
    return rets[idx]


def _synthetic_job(args) -> list[dict]:
    kind, ic, seed = args[:3]
    strategies = args[3] if len(args) > 3 else None
    weekly = _G["weekly"].loc["2006-01-01":]
    full = [c for c in weekly.columns if weekly[c].notna().all()]
    lr = np.log(weekly[full]).diff().dropna().to_numpy()
    rng = np.random.default_rng(seed)

    path = _bootstrap_path(lr, WARMUP_WEEKS + PATH_WEEKS, rng)
    if kind == "with 2008 crash":
        crash = np.log(weekly[full].loc[GFC_BLOCK[0]:GFC_BLOCK[1]]).diff().dropna().to_numpy()
        at = WARMUP_WEEKS + rng.integers(0, PATH_WEEKS - len(crash))
        path[at:at + len(crash)] = crash

    dates = pd.date_range("2030-01-04", periods=len(path) + 1, freq="W-FRI")
    prices = pd.DataFrame(100 * np.exp(np.vstack([np.zeros(len(full)), np.cumsum(path, axis=0)])),
                          index=dates, columns=full)
    stocks = [c for c in full if c != "SPY"]
    rounds = generate_rounds(prices[stocks], _G["cal"], rng, target_ic=ic, noise=_G["noise"])
    spy = SpyMarket(prices["SPY"], window=40)
    schedule = [d for d, _ in rounds][WARMUP_WEEKS:]
    return _run_strategies(rounds, spy, schedule, {"scenario": f"synthetic {kind}", "ic": ic, "seed": seed},
                           strategies)


def _aggregate(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["setup", "scenario", "ic", "strategy"], sort=False)
    out = pd.DataFrame({
        "runs": g.size(),
        "median_vs_baseline_pct": g.vs_baseline_pct.median(),
        "beat_baseline_pct": g.vs_baseline_pct.apply(lambda s: (s > 0).mean() * 100),
        "median_excess_pct": g.excess_pct.median(),
        "p10_excess_pct": g.excess_pct.quantile(0.1),
        "beat_spy_pct": g.excess_pct.apply(lambda s: (s > 0).mean() * 100),
        "median_maxdd_pct": g.max_drawdown_pct.median(),
        "spy_maxdd_pct": g.spy_max_drawdown_pct.median(),
        "median_turnover_pct": g.turnover_pct.median(),
        "median_sells": g.sells.median(),
        "avg_cash_pct": g.avg_cash_pct.mean(),
        "risk_off_rounds": g.rounds_risk_off.median(),
        "dead_money_pct": g.avg_dead_money_pct.mean(),
        "fees_pct_invested": (g.fees.mean() / g.invested.mean() * 100),
    })
    return out.round(1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--seeds", type=int, default=20, help="signal draws per historical scenario")
    ap.add_argument("--paths", type=int, default=150, help="synthetic paths per kind")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[3] / "backtest_data"))
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--sensitivity", action="store_true", help="only run the parameter-sensitivity grid")
    ap.add_argument("--noise", choices=["new", "old"], default="new",
                    help="fair-value noise profile: new prompt (default) or old prompt")
    args = ap.parse_args(argv)

    analyses = load_latest_signals(args.db)
    cal = calibrate(analyses)
    print("Signal model:", cal.describe())
    tickers = sorted(analyses.ticker.unique())
    daily = daily_closes(tickers + ["SPY"], start="1999-01-01", adjusted=True)

    ics = [0.0, round(max(cal.ic, 0.0), 3)]

    if args.sensitivity:
        jobs = [(kind, ic, 20_000 + seed, SENSITIVITY) for kind in ("normal", "with 2008 crash")
                for ic in ics for seed in range(args.paths)]
        with ProcessPoolExecutor(args.workers, initializer=_init_worker, initargs=(daily, cal, args.noise)) as ex:
            raw = pd.DataFrame([r for res in ex.map(_synthetic_job, jobs, chunksize=4) for r in res])
        raw.to_csv(Path(args.out) / "sensitivity_runs.csv", index=False)
        agg = _aggregate(raw)
        agg.to_csv(Path(args.out) / "sensitivity_summary.csv")
        with pd.option_context("display.width", 250, "display.max_columns", 30, "display.max_rows", 200):
            print(agg[["median_vs_baseline_pct", "beat_baseline_pct", "median_maxdd_pct",
                       "median_turnover_pct", "avg_cash_pct"]].to_string())
        return agg
    jobs_h = [(name, s, e, ic, seed) for name, (s, e) in SCENARIOS.items() for ic in ics for seed in range(args.seeds)]
    jobs_s = [(kind, ic, 10_000 + seed) for kind in ("normal", "with 2008 crash") for ic in ics for seed in range(args.paths)]

    rows: list[dict] = []
    with ProcessPoolExecutor(args.workers, initializer=_init_worker, initargs=(daily, cal, args.noise)) as ex:
        for res in ex.map(_historical_job, jobs_h, chunksize=4):
            rows.extend(res)
        print(f"historical scenarios done ({len(jobs_h)} runs x {len(STRATEGIES)} strategies)")
        for res in ex.map(_synthetic_job, jobs_s, chunksize=4):
            rows.extend(res)
        print(f"synthetic paths done ({len(jobs_s)} paths x {len(STRATEGIES)} strategies)")

    raw = pd.DataFrame(rows)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    raw.to_csv(out / f"stress_runs_{args.noise}.csv", index=False)
    agg = _aggregate(raw)
    agg.to_csv(out / f"stress_summary_{args.noise}.csv")
    with pd.option_context("display.width", 250, "display.max_columns", 30, "display.max_rows", 200):
        print(agg.to_string())
    return agg


if __name__ == "__main__":
    main()
