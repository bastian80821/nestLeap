"""
Dry-run the live rebalance against a COPY of the production database and print the
trades it would place. Uses live SPY and prices (network), writes only to a temp copy.

    python -m app.backtest.preview --db ../backtest_data/nestleap-YYYY-MM-DD.db [--strategy v2]
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--strategy", default="v2")
    args = ap.parse_args(argv)

    tmp = os.path.join(tempfile.mkdtemp(prefix="nestleap-preview-"), "copy.db")
    shutil.copy(args.db, tmp)
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp}"
    os.environ["PORTFOLIO_STRATEGY"] = args.strategy

    # Import only after the environment points at the copy.
    from ..analysis import portfolio
    from ..database import SessionLocal, migrate_columns
    from ..models import PortfolioSnapshot, PortfolioTrade

    migrate_columns()
    db = SessionLocal()
    last_trade = db.query(PortfolioTrade.id).order_by(PortfolioTrade.id.desc()).first()
    last_trade = last_trade[0] if last_trade else 0
    before = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.id.desc()).first()
    market = portfolio._spy_market_state()

    portfolio.rebalance_portfolio(db)

    after = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.id.desc()).first()
    trades = db.query(PortfolioTrade).filter(PortfolioTrade.id > last_trade).order_by(PortfolioTrade.id).all()
    holdings = portfolio._get_holdings(db)
    print(f"strategy={args.strategy}  SPY {market.spy_price:.2f} vs 200d SMA {market.spy_sma200:.2f} "
          f"({'RISK-OFF' if market.risk_off else 'risk-on'})")
    print(f"before: value ${before.total_value:,.0f}, cash ${before.cash:,.0f}  ->  "
          f"after: value ${after.total_value:,.0f}, cash ${after.cash:,.0f}, holdings {after.num_holdings}")
    for t in trades:
        print(f"  {t.action.upper():4} {t.ticker:6} ${t.total:>9,.2f}  {t.reason}")
    if not trades:
        print("  (no trades)")
    biggest = sorted(((p["shares"] * p["last_price"], tk) for tk, p in holdings.items()), reverse=True)[:5]
    print("largest positions after:", ", ".join(f"{tk} {v / after.total_value:.1%}" for v, tk in biggest))
    db.close()
    shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)


if __name__ == "__main__":
    main()
