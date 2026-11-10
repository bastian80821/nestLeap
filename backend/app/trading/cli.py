"""
Broker trading commands (run inside the backend container: docker compose exec backend ...).

    python -m app.trading.cli status
    python -m app.trading.cli propose            # cron: after the Sunday batch
    python -m app.trading.cli approve <run_id>   # or reject <run_id>
    python -m app.trading.cli submit             # cron: weekdays during market hours
    python -m app.trading.cli sync [--eod]       # cron: after submit; --eod before the close
    python -m app.trading.cli reconcile          # cron: daily
    python -m app.trading.cli kill on|off --reason "..."
    python -m app.trading.cli adopt-baseline     # once, if the account already held universe stocks
    python -m app.trading.cli check              # verify broker connection (no orders placed)
    python -m app.trading.cli deposit 5000       # record money you added to the pool (pool currency)
    python -m app.trading.cli archive paper-sim  # file this mode's records under a label (when switching brokers)
    python -m app.trading.cli deposit -1000      # ...or took out
    python -m app.trading.cli audit [--run ID]   # cron: after the week's orders are done
    python -m app.trading.cli audit-statement    # cron: monthly, IBKR Flex statement vs records
    python -m app.trading.cli tax-report 2026 [--statement FILE|-]   # German tax worksheet (Anlage KAP/SO)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from ..config import settings
from ..database import Base, SessionLocal, engine, migrate_columns
from . import audit as au
from . import execution as ex
from . import models  # noqa: F401  (registers tables)
from .broker import make_broker


def _check(broker) -> int:
    print(f"broker={broker.name} mode={settings.trading_mode} account={broker.account_id()}")
    print("cash:", ", ".join(f"{c} {v:,.2f}" for c, v in broker.cash_balances().items()) or "none")
    pos = broker.positions()
    print(f"positions ({len(pos)}):", ", ".join(f"{p.ticker} {p.shares:g}" for p in pos.values()) or "none")
    px = broker.last_price("AAPL")
    print(f"AAPL price: {px}")
    if hasattr(broker, "what_if") and px:
        state = broker.what_if("AAPL", "buy", 0.25, round(px * 0.9, 2))
        print("what-if fractional order (0.25 AAPL, nothing placed):",
              {k: getattr(state, k, None) for k in ("status", "commission", "warningText", "initMarginChange")})
        if getattr(state, "warningText", "") or getattr(state, "status", "") in ("Inactive", ""):
            print("!! IBKR did not accept the fractional what-if order. Enable fractional trading for the "
                  "account, or set TRADING_FRACTIONAL=false (then only whole shares are bought).")
    return 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("status", "propose", "submit", "reconcile", "adopt-baseline", "check", "audit-statement"):
        sub.add_parser(name)
    sub.add_parser("deposit").add_argument("amount", type=float)
    sub.add_parser("archive").add_argument("label")
    sub.add_parser("audit").add_argument("--run", type=int, default=None)
    t = sub.add_parser("tax-report")
    t.add_argument("year", type=int)
    t.add_argument("--statement", default=None,
                   help="IBKR Flex XML for the year incl. Cash Transactions (path, or - for stdin) for dividends")
    t.add_argument("--out", default=None, help="output folder (default: /app/data/tax/<year>-<mode>)")
    for name in ("approve", "reject"):
        sub.add_parser(name).add_argument("run_id", type=int)
    sub.add_parser("sync").add_argument("--eod", action="store_true", help="cancel unfilled orders")
    k = sub.add_parser("kill")
    k.add_argument("state", choices=["on", "off"])
    k.add_argument("--reason", default="manual")
    args = ap.parse_args(argv)

    Base.metadata.create_all(bind=engine)
    migrate_columns()
    db = SessionLocal()
    try:
        if args.cmd == "status":
            print(json.dumps(ex.status(db), indent=2, default=str))
            return 0
        if args.cmd == "kill":
            ex.set_kill_switch(db, args.state == "on", args.reason)
            return 0
        if args.cmd == "tax-report":
            import os
            from . import tax_de

            xml = None
            if args.statement == "-":
                xml = sys.stdin.read()
            elif args.statement:
                xml = open(args.statement).read()
            data_dir = os.path.dirname(settings.trading_sim_state) or "."
            rep = tax_de.build_report(db, args.year, settings.trading_mode, xml,
                                      rate_cache=os.path.join(data_dir, "ecb_usd_eur.json"))
            out = tax_de.write_report(rep, args.out or os.path.join(data_dir, "tax", f"{args.year}-{settings.trading_mode}"))
            print(tax_de.summary_text(rep))
            print(f"\nDetail files (CSV, ';'-separated) in {out}")
            return 0
        if args.cmd == "archive":
            print(ex.archive_book(db, args.label))
            return 0
        if args.cmd in ("approve", "reject"):
            run = ex.decide_run(db, args.run_id, approve=args.cmd == "approve", who="cli")
            print(f"run {run.id}: {run.status}")
            return 0

        broker = make_broker()
        try:
            if args.cmd == "check":
                return _check(broker)
            if args.cmd == "propose":
                run = ex.propose(db, broker)
                print(f"run: {run.id} {run.status}" if run else "no run")
            elif args.cmd == "submit":
                print(f"placed {ex.submit(db, broker)} orders")
            elif args.cmd == "sync":
                print(ex.sync(db, broker, end_of_day=args.eod))
            elif args.cmd == "reconcile":
                ok = ex.reconcile(db, broker)
                print("reconciled" if ok else "MISMATCH — kill switch engaged")
                return 0 if ok else 2
            elif args.cmd == "adopt-baseline":
                ex.adopt_baseline(db, broker)
            elif args.cmd == "deposit":
                pool = ex.record_deposit(db, args.amount, broker, note="cli")
                print(f"pool now {settings.trading_currency} {pool:,.2f}")
            elif args.cmd == "audit":
                report = au.weekly_audit(db, broker, args.run)
                if report is None:
                    print("no runs to audit")
                    return 0
                for c in report.checks:
                    print(f"{'ok ' if c['ok'] else 'XX '}{c['name']:18} {c['detail']}")
                print(json.dumps(report.performance, indent=1))
                return 0 if report.passed else 2
            elif args.cmd == "audit-statement":
                if not (settings.ib_flex_token and settings.ib_flex_query_id):
                    print("Set IB_FLEX_TOKEN and IB_FLEX_QUERY_ID to enable the statement audit")
                    return 0
                report = au.statement_audit(db, au.fetch_flex_statement(settings.ib_flex_token, settings.ib_flex_query_id))
                for c in report.checks:
                    print(f"{'ok ' if c['ok'] else 'XX '}{c['name']:18} {c['detail']}")
                return 0 if report.passed else 2
        finally:
            if hasattr(broker, "close"):
                broker.close()
        return 0
    except Exception as e:
        ex.event(db, f"{args.cmd}_error", f"{type(e).__name__}: {e}", level="error")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
