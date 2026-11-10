"""
Weekly broker execution. Each step is idempotent and safe to re-run from cron.

    propose    after the Sunday batch: strategy decides, safeguards check, orders recorded
    approve    (manual mode) you approve or reject the week's orders
    submit     on a US trading day during market hours: sells first, then buys, as limit orders
    sync       poll fills; at end of day cancel anything unfilled
    reconcile  daily: broker positions, executions and cash must match the records

Money model (see config.py): deposits go into a POOL (e.g. EUR). Each week the strategy
may draw at most `trading_weekly_new_money` from it; unused allowance stays in the pool.
Sale proceeds go to a separate PROCEEDS bucket (USD) that the strategy re-buys with or
holds. Buys spend proceeds first, then draw from the pool. Other cash in the account is
never used. The broker's account is the source of truth for holdings.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from datetime import date, datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..analysis.strategy import V2_LIVE, Position, coverage, decide, update_states
from ..config import settings
from ..models import StockAnalysis
from .broker import Broker, fx_rate
from .models import TradingEvent, TradingLedger, TradingOrder, TradingRun, TradingSetting
from .notify import notify

logger = logging.getLogger(__name__)

MAX_ANALYSIS_AGE_DAYS = 3  # propose only from a fresh batch
MAX_SUBMIT_AGE_DAYS = 6  # approved orders expire if not submitted within this
OPEN_STATUSES = ("submitted", "partially_filled")
TERMINAL_STATUSES = ("filled", "cancelled", "failed")
FEE_RESERVE_USD = 2.0  # per buy order, kept back for the commission


def strategy_config():
    return V2_LIVE.with_(top_n=settings.trading_max_buys_per_week)


# ── events (hash-chained) ────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def event_hash(prev: str | None, level: str, kind: str, message: str, details, created_at: datetime) -> str:
    payload = json.dumps([prev, level, kind, message, details, created_at.isoformat()], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def chain_head(db: Session) -> str | None:
    last = db.query(TradingEvent).order_by(TradingEvent.id.desc()).first()
    return last.hash if last else None


def event(db: Session, kind: str, message: str, level: str = "info", details: dict | None = None,
          push: bool = False):
    created = _now()
    prev = chain_head(db)
    db.add(TradingEvent(level=level, kind=kind, message=message, details=details, created_at=created,
                        prev_hash=prev, hash=event_hash(prev, level, kind, message, details, created)))
    db.commit()
    if push or level == "error":
        notify(kind.replace("_", " "), message, level)
    else:
        getattr(logger, "warning" if level == "warning" else "info")(f"[{kind}] {message}")


def order_event(db: Session, o: TradingOrder, note: str = ""):
    """Every order state change is chained, so the audit can rebuild order history."""
    event(db, "order", f"#{o.id} {o.side} {o.ticker}: {o.status}{(' — ' + note) if note else ''}", details={
        "order_id": o.id, "run_id": o.run_id, "ticker": o.ticker, "side": o.side, "status": o.status,
        "quantity": o.quantity, "est_value": round(o.est_value, 4), "limit_price": o.limit_price,
        "filled_qty": o.filled_qty, "avg_fill_price": o.avg_fill_price, "commission": o.commission,
        "broker_order_id": o.broker_order_id, "block_reason": o.block_reason,
    })


# ── settings ─────────────────────────────────────────────────────────────────

def get_setting(db: Session, key: str, default: str | None = None) -> str | None:
    row = db.get(TradingSetting, key)
    return row.value if row else default


def set_setting(db: Session, key: str, value: str):
    row = db.get(TradingSetting, key)
    if row:
        row.value = value
    else:
        db.add(TradingSetting(key=key, value=value))
    db.commit()


def kill_switch(db: Session) -> tuple[bool, str | None]:
    raw = get_setting(db, "kill_switch")
    if not raw:
        return False, None
    data = json.loads(raw)
    return bool(data.get("on")), data.get("reason")


def set_kill_switch(db: Session, on: bool, reason: str):
    set_setting(db, "kill_switch", json.dumps({"on": on, "reason": reason, "at": _now().isoformat()}))
    event(db, "kill_switch", f"Kill switch {'ON' if on else 'off'}: {reason}",
          level="error" if on else "info", push=True)


def mode() -> str:
    return settings.trading_mode


def universe() -> set[str]:
    from ..analysis.batch import _get_full_ticker_list

    return set(_get_full_ticker_list())


# ── ledger ───────────────────────────────────────────────────────────────────

def _bucket_sum(db: Session, bucket: str, **filters) -> float:
    q = db.query(func.coalesce(func.sum(TradingLedger.amount), 0.0)).filter_by(mode=mode(), bucket=bucket, **filters)
    return float(q.scalar())


def pool_balance(db: Session) -> float:
    return _bucket_sum(db, "pool")


def proceeds_balance(db: Session) -> float:
    return _bucket_sum(db, "proceeds")


def drawn_for_run(db: Session, run_id: int) -> float:
    """New money (pool currency) drawn by this run's buys."""
    return -_bucket_sum(db, "pool", kind="draw", run_id=run_id)


def record_deposit(db: Session, amount: float, broker: Broker | None = None, note: str = "") -> float:
    cur = settings.trading_currency
    kind = "deposit" if amount > 0 else "withdrawal"
    db.add(TradingLedger(mode=mode(), bucket="pool", currency=cur, kind=kind, amount=amount, note=note))
    db.commit()
    if broker is not None and broker.name == "sim":  # money doesn't arrive by itself in a simulation
        broker.deposit(amount, cur)
    event(db, kind, f"{kind.title()} of {cur} {abs(amount):,.2f} recorded; pool now {cur} {pool_balance(db):,.2f}",
          push=True)
    return pool_balance(db)


def _fx_or_fail(db: Session, step: str) -> float | None:
    rate = fx_rate(settings.trading_currency)
    if not rate:
        event(db, f"{step}_skipped", f"No {settings.trading_currency}/USD rate available", level="warning", push=True)
    return rate


# ── guards & calendar ────────────────────────────────────────────────────────

def _guard(db: Session, broker: Broker, step: str) -> bool:
    if mode() not in ("paper", "live"):
        logger.info(f"{step}: trading mode is {mode()!r}, nothing to do")
        return False
    on, reason = kill_switch(db)
    if on:
        event(db, f"{step}_halted", f"Kill switch is on ({reason}); {step} skipped", level="warning")
        return False
    acct = broker.account_id()
    if broker.name == "ibkr":  # IBKR paper accounts start with "DU". Never let the modes cross.
        is_paper = acct.upper().startswith("DU")
        if mode() == "paper" and not is_paper:
            set_kill_switch(db, True, f"TRADING_MODE=paper but gateway is logged into non-paper account {acct}")
            return False
        if mode() == "live" and is_paper:
            set_kill_switch(db, True, f"TRADING_MODE=live but gateway is logged into paper account {acct}")
            return False
    elif mode() == "live":
        set_kill_switch(db, True, f"TRADING_MODE=live requires TRADING_BROKER=ibkr (got {broker.name})")
        return False
    return True


def market_open(now_utc: datetime | None = None, minutes_before_close: int = 30) -> bool:
    import exchange_calendars as xc
    import pandas as pd

    cal = xc.get_calendar("XNYS")
    ts = pd.Timestamp(now_utc or datetime.now(timezone.utc))
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    if not cal.is_open_on_minute(ts):
        return False
    return ts <= cal.session_close(cal.minute_to_session(ts)) - pd.Timedelta(minutes=minutes_before_close)


# ── propose ──────────────────────────────────────────────────────────────────

def strategy_states(db: Session, max_analysis_id: int | None = None):
    """Signal state as of an analysis id (the audit replays with the id stored on the run)."""
    from ..analysis.portfolio import _signal_rounds

    rounds = _signal_rounds(db, max_analysis_id=max_analysis_id)
    cfg = strategy_config()
    states: dict = {}
    for idx, (_, sigs) in enumerate(rounds):
        update_states(states, sigs, idx, cfg)
    return rounds, states


def propose(db: Session, broker: Broker, today: date | None = None) -> TradingRun | None:
    if not _guard(db, broker, "propose"):
        return None
    from ..analysis.portfolio import _spy_market_state

    today = today or _now().date()
    max_id = db.query(func.max(StockAnalysis.id)).scalar()
    rounds, states = strategy_states(db, max_id)
    if not rounds:
        return None
    round_date, signals = rounds[-1]
    if (today - round_date).days > MAX_ANALYSIS_AGE_DAYS:
        event(db, "propose_skipped", f"Latest analyses are from {round_date}, older than "
              f"{MAX_ANALYSIS_AGE_DAYS} days; not trading on stale data", level="warning", push=True)
        return None
    existing = db.query(TradingRun).filter_by(mode=mode(), round_date=round_date).first()
    if existing:
        return existing  # idempotent: one decision per batch

    fx = _fx_or_fail(db, "propose")
    if fx is None:
        return None
    cfg = strategy_config()
    cur = settings.trading_currency
    cov = coverage(signals)
    market = _spy_market_state()

    pool, proceeds = pool_balance(db), proceeds_balance(db)
    allowance = max(0.0, min(settings.trading_weekly_new_money, pool))
    budget = max(0.0, proceeds) + allowance * fx
    balances = broker.cash_balances()
    broker_cash_usd = sum(v * (1.0 if c == "USD" else (fx if c == cur else 0.0)) for c, v in balances.items())
    cash = max(0.0, min(budget, broker_cash_usd))

    allowed = universe()
    held = broker.positions()
    holdings = {t: Position(p.shares, p.shares * p.avg_cost) for t, p in held.items() if t in allowed}
    holdings_value = sum(p.shares * (states[t].last_price or 0) for t, p in holdings.items() if t in states)
    idx = len(rounds) - 1
    orders = decide(cfg, holdings, cash, states, idx, cov, market)

    inputs = {
        "max_analysis_id": max_id, "round_index": idx, "coverage": cov, "cash_usd": cash,
        "holdings": {t: [p.shares, p.cost_basis] for t, p in holdings.items()},
        "market": {"spy_price": market.spy_price, "spy_sma200": market.spy_sma200},
        "config": {k: (v if v not in (float("inf"),) else "inf") for k, v in asdict(cfg).items()},
        "fx_rate": fx, "pool": pool, "proceeds": proceeds, "allowance": allowance,
    }
    run = TradingRun(mode=mode(), broker=broker.name, round_date=round_date, status="no_trades",
                     coverage=cov, risk_off=int(market.risk_off), fx_rate=fx, pool_before=pool,
                     allowance=allowance, proceeds_before=proceeds, budget_usd=budget,
                     holdings_value=holdings_value, inputs=inputs)
    if cov < cfg.min_coverage:
        run.status, run.note = "skipped", f"only {cov:.0%} of analyses usable (min {cfg.min_coverage:.0%})"
    db.add(run)
    db.flush()

    latest_ids = dict(db.query(StockAnalysis.ticker, func.max(StockAnalysis.id))
                      .filter(StockAnalysis.id <= max_id).group_by(StockAnalysis.ticker).all())
    auto = settings.trading_approval == "auto"
    buys_total = 0.0
    created = []
    for o in orders:
        value, qty, reason, block = o.total, o.shares, o.reason, None
        if o.ticker not in allowed:
            block = "not in the analysed universe"
        elif o.action == "buy":
            room = min(settings.trading_max_order_value, settings.trading_max_weekly_buys - buys_total)
            if value > room:
                value, reason = room, f"{reason} [clipped to ${room:.0f} by safety cap]"
                qty = value / o.price
            if value < cfg.min_trade_value:
                block = "weekly buy cap reached"
            else:
                buys_total += value
        elif o.action == "sell":
            have = held.get(o.ticker)
            if not have or qty > have.shares + 1e-6:
                block = "sell exceeds broker position"
        row = TradingOrder(
            run_id=run.id, ticker=o.ticker, side=o.action, quantity=qty, strategy_quantity=o.shares,
            est_price=o.price, est_value=value, reason=reason[:250], analysis_id=latest_ids.get(o.ticker),
            status="blocked" if block else ("approved" if auto else "proposed"),
            block_reason=block, approved_at=_now() if auto and not block else None,
        )
        db.add(row)
        created.append(row)
    db.flush()
    if run.status != "skipped" and any(r.status in ("proposed", "approved") for r in created):
        run.status = "approved" if auto else "awaiting_approval"
    db.commit()
    for r in created:
        order_event(db, r, "proposed by strategy")

    lines = [f"{r.side.upper()} {r.ticker} ${r.est_value:,.0f} — {r.status}"
             + (f" ({r.block_reason})" if r.block_reason else "") for r in created]
    head = (f"[{mode()}] week of {round_date}: {len(lines)} orders. Budget ${budget:,.0f} = proceeds "
            f"${proceeds:,.0f} + new money {cur} {allowance:,.0f}{', RISK-OFF (holding cash)' if market.risk_off else ''}. "
            f"Status: {run.status}.")
    action = (f"\nApprove in the admin page or: trading.sh approve {run.id}"
              if run.status == "awaiting_approval" else "")
    event(db, "proposed", head + ("\n" + "\n".join(lines) if lines else "") + action,
          details={"run_id": run.id}, push=True)

    weeks_left = (pool - allowance) / settings.trading_weekly_new_money if settings.trading_weekly_new_money else 99
    if weeks_left < 2:
        event(db, "pool_low", f"Pool has {cur} {pool - allowance:,.0f} left after this week (about "
              f"{max(weeks_left, 0):.1f} weeks of new money). Deposit more and record it with "
              f"`trading.sh deposit <amount>`; until then only sale proceeds are reinvested.",
              level="warning", push=True)
    return run


# ── approval ─────────────────────────────────────────────────────────────────

def decide_run(db: Session, run_id: int, approve: bool, who: str = "admin") -> TradingRun:
    run = db.get(TradingRun, run_id)
    if run is None or run.mode != mode():
        raise ValueError(f"No {mode()} run {run_id}")
    if run.status != "awaiting_approval":
        raise ValueError(f"Run {run_id} is {run.status}, not awaiting approval")
    now = _now()
    changed = []
    for o in db.query(TradingOrder).filter_by(run_id=run_id, status="proposed"):
        o.status = "approved" if approve else "rejected"
        o.approved_at = now
        changed.append(o)
    run.status = "approved" if approve else "rejected"
    run.decided_at = now
    db.commit()
    for o in changed:
        order_event(db, o, f"by {who}")
    event(db, "approved" if approve else "rejected", f"Run {run_id} {run.status} by {who}", push=True)
    return run


# ── submit ───────────────────────────────────────────────────────────────────

def submit(db: Session, broker: Broker, now_utc: datetime | None = None) -> int:
    if not _guard(db, broker, "submit"):
        return 0
    now = now_utc or _now()
    run = (db.query(TradingRun).filter_by(mode=mode(), status="approved")
           .order_by(TradingRun.id.desc()).first())
    if run is None:
        return 0
    if (now.date() - run.round_date).days > MAX_SUBMIT_AGE_DAYS:
        for o in db.query(TradingOrder).filter_by(run_id=run.id, status="approved"):
            o.status = "expired"
            order_event(db, o)
        run.status = "expired"
        db.commit()
        event(db, "expired", f"Run {run.id} expired before it could be submitted", level="warning", push=True)
        return 0
    if not market_open(now):
        logger.info("submit: US market not open (or closing within 30 min); will retry")
        return 0
    fx = _fx_or_fail(db, "submit")
    if fx is None:
        return 0

    tol, off = settings.trading_price_tolerance, settings.trading_limit_offset
    cfg = strategy_config()
    orders = db.query(TradingOrder).filter_by(run_id=run.id, status="approved").all()
    held = broker.positions()
    placed = 0

    def check_price(o) -> float | None:
        px = broker.last_price(o.ticker)
        if not px:
            o.status, o.block_reason = "blocked", "no current price"
            return None
        move = px / o.est_price - 1
        if abs(move) > tol:
            o.status, o.block_reason = "blocked", f"price moved {move:+.1%} since proposal (limit ±{tol:.0%})"
            return None
        return px

    def place(o, qty, limit):
        try:
            o.broker_order_id = broker.place_limit(o.ticker, o.side, qty, limit, ref=f"nestleap-{o.id}")
            o.status, o.limit_price, o.submitted_quantity, o.submitted_at = "submitted", limit, qty, _now()
            return True
        except Exception as e:
            o.status, o.error = "failed", str(e)[:1000]
            event(db, "order_failed", f"{o.side} {o.ticker}: {e}", level="error")
            return False

    sells = [x for x in orders if x.side == "sell"]
    for o in sells:
        px = check_price(o)
        if px is not None:
            have = held.get(o.ticker)
            qty = min(o.quantity, have.shares if have else 0.0)
            if qty <= 1e-9:
                o.status, o.block_reason = "blocked", "no shares held at submit time"
            else:
                placed += place(o, qty, round(px * (1 - off), 2))
        db.commit()
        order_event(db, o)
    if sells:
        _sync_orders(db, broker, [o for o in sells if o.status in OPEN_STATUSES])  # book proceeds that filled

    # Buy budget: proceeds + whatever is left of this week's new-money allowance.
    budget = max(0.0, proceeds_balance(db)) + max(0.0, (run.allowance or 0.0) - drawn_for_run(db, run.id)) * fx
    buys = sorted([x for x in orders if x.side == "buy"], key=lambda x: -x.est_value)
    planned = min(budget, sum(b.est_value for b in buys)) + FEE_RESERVE_USD * len(buys)
    usd = broker.cash("USD")
    cur = settings.trading_currency
    if buys and usd < planned and settings.trading_auto_fx and cur != "USD":
        have_ccy = broker.cash(cur)
        need = (planned - usd) / fx * 1.01
        amount = min(have_ccy, max(need, settings.trading_fx_min_conversion))
        if amount > 1:
            try:
                conv = broker.convert(cur, "USD", amount)
                db.add(TradingLedger(mode=mode(), bucket="pool", currency=cur, kind="fx_fee",
                                     amount=-conv.fee_usd / fx, fx_rate=conv.rate, run_id=run.id,
                                     note=f"converted {cur} {conv.sold_amount:,.2f} -> USD {conv.bought_amount:,.2f}"))
                db.commit()
                event(db, "fx", f"Converted {cur} {conv.sold_amount:,.2f} to USD {conv.bought_amount:,.2f} "
                      f"at {conv.rate:.4f} (fee USD {conv.fee_usd:.2f})", details={**asdict(conv), "mode": mode()})
                usd = broker.cash("USD")
            except Exception as e:
                event(db, "fx_failed", f"Currency conversion failed: {e}", level="error")

    available = min(usd, budget)
    for o in buys:
        px = check_price(o)
        if px is not None:
            limit = round(px * (1 + off), 2)
            value = min(o.est_value, available - FEE_RESERVE_USD)
            qty = value / limit if settings.trading_fractional else float(int(value // limit))
            if qty * limit < cfg.min_trade_value or qty <= 0:
                o.status, o.block_reason = "blocked", f"not enough budget (${available:,.0f} available)"
            elif place(o, round(qty, 4), limit):
                placed += 1
                available -= round(qty, 4) * limit + FEE_RESERVE_USD
        db.commit()
        order_event(db, o)

    run.status = "submitted"
    db.commit()
    blocked = [o for o in orders if o.status == "blocked"]
    event(db, "submitted", f"Run {run.id}: {placed} orders sent to {broker.name}"
          + (f", {len(blocked)} blocked: " + "; ".join(f"{o.ticker} ({o.block_reason})" for o in blocked)
             if blocked else ""), level="warning" if blocked else "info", push=True)
    return placed


# ── sync ─────────────────────────────────────────────────────────────────────

def _book_fill(db: Session, o: TradingOrder):
    value = (o.filled_qty or 0.0) * (o.avg_fill_price or 0.0)
    fee = o.commission or 0.0
    if value <= 0 and not fee:
        return
    desc = f"{o.ticker} {o.filled_qty:.4f} @ {o.avg_fill_price or 0:.2f}, fee {fee:.2f}"
    if o.side == "sell":
        db.add(TradingLedger(mode=mode(), bucket="proceeds", currency="USD", kind="sell", amount=value - fee,
                             run_id=o.run_id, order_id=o.id, note=desc))
        return
    cost = value + fee
    from_proceeds = min(max(proceeds_balance(db), 0.0), cost)
    if from_proceeds > 0:
        db.add(TradingLedger(mode=mode(), bucket="proceeds", currency="USD", kind="buy", amount=-from_proceeds,
                             run_id=o.run_id, order_id=o.id, note=desc))
    rest = cost - from_proceeds
    if rest > 1e-9:
        fx = fx_rate(settings.trading_currency) or db.get(TradingRun, o.run_id).fx_rate
        db.add(TradingLedger(mode=mode(), bucket="pool", currency=settings.trading_currency, kind="draw",
                             amount=-rest / fx, fx_rate=fx, run_id=o.run_id, order_id=o.id,
                             note=f"{desc}; USD {rest:,.2f} of new money"))


def _sync_orders(db: Session, broker: Broker, orders, end_of_day: bool = False) -> dict:
    counts: dict[str, int] = {}
    for o in orders:
        try:
            if end_of_day:
                if broker.order_update(o.broker_order_id).status in OPEN_STATUSES:
                    broker.cancel(o.broker_order_id)
            upd = broker.order_update(o.broker_order_id)
        except Exception as e:
            event(db, "sync_failed", f"{o.ticker} order {o.broker_order_id}: {e}", level="error")
            continue
        if end_of_day and upd.status in OPEN_STATUSES:
            upd.status = "cancelled"  # DAY orders expire at the close anyway
        changed = (upd.status, upd.filled_qty) != (o.status, o.filled_qty)
        o.status, o.filled_qty, o.avg_fill_price, o.commission = upd.status, upd.filled_qty, upd.avg_fill_price, upd.commission
        o.updated_at = _now()
        if o.status in TERMINAL_STATUSES:
            _book_fill(db, o)
        db.commit()
        if changed:
            order_event(db, o)
        counts[o.status] = counts.get(o.status, 0) + 1
    return counts


def sync(db: Session, broker: Broker, end_of_day: bool = False) -> dict:
    if mode() not in ("paper", "live"):
        return {}
    open_orders = (db.query(TradingOrder).join(TradingRun, TradingRun.id == TradingOrder.run_id)
                   .filter(TradingRun.mode == mode(), TradingOrder.status.in_(OPEN_STATUSES)).all())
    counts = _sync_orders(db, broker, open_orders, end_of_day)
    cur = settings.trading_currency
    for run in db.query(TradingRun).filter_by(mode=mode(), status="submitted"):
        if not db.query(TradingOrder).filter(TradingOrder.run_id == run.id,
                                             TradingOrder.status.in_(OPEN_STATUSES)).count():
            run.status = "done"
            db.commit()
            filled = db.query(TradingOrder).filter_by(run_id=run.id, status="filled").count()
            unfilled = db.query(TradingOrder).filter(TradingOrder.run_id == run.id,
                                                     TradingOrder.status.in_(("cancelled", "failed"))).count()
            event(db, "week_done", f"Run {run.id}: {filled} filled, {unfilled} unfilled/failed. New money drawn "
                  f"{cur} {drawn_for_run(db, run.id):,.2f}; pool {cur} {pool_balance(db):,.2f}; proceeds "
                  f"${proceeds_balance(db):,.2f}", level="warning" if unfilled else "info", push=True)
    return counts


# ── reconcile ────────────────────────────────────────────────────────────────

def expected_positions(db: Session) -> dict[str, float]:
    baseline = json.loads(get_setting(db, f"position_baseline_{mode()}", "{}"))
    out = {t: float(q) for t, q in baseline.items()}
    rows = (db.query(TradingOrder).join(TradingRun, TradingRun.id == TradingOrder.run_id)
            .filter(TradingRun.mode == mode(), TradingOrder.filled_qty > 0).all())
    for o in rows:
        out[o.ticker] = out.get(o.ticker, 0.0) + (o.filled_qty if o.side == "buy" else -o.filled_qty)
    return {t: q for t, q in out.items() if abs(q) > 1e-6}


def adopt_baseline(db: Session, broker: Broker):
    """Record the account's current universe positions as the starting point (run once,
    e.g. if the account already held some of these stocks before NestLeap traded)."""
    allowed = universe()
    current = {t: p.shares for t, p in broker.positions().items() if t in allowed}
    implied = expected_positions(db)
    baseline = json.loads(get_setting(db, f"position_baseline_{mode()}", "{}"))
    for t in set(current) | set(implied):
        baseline[t] = baseline.get(t, 0.0) + current.get(t, 0.0) - implied.get(t, 0.0)
    set_setting(db, f"position_baseline_{mode()}", json.dumps({t: q for t, q in baseline.items() if abs(q) > 1e-9}))
    allowed_refs = json.loads(get_setting(db, f"known_foreign_executions_{mode()}", "[]"))
    allowed_refs += [e.broker_order_id for e in broker.executions() if not e.ref.startswith("nestleap-")]
    set_setting(db, f"known_foreign_executions_{mode()}", json.dumps(sorted(set(allowed_refs))))
    event(db, "baseline", f"Adopted broker positions as baseline: {current}", push=True)


def foreign_executions(db: Session, broker: Broker) -> list:
    """Broker executions NestLeap did not place (manual trades, other software)."""
    known = {o.broker_order_id for o in db.query(TradingOrder).filter(TradingOrder.broker_order_id.isnot(None))}
    accepted = set(json.loads(get_setting(db, f"known_foreign_executions_{mode()}", "[]")))
    return [e for e in broker.executions()
            if e.broker_order_id not in known and e.broker_order_id not in accepted]


def cash_check(db: Session, broker: Broker, fx: float) -> tuple[float, float]:
    """(broker cash in USD terms, ledger cash in USD terms) for the strategy's currencies."""
    cur = settings.trading_currency
    bal = broker.cash_balances()
    physical = bal.get("USD", 0.0) + (bal.get(cur, 0.0) * fx if cur != "USD" else 0.0)
    ledger = proceeds_balance(db) + pool_balance(db) * fx
    return physical, ledger


def reconcile(db: Session, broker: Broker, tolerance_shares: float = 1e-3) -> bool:
    if mode() not in ("paper", "live"):
        return True
    allowed = universe()
    actual = {t: p.shares for t, p in broker.positions().items() if t in allowed}
    expected = expected_positions(db)
    diffs = {t: (expected.get(t, 0.0), actual.get(t, 0.0)) for t in set(actual) | set(expected)
             if abs(expected.get(t, 0.0) - actual.get(t, 0.0)) > tolerance_shares}
    if diffs:
        detail = "; ".join(f"{t}: expected {e:.4f}, broker {a:.4f}" for t, (e, a) in sorted(diffs.items()))
        set_kill_switch(db, True, f"Reconciliation mismatch — {detail}")
        return False
    foreign = foreign_executions(db, broker)
    if foreign:
        detail = "; ".join(f"{e.side} {e.ticker} {e.shares:g} ({e.ref or 'no ref'})" for e in foreign)
        set_kill_switch(db, True, f"Executions not placed by NestLeap: {detail}")
        return False
    fx = fx_rate(settings.trading_currency)
    if fx:
        physical, ledger = cash_check(db, broker, fx)
        if physical < ledger * 0.95 - 5:
            set_kill_switch(db, True, f"Account cash ${physical:,.2f} is far below the recorded ${ledger:,.2f}")
            return False
        if physical < ledger * 0.98 - 5:
            event(db, "reconcile_cash", f"Account cash ${physical:,.2f} below recorded ${ledger:,.2f} "
                  f"(currency moves or unrecorded withdrawal?)", level="warning", push=True)
        elif physical > ledger * 1.02 + 5:
            # Extra cash is never used (buys are limited to pool + proceeds), so it's only noted:
            # it may be an unrecorded deposit, or simply money kept in the account.
            event(db, "reconcile_cash", f"Account holds ${physical - ledger:,.2f} more cash than NestLeap manages "
                  f"(not used; record new deposits with `trading.sh deposit <amount>`)")
    event(db, "reconciled", f"{len(actual)} positions match, no foreign executions; pool "
          f"{settings.trading_currency} {pool_balance(db):,.2f}, proceeds ${proceeds_balance(db):,.2f}")
    return True


# ── archive (switching brokers within a mode) ────────────────────────────────

def archive_book(db: Session, label: str) -> dict:
    """Move the current mode's runs, ledger, audit reports and position settings under
    `label` (e.g. "paper-sim"), so a new broker starts from a clean book. Nothing is
    deleted; the move itself is recorded in the hash-chained log."""
    from .models import AuditReport

    if not label or label in ("paper", "live", "off") or label == mode():
        raise ValueError("Choose a new label such as 'paper-sim-2026-11'")
    if db.query(TradingRun).filter_by(mode=label).count() or db.query(TradingLedger).filter_by(mode=label).count():
        raise ValueError(f"Label {label!r} is already in use")
    counts = {}
    for name, model in (("runs", TradingRun), ("ledger_rows", TradingLedger), ("audit_reports", AuditReport)):
        counts[name] = db.query(model).filter_by(mode=mode()).update({"mode": label}, synchronize_session=False)
    for key in ("position_baseline", "known_foreign_executions"):
        row = db.get(TradingSetting, f"{key}_{mode()}")
        if row:
            db.add(TradingSetting(key=f"{key}_{label}", value=row.value))
            db.delete(row)
    db.commit()
    event(db, "archived", f"Archived the {mode()!r} book as {label!r}: {counts}", details={"label": label, **counts},
          push=True)
    return counts


# ── status ───────────────────────────────────────────────────────────────────

def status(db: Session) -> dict:
    from .models import AuditReport

    on, reason = kill_switch(db)
    run = db.query(TradingRun).filter_by(mode=mode()).order_by(TradingRun.id.desc()).first()
    orders = db.query(TradingOrder).filter_by(run_id=run.id).all() if run else []
    events = db.query(TradingEvent).order_by(TradingEvent.id.desc()).limit(25).all()
    audit = db.query(AuditReport).filter_by(mode=mode()).order_by(AuditReport.id.desc()).first()
    return {
        "mode": mode(), "broker": settings.trading_broker, "approval": settings.trading_approval,
        "kill_switch": on, "kill_reason": reason, "currency": settings.trading_currency,
        "pool": round(pool_balance(db), 2), "proceeds_usd": round(proceeds_balance(db), 2),
        "weekly_new_money": settings.trading_weekly_new_money,
        "max_buys_per_week": settings.trading_max_buys_per_week,
        "run": None if not run else {
            "id": run.id, "round_date": str(run.round_date), "status": run.status, "coverage": run.coverage,
            "risk_off": bool(run.risk_off), "budget_usd": run.budget_usd, "allowance": run.allowance,
            "drawn": round(drawn_for_run(db, run.id), 2), "note": run.note,
            "orders": [{
                "id": o.id, "ticker": o.ticker, "side": o.side, "est_value": round(o.est_value, 2),
                "quantity": o.quantity, "est_price": o.est_price, "status": o.status, "reason": o.reason,
                "block_reason": o.block_reason, "filled_qty": o.filled_qty, "avg_fill_price": o.avg_fill_price,
                "commission": o.commission, "limit_price": o.limit_price,
            } for o in orders],
        },
        "audit": None if not audit else {
            "id": audit.id, "kind": audit.kind, "at": audit.created_at.isoformat() if audit.created_at else None,
            "passed": audit.passed, "critical_failures": audit.critical_failures, "warnings": audit.warnings,
            "checks": audit.checks, "performance": audit.performance, "chain_head": audit.chain_head,
        },
        "events": [{"at": e.created_at.isoformat() if e.created_at else None, "level": e.level,
                    "kind": e.kind, "message": e.message} for e in events],
    }
