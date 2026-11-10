"""End-to-end: real app + SQLite, network replaced by fakes."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.analysis import analyzer, portfolio
from app.analysis.strategy import MarketState
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import PortfolioSnapshot, PortfolioTrade, StockAnalysis

TICKERS = [f"T{i:02d}" for i in range(20)]


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(portfolio, "_spy_market_state", lambda: MarketState(500.0, 480.0))
    monkeypatch.setattr(portfolio, "_get_live_prices_bulk", lambda tickers: {})
    yield


def add_round(db, when: datetime, fv_ratio: dict[str, float | None], price=100.0):
    """One analysis per ticker; fv_ratio = fair value / price (None = Gemini failed)."""
    for i, t in enumerate(TICKERS):
        ratio = fv_ratio.get(t, 1.0)
        db.add(StockAnalysis(
            ticker=t, name=t, sector="Technology", current_price=price,
            fair_value=None if ratio is None else price * ratio,
            valuation=None if ratio is None else ("Undervalued" if ratio > 1.11 else "Fair Value"),
            overall_score=None if ratio is None else 60 + i, conviction=None if ratio is None else 7,
            analyzed_at=when,
        ))
    db.commit()


def portfolio_value(db) -> tuple[float, dict[str, float]]:
    snap = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.id.desc()).first()
    holdings = {t: p["shares"] * 100.0 for t, p in portfolio._get_holdings(db).items()}
    return snap.total_value, holdings


def test_api_endpoints_respond_with_new_schema():
    db = SessionLocal()
    add_round(db, datetime.utcnow() - timedelta(days=1), {t: 1.3 for t in TICKERS})  # "recent" = within 7 days
    db.close()
    with TestClient(app) as client:  # runs lifespan: create_all + migrate_columns
        for path in ["/api/health", "/api/dashboard", "/api/stock/T00", "/api/stocks/analyzed",
                     "/api/portfolio", "/api/portfolio/history", "/api/stats", "/api/batch/status"]:
            r = client.get(path)
            assert r.status_code == 200, (path, r.text)
        assert "changes_since_last" in client.get("/api/stock/T00").json()
        assert client.post("/api/admin/portfolio/rebalance").status_code in (401, 403, 422)


def test_v2_rebalance_end_to_end_respects_caps_and_cash():
    db = SessionLocal()
    start = datetime(2026, 9, 6, 2)
    for w in range(8):
        add_round(db, start + timedelta(weeks=w), {t: 1.3 for t in TICKERS})
        portfolio.rebalance_portfolio(db)

    total, holdings = portfolio_value(db)
    snap = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.id.desc()).first()
    assert snap.total_invested == 8000
    assert snap.cash >= -1e-6
    assert total == pytest.approx(8000, rel=1e-6)  # flat prices: value == contributions
    assert max(holdings.values()) <= 0.12 * total + 1e-6
    db.close()


def test_sell_zone_exits_within_two_weeks():
    db = SessionLocal()
    start = datetime(2026, 9, 6, 2)
    for w in range(4):
        add_round(db, start + timedelta(weeks=w), {t: 1.3 for t in TICKERS})
        portfolio.rebalance_portfolio(db)
    held = set(portfolio._get_holdings(db))
    target = sorted(held)[0]

    # Target's fair value collapses to 10% below the price: half goes in the first
    # round, the rest in the second. Nothing may sit in the sell zone longer than 2 weeks.
    sold_by_round = []
    for w in range(4, 6):
        add_round(db, start + timedelta(weeks=w), {**{t: 1.3 for t in TICKERS}, target: 0.9})
        portfolio.rebalance_portfolio(db)
        sold_by_round.append([t.reason for t in db.query(PortfolioTrade).filter_by(ticker=target, action="sell")])

    assert len(sold_by_round[0]) == 1 and sold_by_round[0][0].startswith("Trim")
    assert len(sold_by_round[1]) == 2 and sold_by_round[1][1].startswith("Exit")
    assert target not in portfolio._get_holdings(db)
    db.close()


def test_gemini_outage_round_skips_trading_but_records_contribution():
    db = SessionLocal()
    add_round(db, datetime(2026, 10, 25, 2), {t: 1.3 for t in TICKERS})
    portfolio.rebalance_portfolio(db)
    trades_before = db.query(PortfolioTrade).count()

    add_round(db, datetime(2026, 11, 1, 2), {t: None for t in TICKERS})  # every call failed
    portfolio.rebalance_portfolio(db)

    assert db.query(PortfolioTrade).count() == trades_before
    snap = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.id.desc()).first()
    assert snap.total_invested == 2000 and snap.cash == pytest.approx(1000, abs=1e-6)
    db.close()


def test_missing_spy_data_aborts_without_writing(monkeypatch):
    db = SessionLocal()
    add_round(db, datetime(2026, 11, 1, 2), {t: 1.3 for t in TICKERS})

    def boom():
        raise RuntimeError("No SPY price history available")

    monkeypatch.setattr(portfolio, "_spy_market_state", boom)
    with pytest.raises(RuntimeError):
        portfolio.rebalance_portfolio(db)
    db.rollback()
    assert db.query(PortfolioSnapshot).count() == 0
    assert db.query(PortfolioTrade).count() == 0
    db.close()


def test_risk_off_holds_cash():
    db = SessionLocal()
    for w in range(3):
        add_round(db, datetime(2026, 9, 6, 2) + timedelta(weeks=w), {t: 1.3 for t in TICKERS})
        portfolio.rebalance_portfolio(db)
    portfolio._spy_market_state = lambda: MarketState(400.0, 480.0)  # restored by fixture
    add_round(db, datetime(2026, 9, 27, 2), {t: 1.3 for t in TICKERS})
    portfolio.rebalance_portfolio(db)
    snap = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.id.desc()).first()
    assert snap.cash == pytest.approx(1000, abs=1e-6)  # $4k portfolio, 30% reserve > $1k cash
    db.close()


@pytest.mark.parametrize("prev", [
    None,
    SimpleNamespace(analyzed_at=datetime(2026, 10, 25), current_price=None, fair_value=120.0,
                    valuation=None, conviction=None, overall_score=None, summary=None,
                    risks=None, catalysts=None, pe_ratio=None, forward_pe=None),
])
def test_previous_section_tolerates_missing_fields(prev):
    data = SimpleNamespace(current_price=100.0, name="X", last_earnings_date=date(2026, 10, 30),
                           pe_ratio=20.0, forward_pe=18.0,
                           **{m[0]: None for m in analyzer._TRACKED_METRICS})
    text = analyzer._previous_section(prev, data)
    assert "PREVIOUS ASSESSMENT" in text
    if prev is not None:
        assert "EARNINGS SINCE THEN" in text


def test_fresh_look_week_cadence():
    weeks = [analyzer._is_fresh_look_week(datetime(2026, 1, 5) + timedelta(weeks=w)) for w in range(8)]
    assert sum(weeks) == 2
