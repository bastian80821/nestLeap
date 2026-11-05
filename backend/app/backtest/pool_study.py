"""
The live money model under replay, crises and synthetic markets.

    python -m app.backtest.pool_study --db ../backtest_data/nestleap-YYYY-MM-DD.db

Setup: EUR 5,000 pool, at most EUR 400 of new money a week, at most 2 buys a week,
$1 per order, USD 2 per EUR 1,000 converted. Two cases:
    one-off   the EUR 5,000 lasts ~12.5 weeks, then only sale proceeds are reinvested
    topped-up you keep the pool topped up, so EUR 400 is available every week
"""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from ..analysis.strategy import LEGACY, V2_LIVE
from .data import daily_closes, load_latest_signals, load_rounds
from .signal_model import calibrate, generate_rounds
from .simulator import SpyMarket, simulate_pool, summarize_pool
from .stress import SCENARIOS, WARMUP_WEEKS, _bootstrap_path, _init_worker, _G, GFC_BLOCK

STRATS = [
    V2_LIVE,
    V2_LIVE.with_(name="v2-live exit at once", confirm_rounds=1, trim_fraction=1.0),
    V2_LIVE.with_(name="v2-live no trend filter", trend_filter=False),
    LEGACY.with_(name="legacy top2", top_n=2),
]
BASE = V2_LIVE.with_(name="baseline equal-weight (no fees)", buy_upside=-10.0, sell_upside=-10.0, confirm_rounds=1,
                     top_n=10_000, weighting="equal", max_position_pct=1.0, cap_trim_pct=float("inf"),
                     cap_floor=0.0, trend_filter=False, min_coverage=0.0, min_trade_value=0.0)


def _cases(fx: float, weeks: int):
    return {"one-off EUR 5k": (5000 * fx, 400 * fx), "topped-up EUR 400/wk": (400 * fx * (weeks + 1), 400 * fx)}


def _run_all(rounds, spy, schedule, fx, tag):
    out = []
    for case, (pool, weekly) in _cases(fx, len(schedule)).items():
        base = summarize_pool(BASE.name, simulate_pool(BASE, rounds, spy, pool, weekly, fee_per_order=0.0,
                                                       fx_fee=0.0, schedule=schedule), pool)
        for cfg in STRATS:
            r = summarize_pool(cfg.name, simulate_pool(cfg, rounds, spy, pool, weekly, schedule=schedule), pool)
            r["vs_baseline_pct_of_pool"] = round((r["final_value"] - base["final_value"]) / pool * 100, 2)
            r.update(tag, case=case)
            out.append(r)
        base.update(tag, case=case, vs_baseline_pct_of_pool=0.0)
        out.append(base)
    return out


def _hist_job(args):
    name, start, end, ic, seed, fx = args
    w = _G["weekly"].loc[start:end]
    stocks = [c for c in w.columns if c != "SPY" and pd.notna(w[c].iloc[0])]
    rounds = generate_rounds(w[stocks].ffill(), _G["cal"], np.random.default_rng(seed), target_ic=ic, noise="new")
    return _run_all(rounds, _G["spy_daily"], [d for d, _ in rounds], fx, {"scenario": name, "ic": ic})


def _synth_job(args):
    kind, ic, seed, fx = args
    weekly = _G["weekly"].loc["2006-01-01":]
    full = [c for c in weekly.columns if weekly[c].notna().all()]
    lr = np.log(weekly[full]).diff().dropna().to_numpy()
    rng = np.random.default_rng(seed)
    path = _bootstrap_path(lr, WARMUP_WEEKS + 104, rng)
    if kind == "with 2008 crash":
        crash = np.log(weekly[full].loc[GFC_BLOCK[0]:GFC_BLOCK[1]]).diff().dropna().to_numpy()
        at = WARMUP_WEEKS + rng.integers(0, 104 - len(crash))
        path[at:at + len(crash)] = crash
    dates = pd.date_range("2030-01-04", periods=len(path) + 1, freq="W-FRI")
    prices = pd.DataFrame(100 * np.exp(np.vstack([np.zeros(len(full)), np.cumsum(path, axis=0)])),
                          index=dates, columns=full)
    rounds = generate_rounds(prices[[c for c in full if c != "SPY"]], _G["cal"], rng, target_ic=ic, noise="new")
    return _run_all(rounds, SpyMarket(prices["SPY"], window=40), [d for d, _ in rounds][WARMUP_WEEKS:], fx,
                    {"scenario": f"synthetic {kind}", "ic": ic})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--fx", type=float, default=None, help="USD per EUR (default: live rate)")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--paths", type=int, default=150)
    ap.add_argument("--out", default="../backtest_data")
    args = ap.parse_args(argv)

    fx = args.fx
    if fx is None:
        from ..analysis.portfolio import _get_live_price
        fx = _get_live_price("EURUSD=X") or 1.15
    print(f"EUR/USD {fx:.4f}: pool ${5000 * fx:,.0f}, new money ${400 * fx:,.0f}/week\n")

    rounds = load_rounds(args.db)
    spy_real = SpyMarket(daily_closes(["SPY"], start=str((pd.Timestamp(rounds[0][0]) - pd.Timedelta(days=400)).date()),
                                      adjusted=False)["SPY"])
    sched = [d for d, s in rounds if len(s) >= 150 and sum(1 for x in s.values() if x.fair_value) > 100]
    replay = pd.DataFrame(_run_all(rounds, spy_real, sched, fx, {"scenario": "replay: real 29 weeks", "ic": "live"}))

    cal = calibrate(load_latest_signals(args.db))
    analyses = load_latest_signals(args.db)
    daily = daily_closes(sorted(analyses.ticker.unique()) + ["SPY"], start="1999-01-01", adjusted=True)
    ics = [0.0, round(max(cal.ic, 0.0), 3)]
    jobs_h = [(n, s, e, ic, seed, fx) for n, (s, e) in SCENARIOS.items() for ic in ics for seed in range(args.seeds)]
    jobs_s = [(k, ic, 30_000 + seed, fx) for k in ("normal", "with 2008 crash") for ic in ics for seed in range(args.paths)]
    rows = []
    with ProcessPoolExecutor(max(1, (os.cpu_count() or 2) - 1), initializer=_init_worker, initargs=(daily, cal, "new")) as ex:
        for r in ex.map(_hist_job, jobs_h, chunksize=4):
            rows.extend(r)
        for r in ex.map(_synth_job, jobs_s, chunksize=4):
            rows.extend(r)
    stress = pd.DataFrame(rows)
    replay.to_csv(os.path.join(args.out, "pool_replay.csv"), index=False)
    stress.to_csv(os.path.join(args.out, "pool_stress_runs.csv"), index=False)

    cols = ["final_value", "gain_pct_of_pool", "spy_same_draws", "vs_spy_pct_of_pool", "max_drawdown_pct",
            "pool_empty_week", "avg_idle_proceeds", "max_idle_proceeds", "buys", "sells", "max_buys_in_a_week",
            "fees_pct_of_pool", "avg_dead_money_pct"]
    with pd.option_context("display.width", 250, "display.max_columns", 30, "display.max_rows", 300):
        print("== Replay on the real 29 weeks of Gemini analyses")
        print(replay.set_index(["case", "strategy"])[cols].to_string())
        g = stress.groupby(["case", "scenario", "ic", "strategy"], sort=False)
        agg = pd.DataFrame({
            "runs": g.size(),
            "med_vs_spy_pct": g.vs_spy_pct_of_pool.median(),
            "p10_vs_spy_pct": g.vs_spy_pct_of_pool.quantile(0.1),
            "beat_spy_pct": g.vs_spy_pct_of_pool.apply(lambda s: (s > 0).mean() * 100),
            "med_vs_baseline_pct": g.vs_baseline_pct_of_pool.median(),
            "med_maxdd_pct": g.max_drawdown_pct.median(),
            "med_idle_proceeds": g.avg_idle_proceeds.median(),
            "med_sells": g.sells.median(),
            "fees_pct": g.fees_pct_of_pool.median(),
            "dead_money_pct": g.avg_dead_money_pct.mean(),
        }).round(1)
        agg.to_csv(os.path.join(args.out, "pool_stress_summary.csv"))
        print("\n== Crises and synthetic markets (percentages are of the pool)")
        print(agg.to_string())


if __name__ == "__main__":
    main()
