"""
Replay the stored Gemini analyses under different trading rules.

Every analysis in the database was produced live, before the prices that followed
were known, so replaying them has no lookahead: it answers "what would these rules
have done with exactly the information we had at the time?"

    python -m app.backtest.replay --db ../backtest_data/nestleap-2026-11-05.db

First validates the engine: the LEGACY preset must reproduce the real paper record.
"""

from __future__ import annotations

import argparse
from datetime import date

import pandas as pd

from ..analysis.strategy import LEGACY, V2
from .data import daily_closes, load_rounds, load_snapshots
from .simulator import SpyMarket, simulate, summarize

VARIANTS = [
    LEGACY,
    V2,
    V2.with_(name="v2 sticky (EMA + wait 2wk)", fv_ema_alpha=0.4, trim_fraction=1.0),
    V2.with_(name="v2 exit at once", confirm_rounds=1, trim_fraction=1.0),
    V2.with_(name="v2 + EMA 0.4", fv_ema_alpha=0.4),
    V2.with_(name="v2 - position cap", max_position_pct=1.0, cap_trim_pct=float("inf")),
    V2.with_(name="v2 - conviction weights", weighting="equal"),
    V2.with_(name="v2 - trend filter", trend_filter=False),
    V2.with_(name="v2 sell at +2%", sell_upside=0.02),
    V2.with_(name="v2 sell at +8%", sell_upside=0.08),
]

# Planned live setup: $200 a week, 2 buys, ~$1 per order.
LIVE = dict(contribution=200.0, fee_per_order=1.0)
LIVE_TWEAK = dict(top_n=2, cap_floor=500.0, min_trade_value=50.0)


def sweep(rounds, spy, schedule, end) -> pd.DataFrame:
    """Grid over the sell rule: where the sell zone starts, confirmation, and trim size."""
    rows = []
    for sell_up in (0.10, 0.08, 0.05, 0.02, 0.0, -0.05, -0.10):
        for confirm in (1, 2):
            for trim in (0.5, 1.0):
                for alpha in (0.4, 1.0):
                    cfg = V2.with_(
                        name=f"sell<{sell_up:+.0%} c{confirm} trim{trim:.0%} a{alpha}",
                        sell_upside=sell_up, confirm_rounds=confirm, trim_fraction=trim, fv_ema_alpha=alpha,
                    )
                    r = summarize(simulate(cfg, rounds, spy, end=end, schedule=schedule))
                    r.update(sell_upside=sell_up, confirm=confirm, trim=trim, alpha=alpha)
                    rows.append(r)
    return pd.DataFrame(rows)


def validate(rounds, spy, snapshots: pd.DataFrame, schedule, end: date | None) -> pd.DataFrame:
    sim = simulate(LEGACY, rounds, spy, end=end, schedule=schedule).frame()
    snaps = snapshots.groupby("date").last().reset_index()
    merged = sim.merge(snaps, on="date", how="inner", suffixes=("_sim", "_actual"))
    merged["diff"] = merged["nav"] - merged["total_value"]
    merged["diff_pct"] = merged["diff"] / merged["total_value"] * 100
    return merged[["date", "nav", "total_value", "diff", "diff_pct", "invested", "total_invested"]]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--end", type=date.fromisoformat, default=None, help="last round to include")
    ap.add_argument("--csv", default=None, help="write the summary table here")
    ap.add_argument("--sweep", action="store_true", help="also grid-search the sell rule")
    args = ap.parse_args(argv)

    rounds = load_rounds(args.db)
    first = rounds[0][0]
    spy = SpyMarket(daily_closes(["SPY"], start=str((pd.Timestamp(first) - pd.Timedelta(days=400)).date()), adjusted=False)["SPY"])

    snapshots = load_snapshots(args.db)
    # Rebalance on the real record's dates so every variant gets identical contributions.
    schedule = sorted(set(snapshots["date"]))

    print("== Validation: LEGACY replay vs actual paper record")
    v = validate(rounds, spy, snapshots, schedule, args.end)
    print(f"rounds compared: {len(v)}; max |diff| {v['diff_pct'].abs().max():.2f}%; "
          f"final sim ${v['nav'].iloc[-1]:,.0f} vs actual ${v['total_value'].iloc[-1]:,.0f}")
    worst = v.loc[v["diff_pct"].abs().idxmax()]
    print(f"largest gap on {worst['date']}: sim ${worst['nav']:,.0f} vs actual ${worst['total_value']:,.0f}\n")

    rows = [summarize(simulate(cfg, rounds, spy, end=args.end, schedule=schedule)) for cfg in VARIANTS]
    table = pd.DataFrame(rows).set_index("strategy")
    cols = ["final_value", "gain_pct", "spy_gain_pct", "excess_vs_spy", "max_drawdown_pct",
            "spy_max_drawdown_pct", "trades", "sells", "turnover_pct", "avg_cash_pct",
            "avg_dead_money_pct", "holdings_end", "rounds_skipped"]
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print("== $1,000/week, top 10, no fees")
        print(table[cols].to_string())
        live_rows = []
        for cfg in VARIANTS:
            c = cfg.with_(**(LIVE_TWEAK if cfg is not LEGACY else {"top_n": 2}))
            live_rows.append(summarize(simulate(c, rounds, spy, end=args.end, schedule=schedule, **LIVE)))
        live = pd.DataFrame(live_rows).set_index("strategy")
        print("\n== Live plan: $200/week, top 2, $1 per order")
        print(live[cols + ["fees"]].to_string())
    if args.csv:
        table.to_csv(args.csv)
    if args.sweep:
        sw = sweep(rounds, spy, schedule, args.end)
        print("\n== Sell-rule sweep (sorted by final value)")
        cols = ["sell_upside", "confirm", "trim", "alpha", "final_value", "excess_vs_spy",
                "max_drawdown_pct", "sells", "turnover_pct", "realized_pnl"]
        print(sw.sort_values("final_value", ascending=False)[cols].to_string(index=False))
        print("\nMean final value by sell threshold:")
        print(sw.groupby("sell_upside")["final_value"].agg(["mean", "min", "max"]).round(0).to_string())
        print("\nMean final value by smoothing (alpha 1.0 = none):")
        print(sw.groupby("alpha")["final_value"].mean().round(0).to_string())
        if args.csv:
            sw.to_csv(args.csv.replace(".csv", "_sweep.csv"), index=False)
    return table


if __name__ == "__main__":
    main()
