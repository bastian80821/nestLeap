# Backtesting

All tools drive the same rules the live rebalance uses (`app/analysis/strategy.py`).
Run from `backend/` with a copy of the production database:

```bash
python -m app.backtest.replay --db ../backtest_data/nestleap-YYYY-MM-DD.db --sweep
python -m app.backtest.stress --db ../backtest_data/nestleap-YYYY-MM-DD.db
python -m pytest tests
```

Outputs land in `backtest_data/` (git-ignored), next to cached price downloads.

## Replay (`replay.py`)

Re-runs the stored weekly Gemini analyses under different rules, on the real
rebalance dates. No lookahead: every analysis was produced live. First it checks
that the `legacy` preset reproduces the actual paper record exactly; if that ever
drifts, the engine and the live code have diverged.

## Stress tests and synthetic markets (`stress.py`)

There are no real Gemini analyses for past crises, and asking Gemini now would leak
hindsight. Signals come from `signal_model.py`, fitted to the live analyses:
how far fair value follows price (beta), its weekly noise, the score/upside link,
and the measured information coefficient (IC). Each test runs at IC 0 (no skill)
and at the live IC.

- Historical: today's universe through the dot-com bust, 2008, COVID, 2022, and a
  calm 2017 control.
- Synthetic: 2-year paths stitched from random 8-week blocks of real 2006–2026
  weekly returns, with and without a forced 2008-style crash.

Compare strategies against the equal-weight baseline, not only SPY: the universe is
today's large caps, so every strategy inherits survivorship bias, and the baseline
carries the same bias. These tests measure how the rules behave under stress
(drawdowns, turnover, cash handling); they cannot show whether Gemini picks winners.
Only the live record can.
