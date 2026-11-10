"""
Audit: independent checks that the trading system did what it was allowed to do.

Weekly audit (after each week's orders are done) — critical failures trip the kill switch:
    event_chain        every audit-log row is intact (hash chain unbroken)
    order_history      each order's current state matches its last logged event
    decision_replay    recomputing the strategy from the stored inputs gives the same orders
    approvals          nothing reached the broker without an approval
    new_money_cap      new money drawn this week <= the weekly allowance (e.g. EUR 400)
    max_buys           at most N buy orders per week
    limit_prices       every fill respected its limit price
    ledger_integrity   every fill is fully booked in the ledger; no bucket below zero
    universe           only NestLeap-analysed stocks are held
    positions          broker positions match recorded fills
    foreign_trades     no executions in the account that NestLeap didn't place
    cash               account cash matches pool + proceeds (warning on small FX drift)
    fees               commissions in line with IBKR pricing (warning)

Monthly statement audit (IBKR Flex Web Service): the broker's own back-office statement,
fetched outside the trading API, must contain exactly the fills NestLeap recorded.

Each report also stores the event-chain head hash and sends it in the notification:
since the notification leaves the server, a later rewrite of the history is detectable
by comparing hashes.
"""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..analysis.strategy import MarketState, Position, StrategyConfig, decide
from ..config import settings
from . import execution as ex
from .broker import Broker, fx_rate, ibkr_fee
from .models import AuditReport, TradingEvent, TradingLedger, TradingOrder, TradingRun

SUBMITTED = ("submitted", "partially_filled", "filled", "cancelled", "failed")


def _check(name, ok, detail="", severity="critical"):
    return {"name": name, "ok": bool(ok), "severity": severity, "detail": detail}


# ── individual checks ────────────────────────────────────────────────────────

def check_event_chain(db: Session):
    prev = None
    for e in db.query(TradingEvent).order_by(TradingEvent.id):
        if e.prev_hash != prev:
            return _check("event_chain", False, f"event {e.id}: previous-hash link broken (row deleted or inserted?)")
        if ex.event_hash(prev, e.level, e.kind, e.message, e.details, e.created_at) != e.hash:
            return _check("event_chain", False, f"event {e.id} ({e.kind}) content was modified")
        prev = e.hash
    return _check("event_chain", True, f"intact, head {prev[:12] if prev else 'empty'}")


def check_order_history(db: Session, run: TradingRun):
    last: dict[int, dict] = {}
    for e in db.query(TradingEvent).filter_by(kind="order").order_by(TradingEvent.id):
        if e.details and e.details.get("run_id") == run.id:
            last[e.details["order_id"]] = e.details
    bad = []
    for o in db.query(TradingOrder).filter_by(run_id=run.id):
        d = last.get(o.id)
        if d is None:
            bad.append(f"#{o.id} {o.ticker} has no logged history")
            continue
        for field in ("status", "ticker", "side", "filled_qty", "avg_fill_price", "commission", "broker_order_id"):
            a, b = getattr(o, field), d.get(field)
            if isinstance(a, float) or isinstance(b, float):
                if abs((a or 0) - (b or 0)) > 1e-6:
                    bad.append(f"#{o.id} {field}: table {a} vs log {b}")
            elif a != b:
                bad.append(f"#{o.id} {field}: table {a!r} vs log {b!r}")
    return _check("order_history", not bad, "; ".join(bad) or "orders match their logged history")


def check_decision_replay(db: Session, run: TradingRun):
    inp = run.inputs or {}
    if not inp:
        return _check("decision_replay", False, "run has no stored inputs")
    cfg_dict = {k: (float("inf") if v == "inf" else v) for k, v in inp["config"].items()}
    cfg = StrategyConfig(**cfg_dict)
    from ..analysis.portfolio import _signal_rounds
    from ..analysis.strategy import coverage, update_states

    rounds = _signal_rounds(db, max_analysis_id=inp["max_analysis_id"])
    states: dict = {}
    for idx, (_, sigs) in enumerate(rounds):
        update_states(states, sigs, idx, cfg)
    if len(rounds) - 1 != inp["round_index"]:
        return _check("decision_replay", False, f"analysis history changed: {len(rounds) - 1} rounds now vs "
                      f"{inp['round_index']} at decision time")
    cov = coverage(rounds[-1][1])
    if abs(cov - inp["coverage"]) > 1e-9:
        return _check("decision_replay", False, f"coverage now {cov:.4f} vs {inp['coverage']:.4f} at decision time")
    holdings = {t: Position(v[0], v[1]) for t, v in inp["holdings"].items()}
    m = inp["market"]
    orders = decide(cfg, holdings, inp["cash_usd"], states, inp["round_index"], cov,
                    MarketState(m["spy_price"], m["spy_sma200"]))
    want = sorted((o.ticker, o.action, round(o.shares, 6)) for o in orders)
    got = sorted((o.ticker, o.side, round(o.strategy_quantity or o.quantity, 6))
                 for o in db.query(TradingOrder).filter_by(run_id=run.id))
    if want != got:
        return _check("decision_replay", False, f"recomputed {want} but recorded {got}")
    return _check("decision_replay", True, f"{len(want)} orders reproduced exactly from stored inputs")


def check_approvals(db: Session, run: TradingRun):
    sent = db.query(TradingOrder).filter(TradingOrder.run_id == run.id, TradingOrder.broker_order_id.isnot(None)).all()
    bad = [f"#{o.id} {o.ticker}" for o in sent if o.approved_at is None]
    if sent and not db.query(TradingEvent).filter(TradingEvent.kind == "order",
                                                  TradingEvent.message.like("%: approved%")).count():
        bad.append("no approval events logged")
    return _check("approvals", not bad, ("sent without approval: " + ", ".join(bad)) if bad
                  else f"{len(sent)} submitted orders, all approved first")


def check_new_money_cap(db: Session, run: TradingRun):
    cap = settings.trading_weekly_new_money
    drawn = ex.drawn_for_run(db, run.id)
    allowed = min(cap, max(run.pool_before or 0.0, 0.0))
    ok = drawn <= allowed * 1.005 + 0.01 and (run.allowance or 0) <= cap + 1e-9
    cur = settings.trading_currency
    return _check("new_money_cap", ok, f"drew {cur} {drawn:,.2f} of new money; allowed {cur} {allowed:,.2f}")


def check_max_buys(db: Session, run: TradingRun):
    n = db.query(TradingOrder).filter(TradingOrder.run_id == run.id, TradingOrder.side == "buy",
                                      TradingOrder.broker_order_id.isnot(None)).count()
    cap = settings.trading_max_buys_per_week
    return _check("max_buys", n <= cap, f"{n} buy orders sent (max {cap})")


def check_limit_prices(db: Session, run: TradingRun):
    bad = []
    for o in db.query(TradingOrder).filter(TradingOrder.run_id == run.id, TradingOrder.filled_qty > 0):
        if o.limit_price is None or o.avg_fill_price is None:
            bad.append(f"#{o.id} filled without a recorded limit/fill price")
        elif o.side == "buy" and o.avg_fill_price > o.limit_price + 0.01:
            bad.append(f"#{o.id} {o.ticker} bought at {o.avg_fill_price:.2f} > limit {o.limit_price:.2f}")
        elif o.side == "sell" and o.avg_fill_price < o.limit_price - 0.01:
            bad.append(f"#{o.id} {o.ticker} sold at {o.avg_fill_price:.2f} < limit {o.limit_price:.2f}")
    return _check("limit_prices", not bad, "; ".join(bad) or "all fills within limits")


def check_fees(db: Session, run: TradingRun):
    odd = []
    for o in db.query(TradingOrder).filter(TradingOrder.run_id == run.id, TradingOrder.filled_qty > 0):
        expected = ibkr_fee(o.filled_qty, o.avg_fill_price or 0)
        if (o.commission or 0) > max(expected * 1.5, expected + 0.5):
            odd.append(f"#{o.id} {o.ticker} fee ${o.commission:.2f} vs ~${expected:.2f}")
    return _check("fees", not odd, "; ".join(odd) or "commissions in line with IBKR pricing", severity="warning")


def check_ledger_integrity(db: Session, run: TradingRun):
    bad = []
    for o in db.query(TradingOrder).filter(TradingOrder.run_id == run.id, TradingOrder.filled_qty > 0,
                                           TradingOrder.status.in_(ex.TERMINAL_STATUSES)):
        value = o.filled_qty * (o.avg_fill_price or 0)
        rows = db.query(TradingLedger).filter_by(order_id=o.id).all()
        booked = sum(r.amount if r.currency == "USD" else r.amount * (r.fx_rate or 0) for r in rows)
        expected = (value - (o.commission or 0)) if o.side == "sell" else -(value + (o.commission or 0))
        if abs(booked - expected) > 0.02:
            bad.append(f"#{o.id} {o.ticker}: booked {booked:,.2f} vs fill {expected:,.2f}")
    pool, proceeds = ex.pool_balance(db), ex.proceeds_balance(db)
    if pool < -0.01:
        bad.append(f"pool below zero ({pool:,.2f})")
    if proceeds < -0.01:
        bad.append(f"proceeds below zero ({proceeds:,.2f})")
    return _check("ledger_integrity", not bad, "; ".join(bad) or "every fill fully booked; buckets non-negative")


def check_universe(db: Session, broker: Broker):
    allowed = ex.universe() | set(json.loads(ex.get_setting(db, f"position_baseline_{ex.mode()}", "{}")))
    outside = [t for t in ex.expected_positions(db) if t not in allowed]
    return _check("universe", not outside, ("held outside the universe: " + ", ".join(outside)) if outside
                  else "all holdings are analysed stocks")


def check_positions(db: Session, broker: Broker):
    allowed = ex.universe()
    actual = {t: p.shares for t, p in broker.positions().items() if t in allowed}
    expected = ex.expected_positions(db)
    diffs = [f"{t}: recorded {expected.get(t, 0):.4f}, broker {actual.get(t, 0):.4f}"
             for t in sorted(set(actual) | set(expected)) if abs(expected.get(t, 0) - actual.get(t, 0)) > 1e-3]
    return _check("positions", not diffs, "; ".join(diffs) or f"{len(actual)} positions match the broker")


def check_foreign_trades(db: Session, broker: Broker):
    foreign = ex.foreign_executions(db, broker)
    return _check("foreign_trades", not foreign,
                  "; ".join(f"{e.side} {e.ticker} {e.shares:g}" for e in foreign) or "none")


def check_cash(db: Session, broker: Broker, fx: float):
    physical, ledger = ex.cash_check(db, broker, fx)
    if physical < ledger * 0.95 - 5:
        return _check("cash", False, f"account ${physical:,.2f} far below recorded ${ledger:,.2f}")
    # Only missing money is a problem; extra cash in the account is never used by NestLeap.
    ok = physical >= ledger * 0.98 - 5
    extra = f" (+${physical - ledger:,.2f} not managed by NestLeap)" if physical > ledger * 1.02 + 5 else ""
    return _check("cash", ok, f"account ${physical:,.2f} vs recorded ${ledger:,.2f}{extra}", severity="warning")


# ── performance ──────────────────────────────────────────────────────────────

def spy_history(start: str):
    """Daily SPY closes from a week before `start` (fresh download, no cache). The margin
    keeps the range valid when the first draw is today, and gives a close for weekend draws."""
    import pandas as pd
    import yfinance as yf

    begin = (pd.Timestamp(start) - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    spy = yf.download("SPY", start=begin, auto_adjust=False, progress=False)["Close"].squeeze()
    spy.index = spy.index.tz_localize(None) if spy.index.tz is not None else spy.index
    return spy


def performance(db: Session, broker: Broker, fx: float) -> dict:
    """Strategy result in the pool currency, against SPY bought with the same new money."""
    cur, m = settings.trading_currency, ex.mode()
    rows = db.query(TradingLedger).filter_by(mode=m).order_by(TradingLedger.id).all()
    deposits = sum(r.amount for r in rows if r.bucket == "pool" and r.kind in ("deposit", "withdrawal"))
    draws = [r for r in rows if r.kind == "draw"]
    drawn = -sum(r.amount for r in draws)
    allowed = ex.universe()
    prices = {t: broker.last_price(t) for t in broker.positions() if t in allowed}
    holdings_usd = sum(p.shares * (prices.get(t) or p.avg_cost) for t, p in broker.positions().items() if t in allowed)
    nav = (holdings_usd + ex.proceeds_balance(db)) / fx + ex.pool_balance(db)

    spy_now = broker.last_price("SPY")
    bench = ex.pool_balance(db)  # undrawn money is the same in both
    if draws and spy_now:
        start = min(r.created_at for r in draws).date()
        spy = spy_history(str(start))
        for r in draws:
            px = spy[: r.created_at.strftime("%Y-%m-%d")]
            px = float(px.iloc[-1]) if len(px) else spy_now
            bench += (-r.amount * (r.fx_rate or fx) / px) * spy_now / fx
    else:
        bench += drawn  # nothing invested yet
    bench += sum(r.amount for r in rows if r.kind == "fx_fee")  # charge the benchmark the same FX costs

    orders = (db.query(TradingOrder).join(TradingRun, TradingRun.id == TradingOrder.run_id)
              .filter(TradingRun.mode == m, TradingOrder.filled_qty > 0).all())
    fees_usd = sum(o.commission or 0 for o in orders)
    fx_fees = -sum(r.amount for r in rows if r.kind == "fx_fee")
    return {
        "currency": cur, "fx_rate": round(fx, 4),
        "deposited": round(deposits, 2), "new_money_invested": round(drawn, 2),
        "pool_left": round(ex.pool_balance(db), 2), "proceeds_usd": round(ex.proceeds_balance(db), 2),
        "holdings_usd": round(holdings_usd, 2), "nav": round(nav, 2),
        "gain": round(nav - deposits, 2), "gain_pct_of_invested": round((nav - deposits) / drawn * 100, 2) if drawn else None,
        "spy_same_deposits_nav": round(bench, 2), "vs_spy": round(nav - bench, 2),
        "trades": len(orders), "fees_usd": round(fees_usd, 2), "fx_fees": round(fx_fees, 2),
        "positions": len(prices),
    }


# ── reports ──────────────────────────────────────────────────────────────────

def _finish(db: Session, kind: str, run_id: int | None, checks: list[dict], perf: dict | None) -> AuditReport:
    crit = [c for c in checks if not c["ok"] and c["severity"] == "critical"]
    warn = [c for c in checks if not c["ok"] and c["severity"] == "warning"]
    head = ex.chain_head(db)
    report = AuditReport(mode=ex.mode(), kind=kind, run_id=run_id, passed=not crit, critical_failures=len(crit),
                         warnings=len(warn), checks=checks, performance=perf, chain_head=head)
    db.add(report)
    db.commit()
    lines = [f"{'PASS' if not crit else 'FAIL'}: {len(checks) - len(crit) - len(warn)}/{len(checks)} checks ok"
             + (f", {len(warn)} warnings" if warn else "")]
    lines += [f"✗ {c['name']}: {c['detail']}" for c in crit + warn]
    if perf:
        cur = perf["currency"]
        lines.append(f"NAV {cur} {perf['nav']:,.2f} on {cur} {perf['deposited']:,.2f} deposited "
                     f"({cur} {perf['new_money_invested']:,.2f} invested); SPY with same deposits "
                     f"{cur} {perf['spy_same_deposits_nav']:,.2f}; fees ${perf['fees_usd']:,.2f}")
    lines.append(f"chain head {head}")
    ex.event(db, f"audit_{kind}", "\n".join(lines), level="error" if crit else ("warning" if warn else "info"),
             details={"report_id": report.id}, push=True)
    if crit:
        ex.set_kill_switch(db, True, f"Audit #{report.id} failed: " + ", ".join(c["name"] for c in crit))
    return report


def weekly_audit(db: Session, broker: Broker, run_id: int | None = None) -> AuditReport | None:
    q = db.query(TradingRun).filter_by(mode=ex.mode())
    run = q.filter_by(id=run_id).first() if run_id else q.order_by(TradingRun.id.desc()).first()
    if run is None:
        return None
    fx = fx_rate(settings.trading_currency) or run.fx_rate
    checks = [
        check_event_chain(db), check_order_history(db, run), check_decision_replay(db, run),
        check_approvals(db, run), check_new_money_cap(db, run), check_max_buys(db, run),
        check_limit_prices(db, run), check_ledger_integrity(db, run), check_universe(db, broker),
        check_positions(db, broker), check_foreign_trades(db, broker), check_cash(db, broker, fx),
        check_fees(db, run),
    ]
    try:
        perf = performance(db, broker, fx)
    except Exception as e:  # a report without performance is still a report
        perf = {"error": str(e)}
    return _finish(db, "weekly", run.id, checks, perf)


# ── IBKR statement (Flex Web Service) ────────────────────────────────────────

FLEX_SEND = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
FLEX_GET = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement"


def fetch_flex_statement(token: str, query_id: str, tries: int = 10) -> str:
    """Download an Activity Flex Query (configure it in IBKR Client Portal: Reports → Flex
    Queries, include the Trades section with orderReference)."""
    import httpx

    r = httpx.get(FLEX_SEND, params={"t": token, "q": query_id, "v": 3}, timeout=30)
    root = ET.fromstring(r.text)
    if root.findtext("Status") != "Success":
        raise RuntimeError(f"Flex request failed: {root.findtext('ErrorMessage') or r.text[:200]}")
    ref = root.findtext("ReferenceCode")
    for _ in range(tries):
        s = httpx.get(FLEX_GET, params={"t": token, "q": ref, "v": 3}, timeout=60)
        if "<FlexQueryResponse" in s.text:
            return s.text
        time.sleep(5)  # "statement generation in progress"
    raise RuntimeError("Flex statement not ready after waiting")


def flex_period(xml_text: str) -> tuple[str, str] | None:
    """(fromDate, toDate) as YYYYMMDD from the statement header, if present."""
    for st in ET.fromstring(xml_text).iter("FlexStatement"):
        a, b = st.attrib.get("fromDate"), st.attrib.get("toDate")
        if a and b:
            return a.replace("-", ""), b.replace("-", "")
    return None


def parse_flex_trades(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for t in root.iter("Trade"):
        a = t.attrib
        if a.get("assetCategory") != "STK":
            continue
        out.append({
            "ticker": a.get("symbol", "").replace(" ", "-"), "side": "buy" if a.get("buySell") == "BUY" else "sell",
            "shares": abs(float(a.get("quantity", 0))), "price": float(a.get("tradePrice", 0)),
            "commission": abs(float(a.get("ibCommission", 0))), "ref": a.get("orderReference", ""),
            "date": a.get("tradeDate", ""),
        })
    return out


def statement_audit(db: Session, xml_text: str) -> AuditReport:
    """Compare the broker's statement with recorded fills, both directions."""
    trades = parse_flex_trades(xml_text)
    by_order: dict[int, list[dict]] = {}
    foreign = []
    for t in trades:
        if t["ref"].startswith("nestleap-") and t["ref"][9:].isdigit():
            by_order.setdefault(int(t["ref"][9:]), []).append(t)
        else:
            foreign.append(t)
    checks, bad = [], []
    period = flex_period(xml_text)
    if period is None:
        dates = sorted(t["date"].replace("-", "") for t in trades if t["date"])
        period = (dates[0], dates[-1]) if dates else None
    for oid, ts in by_order.items():
        o = db.get(TradingOrder, oid)
        shares = sum(t["shares"] for t in ts)
        if o is None:
            bad.append(f"statement has order {oid} that NestLeap never recorded")
            continue
        avg = sum(t["shares"] * t["price"] for t in ts) / shares if shares else 0
        fee = sum(t["commission"] for t in ts)
        if abs(shares - (o.filled_qty or 0)) > 1e-4 or abs(avg - (o.avg_fill_price or 0)) > 0.01 \
                or abs(fee - (o.commission or 0)) > 0.05 or o.ticker != ts[0]["ticker"] or o.side != ts[0]["side"]:
            bad.append(f"#{oid} {o.ticker}: statement {shares:g}@{avg:.2f} fee {fee:.2f} vs recorded "
                       f"{o.filled_qty:g}@{o.avg_fill_price or 0:.2f} fee {o.commission or 0:.2f}")
    if period:
        recorded = (db.query(TradingOrder).join(TradingRun, TradingRun.id == TradingOrder.run_id)
                    .filter(TradingRun.mode == ex.mode(), TradingOrder.filled_qty > 0).all())
        for o in recorded:
            day = (o.submitted_at or o.updated_at)
            if day and period[0] <= day.strftime("%Y%m%d") <= period[1] and o.id not in by_order:
                bad.append(f"#{o.id} {o.ticker} recorded as filled but missing from the statement")
    checks.append(_check("statement_fills", not bad, "; ".join(bad) or f"{len(by_order)} orders match the statement"))
    checks.append(_check("statement_foreign", not foreign,
                         "; ".join(f"{t['side']} {t['ticker']} {t['shares']:g} on {t['date']}" for t in foreign)
                         or "no trades outside NestLeap"))
    return _finish(db, "statement", None, checks, None)
