"""
Summarize a prompt A/B run (JSON produced on the server by a dry-run script):
for each ticker, two runs with the previous assessment as prior and two runs without.

    python -m app.backtest.prompt_ab ../backtest_data/prompt_ab_raw.json
"""

from __future__ import annotations

import json
import math
import re
import statistics as st
import sys


def _fv(r):
    return r and r.get("fair_value")


def main(path: str):
    rows = json.load(open(path))
    rows = [r for r in rows if "error" not in r]
    n = len(rows)
    calls = sum(1 for r in rows for k in ("prior1", "prior2", "noprior1", "noprior2"))
    failed = sum(1 for r in rows for k in ("prior1", "prior2", "noprior1", "noprior2") if not _fv(r.get(k)))
    print(f"{n} tickers, {calls} Gemini calls, {failed} failed or unparseable ({failed / calls:.0%})\n")

    def logdiff(a, b):
        return abs(math.log(a / b)) * 100 if a and b else None

    def med(xs):
        xs = [x for x in xs if x is not None]
        return (st.median(xs), len(xs)) if xs else (float("nan"), 0)

    # 1. Run-to-run randomness on identical inputs.
    for arm in ("prior", "noprior"):
        m, k = med([logdiff(_fv(r.get(f"{arm}1")), _fv(r.get(f"{arm}2"))) for r in rows])
        flips = sum(1 for r in rows if r.get(f"{arm}1") and r.get(f"{arm}2")
                    and r[f"{arm}1"]["valuation"] != r[f"{arm}2"]["valuation"])
        print(f"[{arm:7}] same inputs twice: median fair-value gap {m:.1f}% over {k} pairs; label disagreed {flips}x")

    # 2. Distance from the Oct 25 assessment, split by whether earnings came out since.
    print()
    for since in (False, True):
        grp = [r for r in rows if r["earnings_since"] == since]
        name = "reported earnings since Oct 25" if since else "no earnings since Oct 25"
        for arm in ("prior", "noprior"):
            m, k = med([logdiff(_fv(r.get(f"{arm}{i}")), r["prev_fv"]) for r in grp for i in (1, 2)])
            big = sum(1 for r in grp for i in (1, 2)
                      if (d := logdiff(_fv(r.get(f"{arm}{i}")), r["prev_fv"])) is not None and d > 3)
            print(f"{name:32} [{arm:7}] median move vs Oct 25 {m:.1f}% ({k} runs); moved >3%: {big}/{k}")

    # 3. Does the change note cite earnings when earnings happened?
    print()
    cites = re.compile(r"earning|quarter|Q[1-4]|result|guidance|report", re.I)
    for since in (True, False):
        grp = [r for r in rows if r["earnings_since"] == since]
        notes = [r[f"prior{i}"].get("changes_since_last") or "" for r in grp for i in (1, 2) if r.get(f"prior{i}")]
        hit = sum(1 for x in notes if cites.search(x))
        nochange = sum(1 for x in notes if x.lower().startswith("no material change"))
        label = "after earnings" if since else "no earnings   "
        print(f"change notes {label}: cite results {hit}/{len(notes)}, say 'no material change' {nochange}/{len(notes)}")

    print("\nPer ticker (fair values: Oct 25 -> prior runs | no-prior runs):")
    for r in sorted(rows, key=lambda r: (not r["earnings_since"], r["ticker"])):
        p = [_fv(r.get(f"prior{i}")) for i in (1, 2)]
        q = [_fv(r.get(f"noprior{i}")) for i in (1, 2)]
        fmt = lambda xs: "/".join(f"{x:.0f}" if x else "--" for x in xs)
        tag = "E" if r["earnings_since"] else " "
        print(f"  {tag} {r['ticker']:6} {r['prev_fv']:.0f} -> {fmt(p):11} | {fmt(q):11}  price {r['prev_price']:.0f}->{r['price']:.0f}")


if __name__ == "__main__":
    main(sys.argv[1])
