"""Broker trading end to end against SimBroker: pool money model, FX, safeguards, audits."""

from datetime import datetime, timedelta

import pandas as pd
import pytest

import app.main  # noqa: F401  (registers all tables)
from app.analysis import portfolio
from app.analysis.strategy import MarketState
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import StockAnalysis
from app.trading import audit as au
from app.trading import execution as ex
from app.trading.broker import SimBroker, ibkr_fee
from app.trading.models import AuditReport, TradingEvent, TradingLedger, TradingOrder, TradingRun

TICKERS = [f"T{i:02d}" for i in range(12)]
ROUND = datetime(2026, 11, 8, 2)  # a Sunday batch
EURUSD = 1.10


def monday_open(week: int = 0) -> datetime:
    return datetime(2026, 11, 9, 15, 30) + timedelta(weeks=week)  # 10:30 New York


@pytest.fixture
def env(monkeypatch):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    for k, v in dict(trading_mode="paper", trading_broker="sim", trading_approval="manual",
                     trading_currency="EUR", trading_weekly_new_money=400.0, trading_max_buys_per_week=2,
                     trading_max_order_value=2000.0, trading_max_weekly_buys=4000.0, trading_auto_fx=True,
                     trading_fx_min_conversion=1000.0, trading_fractional=True, notify_url="").items():
        monkeypatch.setattr(settings, k, v)
    market = {"state": MarketState(500.0, 480.0)}
    monkeypatch.setattr(portfolio, "_spy_market_state", lambda: market["state"])
    monkeypatch.setattr(ex, "universe", lambda: set(TICKERS))
    rate = lambda c: {"EUR": EURUSD, "USD": 1.0}.get(c.upper())  # noqa: E731
    monkeypatch.setattr(ex, "fx_rate", rate)
    monkeypatch.setattr(au, "fx_rate", rate)
    monkeypatch.setattr(au, "spy_history", lambda start: pd.Series([500.0], index=[pd.Timestamp("2026-11-01")]))
    prices = {t: 100.0 for t in TICKERS} | {"SPY": 500.0}
    broker = SimBroker(lambda t: prices.get(t), fx_fn=rate)
    db = SessionLocal()
    ex.record_deposit(db, 5000, broker)
    yield db, broker, prices, market
    db.close()


def add_round(db, when, fv_ratio=1.3, overrides=None):
    for i, t in enumerate(TICKERS):
        r = (overrides or {}).get(t, fv_ratio)
        db.add(StockAnalysis(ticker=t, name=t, current_price=100.0, fair_value=None if r is None else 100.0 * r,
                             valuation="Undervalued", overall_score=60 + i, conviction=7, analyzed_at=when))
    db.commit()


def week(db, broker, w=0, overrides=None, approve=True, fv_ratio=1.3):
    when = ROUND + timedelta(weeks=w)
    add_round(db, when, fv_ratio=fv_ratio, overrides=overrides)
    run = ex.propose(db, broker, today=when.date())
    if run and run.status == "awaiting_approval" and approve:
        ex.decide_run(db, run.id, approve=True)
    ex.submit(db, broker, now_utc=monday_open(w))
    ex.sync(db, broker, end_of_day=True)
    return run


def failed(report):
    return {c["name"] for c in report.checks if not c["ok"]}


# ── money model ──────────────────────────────────────────────────────────────

def test_off_mode_does_nothing(env, monkeypatch):
    db, broker, *_ = env
    monkeypatch.setattr(settings, "trading_mode", "off")
    add_round(db, ROUND)
    assert ex.propose(db, broker, today=ROUND.date()) is None


def test_first_week_draws_at_most_400_eur_with_2_buys(env):
    db, broker, *_ = env
    add_round(db, ROUND)
    run = ex.propose(db, broker, today=ROUND.date())
    assert run.status == "awaiting_approval"
    assert run.allowance == 400 and run.budget_usd == pytest.approx(400 * EURUSD)
    orders = db.query(TradingOrder).filter_by(run_id=run.id).all()
    assert [o.side for o in orders] == ["buy", "buy"]
    assert sum(o.est_value for o in orders) == pytest.approx(440)

    assert ex.submit(db, broker, now_utc=monday_open()) == 0  # not approved yet
    ex.decide_run(db, run.id, approve=True)
    assert ex.submit(db, broker, now_utc=monday_open()) == 2
    ex.sync(db, broker)

    # EUR was converted automatically, in a chunk of at least EUR 1,000.
    assert broker.cash("EUR") == pytest.approx(4000)
    assert db.query(TradingLedger).filter_by(kind="fx_fee").count() == 1
    drawn = ex.drawn_for_run(db, run.id)
    assert 0 < drawn <= 400
    assert ex.pool_balance(db) == pytest.approx(5000 - drawn - 2.0 / EURUSD)
    assert ex.reconcile(db, broker)


def test_unused_allowance_does_not_accumulate(env):
    db, broker, *_ = env
    week(db, broker, 0, fv_ratio=None)  # outage week: nothing traded
    run = week(db, broker, 1)
    assert run.allowance == 400  # not 800
    assert ex.drawn_for_run(db, run.id) <= 400


def test_sale_proceeds_are_rebought_on_top_of_allowance(env):
    db, broker, prices, _ = env
    for w in range(4):
        week(db, broker, w)
    target = sorted(broker.positions())[0]
    trim_run = week(db, broker, 4, overrides={target: 0.9})  # trim half
    week(db, broker, 5, overrides={target: 0.9})  # exit rest
    assert target not in broker.positions()
    sells = db.query(TradingOrder).filter_by(ticker=target, side="sell", status="filled").all()
    assert [s.reason.split(":")[0] for s in sells] == ["Trim 50%", "Exit"]

    # The same week, the proceeds are re-bought on top of the EUR 400 of new money...
    proceeds = sum(s.filled_qty * s.avg_fill_price - s.commission for s in sells if s.run_id == trim_run.id)
    buys = db.query(TradingOrder).filter_by(run_id=trim_run.id, side="buy", status="filled").all()
    assert len(buys) <= 2
    assert sum(b.filled_qty * b.avg_fill_price for b in buys) > 440 + proceeds * 0.9
    spent_proceeds = -sum(r.amount for r in db.query(TradingLedger).filter_by(
        run_id=trim_run.id, bucket="proceeds", kind="buy"))
    assert spent_proceeds == pytest.approx(proceeds, abs=0.01)  # proceeds are spent first
    assert ex.drawn_for_run(db, trim_run.id) <= 400  # ...and new money still stays within the cap
    assert ex.proceeds_balance(db) >= -0.01
    assert ex.reconcile(db, broker)


def test_risk_off_holds_proceeds_as_cash(env):
    db, broker, prices, market = env
    for w in range(3):
        week(db, broker, w)
    market["state"] = MarketState(400.0, 480.0)  # SPY below its 200-day average
    run = week(db, broker, 3)
    assert run.risk_off == 1
    assert db.query(TradingOrder).filter_by(run_id=run.id, side="buy").count() == 0
    assert ex.drawn_for_run(db, run.id) == 0
    assert ex.pool_balance(db) > 5000 - 3 * 400 - 10


def test_pool_running_low_is_announced(env):
    db, broker, *_ = env
    ex.record_deposit(db, -4400, broker)  # leave EUR 600
    week(db, broker, 0)
    assert db.query(TradingEvent).filter_by(kind="pool_low").count() == 1
    run = week(db, broker, 1)
    assert run.allowance == pytest.approx(ex.pool_balance(db) + ex.drawn_for_run(db, run.id), abs=0.01)
    assert run.allowance < 400


def test_extra_cash_in_account_is_not_touched(env):
    db, broker, *_ = env
    broker.deposit(10_000, "EUR")  # money added at the broker but not recorded as a deposit
    week(db, broker, 0)
    invested = sum(p.shares * 100 for p in broker.positions().values())
    assert invested <= 440


# ── safeguards ───────────────────────────────────────────────────────────────

def test_kill_switch_blocks_everything(env):
    db, broker, *_ = env
    add_round(db, ROUND)
    ex.set_kill_switch(db, True, "test")
    assert ex.propose(db, broker, today=ROUND.date()) is None
    ex.set_kill_switch(db, False, "test")
    run = ex.propose(db, broker, today=ROUND.date())
    ex.decide_run(db, run.id, approve=True)
    ex.set_kill_switch(db, True, "test")
    assert ex.submit(db, broker, now_utc=monday_open()) == 0


def test_market_hours_and_expiry(env):
    db, broker, *_ = env
    add_round(db, ROUND)
    run = ex.propose(db, broker, today=ROUND.date())
    ex.decide_run(db, run.id, approve=True)
    assert ex.submit(db, broker, now_utc=datetime(2026, 11, 9, 12, 0)) == 0  # before the open
    assert ex.submit(db, broker, now_utc=datetime(2026, 11, 9, 20, 45)) == 0  # 15 min before close
    assert ex.submit(db, broker, now_utc=datetime(2026, 11, 16, 15, 30)) == 0  # a week later: expired
    assert db.get(TradingRun, run.id).status == "expired"


def test_market_calendar():
    assert ex.market_open(datetime(2026, 11, 9, 15, 30))
    assert not ex.market_open(datetime(2026, 11, 26, 16, 0))  # Thanksgiving
    assert not ex.market_open(datetime(2026, 11, 14, 16, 0))  # Saturday
    assert ex.market_open(datetime(2026, 7, 6, 14, 0))  # summer time


def test_price_moved_blocks_order(env):
    db, broker, prices, _ = env
    add_round(db, ROUND)
    run = ex.propose(db, broker, today=ROUND.date())
    ex.decide_run(db, run.id, approve=True)
    target = db.query(TradingOrder).filter_by(run_id=run.id).first().ticker
    prices[target] = 104.0
    assert ex.submit(db, broker, now_utc=monday_open()) == 1
    o = db.query(TradingOrder).filter_by(run_id=run.id, ticker=target).one()
    assert o.status == "blocked" and "price moved" in o.block_reason


def test_stale_analyses_are_not_traded(env):
    db, broker, *_ = env
    add_round(db, ROUND)
    assert ex.propose(db, broker, today=ROUND.date() + timedelta(days=4)) is None


def test_live_mode_refuses_simulated_broker(env, monkeypatch):
    db, broker, *_ = env
    monkeypatch.setattr(settings, "trading_mode", "live")
    add_round(db, ROUND)
    assert ex.propose(db, broker, today=ROUND.date()) is None
    assert ex.kill_switch(db)[0] is True


def test_paper_mode_refuses_live_ibkr_account(env):
    db, broker, *_ = env
    broker.name, broker._account = "ibkr", "U1234567"
    add_round(db, ROUND)
    assert ex.propose(db, broker, today=ROUND.date()) is None
    assert "non-paper" in ex.kill_switch(db)[1]


def test_whole_shares_mode(env, monkeypatch):
    db, broker, *_ = env
    monkeypatch.setattr(settings, "trading_fractional", False)
    week(db, broker, 0)
    assert all(float(p.shares).is_integer() for p in broker.positions().values())


def test_ibkr_fee_model():
    assert ibkr_fee(1, 100) == 1.0 and ibkr_fee(0.5, 100) == 0.5 and ibkr_fee(1000, 50) == 5.0


# ── audits ───────────────────────────────────────────────────────────────────

def test_clean_weeks_pass_every_audit_check(env):
    db, broker, *_ = env
    for w in range(3):
        run = week(db, broker, w)
        report = au.weekly_audit(db, broker, run.id)
        assert report.passed and not failed(report), report.checks
    perf = report.performance
    assert perf["deposited"] == 5000 and 0 < perf["new_money_invested"] <= 1200
    assert perf["nav"] == pytest.approx(5000 - perf["fx_fees"] - perf["fees_usd"] / EURUSD, abs=0.05)
    assert ex.kill_switch(db)[0] is False


def test_audit_detects_edited_order(env):
    db, broker, *_ = env
    run = week(db, broker, 0)
    o = db.query(TradingOrder).filter_by(run_id=run.id).first()
    o.avg_fill_price = o.avg_fill_price * 0.9  # someone "improves" a fill in the database
    db.commit()
    report = au.weekly_audit(db, broker, run.id)
    assert "order_history" in failed(report) and not report.passed
    assert ex.kill_switch(db)[0] is True


def test_audit_detects_edited_or_deleted_log(env):
    db, broker, *_ = env
    run = week(db, broker, 0)
    e = db.query(TradingEvent).filter_by(kind="proposed").first()
    e.message = e.message.replace("2 orders", "0 orders")
    db.commit()
    assert "event_chain" in failed(au.weekly_audit(db, broker, run.id))

    db.query(TradingEvent).filter_by(id=e.id).delete()
    db.commit()
    assert "event_chain" in failed(au.weekly_audit(db, broker, run.id))


def test_audit_detects_changed_analyses_after_decision(env):
    db, broker, *_ = env
    run = week(db, broker, 0)
    chosen = db.query(TradingOrder).filter_by(run_id=run.id).first().ticker
    a = db.query(StockAnalysis).filter_by(ticker=chosen).first()
    a.fair_value = 50.0  # the analysis behind a trade is rewritten afterwards
    db.commit()
    assert "decision_replay" in failed(au.weekly_audit(db, broker, run.id))


def test_audit_detects_draw_over_the_weekly_cap(env):
    db, broker, *_ = env
    run = week(db, broker, 0)
    db.add(TradingLedger(mode="paper", bucket="pool", currency="EUR", kind="draw", amount=-500.0,
                         fx_rate=EURUSD, run_id=run.id, note="injected"))
    db.commit()
    assert {"new_money_cap", "ledger_integrity"} & failed(au.weekly_audit(db, broker, run.id))


def test_manual_trade_in_account_is_caught(env):
    db, broker, *_ = env
    run = week(db, broker, 0)
    broker.place_limit("T05", "buy", 1.0, 101.0, ref="manual")
    assert ex.reconcile(db, broker) is False  # position mismatch trips the switch first
    assert ex.kill_switch(db)[0] is True
    report = au.weekly_audit(db, broker, run.id)
    assert {"positions", "foreign_trades"} <= failed(report)


def _statement(orders, extra=""):
    rows = "".join(
        f'<Trade assetCategory="STK" symbol="{o.ticker}" buySell="{"BUY" if o.side == "buy" else "SELL"}" '
        f'quantity="{o.filled_qty if o.side == "buy" else -o.filled_qty}" tradePrice="{o.avg_fill_price}" '
        f'ibCommission="{-o.commission}" orderReference="nestleap-{o.id}" tradeDate="20261109"/>'
        for o in orders)
    days = [o.submitted_at.strftime("%Y%m%d") for o in orders] or ["20261109"]
    return f'<FlexQueryResponse><FlexStatements><FlexStatement fromDate="{min(days)}" toDate="{max(days)}">' \
           f"<Trades>{rows}{extra}</Trades></FlexStatement></FlexStatements></FlexQueryResponse>"


def test_statement_audit(env):
    db, broker, *_ = env
    week(db, broker, 0)
    filled = db.query(TradingOrder).filter(TradingOrder.filled_qty > 0).all()
    assert au.statement_audit(db, _statement(filled)).passed

    foreign = '<Trade assetCategory="STK" symbol="AAPL" buySell="BUY" quantity="1" tradePrice="300" ' \
              'ibCommission="-1" orderReference="" tradeDate="20261109"/>'
    assert "statement_foreign" in failed(au.statement_audit(db, _statement(filled, foreign)))
    missing_one = _statement(filled[:1]).replace(
        f'fromDate="{filled[0].submitted_at:%Y%m%d}"', f'fromDate="{min(o.submitted_at for o in filled):%Y%m%d}"')
    assert "statement_fills" in failed(au.statement_audit(db, missing_one))


def test_admin_endpoints(env):
    from fastapi.testclient import TestClient

    db, broker, *_ = env
    add_round(db, ROUND)
    run = ex.propose(db, broker, today=ROUND.date())
    with TestClient(app.main.app) as client:
        h = {"X-Admin-Key": settings.admin_key}
        assert client.get("/api/admin/trading").status_code == 403
        st = client.get("/api/admin/trading", headers=h).json()
        assert st["run"]["status"] == "awaiting_approval" and st["pool"] == 5000 and st["currency"] == "EUR"
        assert client.post(f"/api/admin/trading/runs/{run.id}/approve", headers=h).json()["status"] == "approved"
        assert client.post(f"/api/admin/trading/runs/{run.id}/approve", headers=h).status_code == 409
        assert client.post("/api/admin/trading/kill?on=true&reason=test", headers=h).json()["kill_switch"] is True


def test_tax_report_from_trading_records(env, tmp_path):
    from app.trading import tax_de

    db, broker, prices, _ = env
    for w in range(4):
        week(db, broker, w)
    target = sorted(broker.positions())[0]
    prices[target] = 102.9  # sold at a gain (within the 3% price-move check)
    week(db, broker, 4, overrides={target: 0.9})
    rep = tax_de.build_report(db, 2026, "paper", rates=lambda d: EURUSD)
    s = rep.summary()
    sale = [x for x in rep.stock_sales if x.ticker == target][0]
    assert sale.gain_eur > 0 and s["anlage_kap"]["of_which_share_gains_eur"] > 0
    assert len([c for c in rep.currency_disposals if c.reason.startswith("buy")]) >= 8
    assert not any("did not come from a recorded conversion" in w for w in rep.warnings)
    out = tax_de.write_report(rep, str(tmp_path / "tax"))
    assert (out / "aktienverkaeufe.csv").read_text().startswith("date;ticker;shares")
    assert "Anlage KAP" in (out / "uebersicht.txt").read_text()


def test_archive_separates_books(env):
    db, broker, *_ = env
    week(db, broker, 0)
    ex.adopt_baseline(db, broker)
    counts = ex.archive_book(db, "paper-sim")
    assert counts["runs"] == 1 and counts["ledger_rows"] > 0
    assert ex.pool_balance(db) == 0 and ex.expected_positions(db) == {}
    assert db.query(TradingRun).filter_by(mode="paper").count() == 0
    assert ex.get_setting(db, "position_baseline_paper-sim") is not None
    assert au.check_event_chain(db)["ok"]
    with pytest.raises(ValueError):
        ex.archive_book(db, "paper-sim")  # label already used
    with pytest.raises(ValueError):
        ex.archive_book(db, "live")


def test_extra_cash_is_noted_not_flagged(env):
    db, broker, *_ = env
    broker.deposit(1_000_000, "EUR")  # e.g. a paper account's play money
    run = week(db, broker, 0)
    assert ex.reconcile(db, broker)
    assert db.query(TradingEvent).filter_by(kind="reconcile_cash", level="warning").count() == 0
    cash = [c for c in au.weekly_audit(db, broker, run.id).checks if c["name"] == "cash"][0]
    assert cash["ok"] and "not managed by NestLeap" in cash["detail"]
