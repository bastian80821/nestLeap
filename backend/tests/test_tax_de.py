"""German tax worksheet: hand-calculated examples."""

from datetime import date, datetime

import pytest

from app.trading.tax_de import (
    CashIncome, Conversion, EcbRates, Trade, _within_one_year, compute, parse_flex_cash, summary_text,
)


def rates(table):
    def fn(d: date) -> float:
        return table[d.isoformat()]
    return fn


def test_currency_move_is_part_of_the_share_gain():
    r = rates({"2026-03-02": 1.10, "2026-06-01": 1.20})
    rep = compute(
        2026,
        trades=[Trade(datetime(2026, 3, 2, 15, 30), "AAA", "buy", 10, 100.0, 1.0),
                Trade(datetime(2026, 6, 1, 15, 30), "AAA", "sell", 10, 110.0, 1.0)],
        conversions=[Conversion(datetime(2026, 3, 2, 15, 0), 1000.0, 1098.0)],
        cash=[], rate=r,
    )
    (sale,) = rep.stock_sales
    # Cost: (10 * 100 + 1) / 1.10 = 910.00 EUR. Proceeds: (10 * 110 - 1) / 1.20 = 915.83 EUR.
    # +9.8% in dollars, but only +0.6% in euros because the dollar fell.
    assert sale.cost_eur == pytest.approx(910.0)
    assert sale.proceeds_eur == pytest.approx(915.8333, abs=1e-3)
    assert sale.gain_eur == pytest.approx(5.8333, abs=1e-3)

    # Spending USD 1,001 of the USD 1,098 bought for EUR 1,000: cost 911.66, worth 910.00 that day.
    (fx,) = [c for c in rep.currency_disposals if c.reason.startswith("buy")]
    assert fx.cost_eur == pytest.approx(1000 * 1001 / 1098, abs=1e-3)
    assert fx.gain_eur == pytest.approx(910.0 - 1000 * 1001 / 1098, abs=1e-3)
    assert fx.taxable

    s = rep.summary()
    assert s["anlage_kap"]["of_which_share_gains_eur"] == pytest.approx(5.83)
    assert s["anlage_kap"]["share_losses_eur"] == 0
    assert s["anlage_so_private_sales"]["currency_net_eur"] == pytest.approx(-1.66, abs=0.01)
    assert s["anlage_so_private_sales"]["below_freigrenze"]


def test_fifo_across_lots():
    r = rates({"2026-01-02": 1.0, "2026-01-05": 1.0, "2026-02-02": 1.0, "2026-03-02": 1.0})
    rep = compute(
        2026,
        trades=[Trade(datetime(2026, 1, 5), "AAA", "buy", 5, 100.0, 0.0),
                Trade(datetime(2026, 2, 2), "AAA", "buy", 5, 120.0, 0.0),
                Trade(datetime(2026, 3, 2), "AAA", "sell", 7, 130.0, 0.0)],
        conversions=[Conversion(datetime(2026, 1, 2), 2000.0, 2000.0)], cash=[], rate=r,
    )
    (sale,) = rep.stock_sales
    assert sale.cost_eur == pytest.approx(5 * 100 + 2 * 120)  # oldest lot first
    assert sale.gain_eur == pytest.approx(7 * 130 - 740)
    assert rep.open_positions["AAA"]["shares"] == pytest.approx(3)
    assert rep.open_positions["AAA"]["cost_eur"] == pytest.approx(360)


def test_losses_are_reported_separately_and_carried_forward():
    r = rates({"2026-01-02": 1.0, "2026-04-01": 1.0})
    rep = compute(
        2026,
        trades=[Trade(datetime(2026, 1, 2, 16), "AAA", "buy", 10, 100.0, 0.0),
                Trade(datetime(2026, 4, 1), "AAA", "sell", 10, 80.0, 0.0)],
        conversions=[Conversion(datetime(2026, 1, 2, 15), 1000.0, 1000.0)], cash=[], rate=r,
    )
    s = rep.summary()
    assert s["anlage_kap"]["share_losses_eur"] == pytest.approx(200)
    assert s["anlage_kap"]["share_loss_carryforward_eur"] == pytest.approx(200)
    assert s["illustrative_tax_eur"] == 0


def test_currency_held_over_a_year_is_exempt():
    r = rates({"2025-01-02": 1.0, "2025-06-02": 0.8, "2026-02-02": 1.25})
    trades = [Trade(datetime(2025, 6, 2), "AAA", "buy", 1, 500.0, 0.0),
              Trade(datetime(2026, 2, 2), "BBB", "buy", 1, 500.0, 0.0)]
    conv = [Conversion(datetime(2025, 1, 2), 1000.0, 1000.0)]
    y25 = compute(2025, trades, conv, [], r).summary()["anlage_so_private_sales"]
    assert y25["currency_gains_within_one_year_eur"] == pytest.approx(500 / 0.8 - 500)  # +125, taxable
    y26 = compute(2026, trades, conv, [], r).summary()["anlage_so_private_sales"]
    assert y26["currency_net_eur"] == 0
    assert y26["exempt_over_one_year_eur"] == pytest.approx(500 / 1.25 - 500)  # -100, not taxable


def test_one_year_boundary():
    assert _within_one_year(date(2025, 3, 1), date(2026, 3, 1))
    assert not _within_one_year(date(2025, 3, 1), date(2026, 3, 2))
    assert _within_one_year(date(2024, 2, 29), date(2025, 2, 28))


def test_dividends_and_withholding_credit_cap():
    xml = """<FlexQueryResponse><FlexStatements><FlexStatement><CashTransactions>
      <CashTransaction currency="USD" type="Dividends" amount="10" symbol="AAA" dateTime="20260515;120000" levelOfDetail="DETAIL"/>
      <CashTransaction currency="USD" type="Withholding Tax" amount="-1.5" symbol="AAA" dateTime="20260515;120000" levelOfDetail="DETAIL"/>
      <CashTransaction currency="USD" type="Dividends" amount="20" symbol="BBB" dateTime="2026-08-14" levelOfDetail="DETAIL"/>
      <CashTransaction currency="USD" type="Withholding Tax" amount="-6" symbol="BBB" dateTime="2026-08-14" levelOfDetail="DETAIL"/>
      <CashTransaction currency="USD" type="Deposits/Withdrawals" amount="500" dateTime="20260101" levelOfDetail="DETAIL"/>
      <CashTransaction currency="EUR" type="Dividends" amount="99" symbol="SAP" dateTime="20260601" levelOfDetail="DETAIL"/>
    </CashTransactions></FlexStatement></FlexStatements></FlexQueryResponse>"""
    cash = parse_flex_cash(xml)
    assert [(c.ticker, c.kind, c.usd) for c in cash] == [
        ("AAA", "dividend", 10.0), ("AAA", "withholding", -1.5), ("BBB", "dividend", 20.0), ("BBB", "withholding", -6.0)]
    rep = compute(2026, [], [], cash, rates({"2026-05-15": 1.25, "2026-08-14": 1.0}), dividends_included=True)
    k = rep.summary()["anlage_kap"]
    assert k["dividends_gross_eur"] == pytest.approx(10 / 1.25 + 20)  # 8 + 20
    assert k["foreign_withholding_paid_eur"] == pytest.approx(1.2 + 6)
    # 15% cap: BBB had 30% withheld (no W-8BEN); only 15% of 28 EUR gross is creditable.
    assert k["creditable_foreign_tax_eur"] == pytest.approx(0.15 * 28)
    assert not any("Dividends" in w for w in rep.warnings)


def test_illustrative_tax_uses_allowance():
    r = rates({"2026-01-02": 1.0, "2026-09-01": 1.0})
    rep = compute(
        2026,
        trades=[Trade(datetime(2026, 1, 2, 16), "AAA", "buy", 10, 100.0, 0.0),
                Trade(datetime(2026, 9, 1), "AAA", "sell", 10, 400.0, 0.0)],
        conversions=[Conversion(datetime(2026, 1, 2, 15), 1000.0, 1000.0)], cash=[], rate=r,
    )
    # Gain 3,000 EUR, minus 1,000 allowance, times 26.375%.
    assert rep.summary()["illustrative_tax_eur"] == pytest.approx(2000 * 0.26375)


def test_other_years_only_carry_lots():
    r = rates({"2026-01-02": 1.0, "2027-01-04": 1.0})
    trades = [Trade(datetime(2026, 1, 2, 16), "AAA", "buy", 1, 100.0, 0.0),
              Trade(datetime(2027, 1, 4), "AAA", "sell", 1, 150.0, 0.0)]
    conv = [Conversion(datetime(2026, 1, 2, 15), 100.0, 100.0)]
    assert compute(2026, trades, conv, [], r).stock_sales == []
    (sale,) = compute(2027, trades, conv, [], r).stock_sales
    assert sale.gain_eur == pytest.approx(50)


def test_unknown_origin_is_flagged():
    r = rates({"2026-03-02": 1.0})
    rep = compute(2026, [Trade(datetime(2026, 3, 2), "AAA", "sell", 5, 10.0, 0.0)], [], [], r)
    assert any("no recorded purchase" in w for w in rep.warnings)
    rep = compute(2026, [Trade(datetime(2026, 3, 2), "AAA", "buy", 5, 10.0, 0.0)], [], [], r)
    assert any("did not come from a recorded conversion" in w for w in rep.warnings)


def test_ecb_rates_fall_back_to_previous_fixing():
    ecb = EcbRates()
    ecb.rates = {"2026-11-06": 1.12}
    assert ecb(date(2026, 11, 8)) == 1.12  # Sunday -> Friday's fixing
    with pytest.raises(KeyError):
        ecb(date(2026, 10, 1))


def test_summary_text_is_german_and_complete():
    rep = compute(2026, [], [], [], rates({}))
    text = summary_text(rep)
    assert "Anlage KAP" in text and "Anlage SO" in text and "keine Steuerberatung" in text
