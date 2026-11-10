"""
German tax report for the broker account (Anlage KAP and Anlage SO figures).

Not tax advice — a worksheet for your return or your Steuerberater. Method:

Shares (§ 20 EStG, Abgeltungsteuer)
  * FIFO per stock (§ 20 Abs. 4 Satz 7 EStG).
  * Each buy and sell is converted to EUR at the ECB reference rate of its trade date
    (§ 20 Abs. 4 Satz 1 Hs. 2): currency moves are part of the share gain.
  * Buy commissions add to the cost, sell commissions reduce the proceeds.
  * Losses from shares only offset gains from shares (Aktienverlusttopf).

Dividends
  * Gross dividends and US withholding tax from the IBKR statement (NestLeap itself
    never sees dividend payments), converted at the payment date's ECB rate.
  * Creditable foreign tax is capped at 15% of the gross dividend (DBA USA).

USD cash (§ 23 EStG, private Veräußerungsgeschäfte, personal tax rate)
  * Dollars are acquired by EUR->USD conversions, share sales and dividends; they are
    disposed of when spent on share purchases. FIFO lots.
  * A gain or loss on dollars held for no more than one year is taxable; the year's total
    of all private-sale gains is tax-free below the EUR 1,000 Freigrenze.
  * USD balances are treated as non-interest-bearing (IBKR pays no interest on small
    balances); interest-bearing balances may be treated differently.

Exchange rates: ECB euro reference rate EXR D.USD.EUR (USD per EUR), previous business
day when the date has no fixing.
"""

from __future__ import annotations

import csv
import json
import os
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable

ABGELTUNGSTEUER = 0.25 * 1.055  # 25% + 5.5% Solidaritätszuschlag (without church tax)
SPARERPAUSCHBETRAG = 1000.0
FREIGRENZE_23 = 1000.0
DBA_USA_CREDIT = 0.15

RateFn = Callable[[date], float]  # USD per 1 EUR


# ── inputs ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Trade:
    when: datetime
    ticker: str
    side: str  # buy | sell
    shares: float
    price_usd: float
    commission_usd: float
    order_id: int | None = None


@dataclass(frozen=True)
class Conversion:
    when: datetime
    eur_sold: float
    usd_bought: float  # after fees


@dataclass(frozen=True)
class CashIncome:
    when: datetime
    ticker: str
    kind: str  # dividend | withholding
    usd: float  # dividends positive, withholding negative (refunds positive)


# ── outputs ──────────────────────────────────────────────────────────────────

@dataclass
class StockSale:
    date: str
    ticker: str
    shares: float
    proceeds_usd: float
    rate: float
    proceeds_eur: float
    cost_eur: float
    gain_eur: float
    lots: str
    unmatched_shares: float = 0.0


@dataclass
class CurrencyDisposal:
    date: str
    usd: float
    rate: float
    proceeds_eur: float
    cost_eur: float
    gain_eur: float
    acquired: str
    held_days: int
    taxable: bool
    reason: str


@dataclass
class DividendRow:
    date: str
    ticker: str
    kind: str
    usd: float
    rate: float
    eur: float


@dataclass
class TaxReport:
    year: int
    mode: str
    stock_sales: list[StockSale] = field(default_factory=list)
    currency_disposals: list[CurrencyDisposal] = field(default_factory=list)
    dividends: list[DividendRow] = field(default_factory=list)
    open_positions: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    dividends_included: bool = False

    def summary(self) -> dict:
        r2 = lambda x: round(x, 2)  # noqa: E731
        gains = sum(s.gain_eur for s in self.stock_sales if s.gain_eur > 0)
        losses = -sum(s.gain_eur for s in self.stock_sales if s.gain_eur < 0)
        div_gross = sum(d.eur for d in self.dividends if d.kind == "dividend")
        wht = -sum(d.eur for d in self.dividends if d.kind == "withholding")
        creditable = max(0.0, min(wht, DBA_USA_CREDIT * div_gross))
        fx_in = [c for c in self.currency_disposals if c.taxable]
        fx_gain = sum(c.gain_eur for c in fx_in if c.gain_eur > 0)
        fx_loss = -sum(c.gain_eur for c in fx_in if c.gain_eur < 0)
        fx_net = fx_gain - fx_loss
        exempt = sum(c.gain_eur for c in self.currency_disposals if not c.taxable)

        stock_net = gains - losses
        kap_base = max(stock_net, 0.0) + div_gross
        illustrative = max(0.0, kap_base - SPARERPAUSCHBETRAG) * ABGELTUNGSTEUER - creditable
        return {
            "year": self.year, "mode": self.mode,
            "anlage_kap": {
                "capital_income_total_eur": r2(gains + div_gross),
                "of_which_share_gains_eur": r2(gains),
                "share_losses_eur": r2(losses),
                "dividends_gross_eur": r2(div_gross),
                "foreign_withholding_paid_eur": r2(wht),
                "creditable_foreign_tax_eur": r2(creditable),
                "share_loss_carryforward_eur": r2(max(-stock_net, 0.0)),
            },
            "anlage_so_private_sales": {
                "currency_gains_within_one_year_eur": r2(fx_gain),
                "currency_losses_within_one_year_eur": r2(fx_loss),
                "currency_net_eur": r2(fx_net),
                "exempt_over_one_year_eur": r2(exempt),
                "below_freigrenze": fx_net < FREIGRENZE_23,
            },
            "illustrative_tax_eur": r2(illustrative),
            "illustrative_tax_note": (
                "Abgeltungsteuer + Soli on share gains (net, if positive) and dividends, minus the full "
                "EUR 1,000 Sparerpauschbetrag and creditable US tax. Ignores church tax, your other "
                "investment income and § 23 currency results (personal rate)."),
            "counts": {"share_sales": len(self.stock_sales), "currency_disposals": len(self.currency_disposals),
                       "dividend_rows": len(self.dividends)},
            "open_positions_eur_cost": {t: r2(v["cost_eur"]) for t, v in self.open_positions.items()},
            "dividends_included": self.dividends_included,
            "warnings": self.warnings,
        }


# ── engine ───────────────────────────────────────────────────────────────────

_PRIORITY = {"sell": 0, "dividend": 0, "withholding": 0, "conversion": 1, "buy": 2}


def compute(year: int, trades: Iterable[Trade], conversions: Iterable[Conversion],
            cash: Iterable[CashIncome], rate: RateFn, mode: str = "live",
            dividends_included: bool = False) -> TaxReport:
    """Replay all activity up to the end of `year` and report disposals within it."""
    events = ([(t.when, _PRIORITY[t.side], "trade", t) for t in trades]
              + [(c.when, _PRIORITY["conversion"], "conversion", c) for c in conversions]
              + [(c.when, _PRIORITY[c.kind], "cash", c) for c in cash])
    events.sort(key=lambda e: (e[0], e[1]))
    end = datetime(year, 12, 31, 23, 59, 59)

    rep = TaxReport(year=year, mode=mode, dividends_included=dividends_included)
    stock_lots: dict[str, deque] = defaultdict(deque)  # ticker -> [shares, eur_cost, date]
    usd_lots: deque = deque()  # [usd, eur_cost, date]
    unmatched_usd = 0.0

    def add_usd(usd: float, eur_cost: float, when: datetime):
        if usd > 1e-9:
            usd_lots.append([usd, eur_cost, when])

    def spend_usd(usd: float, when: datetime, reason: str, in_year: bool):
        nonlocal unmatched_usd
        fx = rate(when.date())
        remaining = usd
        while remaining > 1e-9 and usd_lots:
            lot = usd_lots[0]
            take = min(lot[0], remaining)
            cost = lot[1] * take / lot[0]
            lot[0] -= take
            lot[1] -= cost
            if lot[0] <= 1e-9:
                usd_lots.popleft()
            remaining -= take
            held = (when.date() - lot[2].date()).days
            proceeds = take / fx
            if in_year:
                rep.currency_disposals.append(CurrencyDisposal(
                    when.date().isoformat(), round(take, 4), fx, round(proceeds, 4), round(cost, 4),
                    round(proceeds - cost, 4), lot[2].date().isoformat(), held,
                    _within_one_year(lot[2].date(), when.date()), reason))
        if remaining > 1e-6:
            unmatched_usd += remaining

    for when, _, kind, ev in events:
        if when > end:
            break
        in_year = when.year == year
        if kind == "conversion":
            add_usd(ev.usd_bought, ev.eur_sold, when)
        elif kind == "cash":
            fx = rate(when.date())
            if in_year:
                rep.dividends.append(DividendRow(when.date().isoformat(), ev.ticker, ev.kind, ev.usd, fx,
                                                 round(ev.usd / fx, 4)))
            if ev.usd > 0:
                add_usd(ev.usd, ev.usd / fx, when)
            else:
                spend_usd(-ev.usd, when, f"{ev.kind} {ev.ticker}", in_year)
        elif ev.side == "buy":
            fx = rate(when.date())
            usd = ev.shares * ev.price_usd + ev.commission_usd
            stock_lots[ev.ticker].append([ev.shares, usd / fx, when])
            spend_usd(usd, when, f"buy {ev.ticker}", in_year)
        else:
            fx = rate(when.date())
            usd = ev.shares * ev.price_usd - ev.commission_usd
            proceeds = usd / fx
            remaining, cost, used = ev.shares, 0.0, []
            lots = stock_lots[ev.ticker]
            while remaining > 1e-9 and lots:
                lot = lots[0]
                take = min(lot[0], remaining)
                c = lot[1] * take / lot[0]
                lot[0] -= take
                lot[1] -= c
                cost += c
                remaining -= take
                used.append(f"{take:g}@{lot[2].date().isoformat()}")
                if lot[0] <= 1e-9:
                    lots.popleft()
            if in_year:
                rep.stock_sales.append(StockSale(
                    when.date().isoformat(), ev.ticker, ev.shares, round(usd, 4), fx, round(proceeds, 4),
                    round(cost, 4), round(proceeds - cost, 4), "; ".join(used), round(max(remaining, 0.0), 6)))
                if remaining > 1e-6:
                    rep.warnings.append(f"{ev.ticker} sale on {when.date()}: {remaining:g} shares with no recorded "
                                        f"purchase (bought outside NestLeap?) — their cost is missing")
            add_usd(usd, proceeds, when)

    rep.open_positions = {t: {"shares": round(sum(l[0] for l in lots), 6), "cost_eur": sum(l[1] for l in lots)}
                          for t, lots in stock_lots.items() if sum(l[0] for l in lots) > 1e-6}
    if unmatched_usd > 1:
        rep.warnings.append(f"USD {unmatched_usd:,.2f} was spent that did not come from a recorded conversion, "
                            f"sale or dividend (dollars already in the account?) — no currency result computed")
    if not dividends_included:
        rep.warnings.append("Dividends and withholding tax not included: pass the year's IBKR Flex statement "
                            "(with the Cash Transactions section)")
    if mode != "live":
        rep.warnings.append(f"This report covers the {mode!r} account, not real money")
    return rep


def _within_one_year(acquired: date, sold: date) -> bool:
    """§ 23: taxable if no more than one year lies between acquisition and sale."""
    try:
        anniversary = acquired.replace(year=acquired.year + 1)
    except ValueError:  # 29 February
        anniversary = acquired.replace(year=acquired.year + 1, day=28)
    return sold <= anniversary


# ── data sources ─────────────────────────────────────────────────────────────

class EcbRates:
    """ECB reference rates (USD per EUR), cached as JSON; falls back to the previous fixing."""

    URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A"

    def __init__(self, cache_path: str | None = None):
        self.path = Path(cache_path) if cache_path else None
        self.rates: dict[str, float] = {}
        if self.path and self.path.exists():
            self.rates = json.loads(self.path.read_text())

    def load(self, start: date, end: date):
        import httpx

        r = httpx.get(self.URL, params={"startPeriod": start.isoformat(), "endPeriod": end.isoformat(),
                                        "format": "csvdata"}, timeout=60)
        r.raise_for_status()
        for row in csv.DictReader(r.text.splitlines()):
            if row.get("OBS_VALUE"):
                self.rates[row["TIME_PERIOD"]] = float(row["OBS_VALUE"])
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.rates, sort_keys=True))

    def __call__(self, d: date) -> float:
        for back in range(10):
            key = (d - timedelta(days=back)).isoformat()
            if key in self.rates:
                return self.rates[key]
        raise KeyError(f"No ECB USD rate on or before {d} (load a range covering it)")


def _parse_ib_date(value: str) -> datetime:
    digits = "".join(ch for ch in value.split(";")[0] if ch.isdigit())
    return datetime.strptime(digits[:8], "%Y%m%d").replace(hour=12)


def parse_flex_cash(xml_text: str) -> list[CashIncome]:
    """Dividends and withholding tax (USD) from an IBKR Flex statement's Cash Transactions."""
    out = []
    for el in ET.fromstring(xml_text).iter("CashTransaction"):
        a = el.attrib
        if a.get("currency") != "USD" or a.get("levelOfDetail", "DETAIL") not in ("DETAIL", ""):
            continue
        typ = a.get("type", "")
        if typ in ("Dividends", "Payment In Lieu Of Dividends"):
            kind = "dividend"
        elif typ == "Withholding Tax":
            kind = "withholding"
        else:
            continue
        when = a.get("dateTime") or a.get("settleDate") or a.get("reportDate") or ""
        out.append(CashIncome(_parse_ib_date(when), a.get("symbol", "").replace(" ", "-"), kind,
                              float(a.get("amount", 0))))
    return out


def load_activity(db, mode: str) -> tuple[list[Trade], list[Conversion]]:
    from .models import TradingEvent, TradingOrder, TradingRun

    orders = (db.query(TradingOrder).join(TradingRun, TradingRun.id == TradingOrder.run_id)
              .filter(TradingRun.mode == mode, TradingOrder.filled_qty > 0).all())
    trades = [Trade(o.submitted_at or o.updated_at, o.ticker, o.side, o.filled_qty, o.avg_fill_price or 0.0,
                    o.commission or 0.0, o.id) for o in orders]
    conversions = []
    for e in db.query(TradingEvent).filter_by(kind="fx").order_by(TradingEvent.id):
        d = e.details or {}
        if d.get("mode") == mode and d.get("sold_currency") == "EUR" and d.get("bought_currency") == "USD":
            conversions.append(Conversion(e.created_at, float(d["sold_amount"]), float(d["bought_amount"])))
    return trades, conversions


def build_report(db, year: int, mode: str, statement_xml: str | None = None,
                 rates: RateFn | None = None, rate_cache: str | None = None) -> TaxReport:
    trades, conversions = load_activity(db, mode)
    cash = parse_flex_cash(statement_xml) if statement_xml else []
    if rates is None:
        ecb = EcbRates(rate_cache)
        dates = [t.when.date() for t in trades] + [c.when.date() for c in conversions] + [c.when.date() for c in cash]
        if dates:
            ecb.load(min(dates) - timedelta(days=10), max(dates))
        rates = ecb
    return compute(year, trades, conversions, cash, rates, mode, dividends_included=statement_xml is not None)


# ── output ───────────────────────────────────────────────────────────────────

def _write_csv(path: Path, rows: list):
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()), delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))


def summary_text(rep: TaxReport) -> str:
    s = rep.summary()
    k, so = s["anlage_kap"], s["anlage_so_private_sales"]
    eur = lambda x: f"{x:>12,.2f} EUR".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
    lines = [
        f"NestLeap Steuerübersicht {rep.year} ({rep.mode}) — keine Steuerberatung",
        "",
        "Anlage KAP (ausländische Kapitalerträge ohne Steuerabzug)",
        f"  Kapitalerträge gesamt (Aktiengewinne + Dividenden)  {eur(k['capital_income_total_eur'])}",
        f"  davon Gewinne aus Aktienveräußerungen               {eur(k['of_which_share_gains_eur'])}",
        f"  Verluste aus Aktienveräußerungen                    {eur(k['share_losses_eur'])}",
        f"  Dividenden (brutto)                                 {eur(k['dividends_gross_eur'])}",
        f"  gezahlte US-Quellensteuer                           {eur(k['foreign_withholding_paid_eur'])}",
        f"  anrechenbare ausländische Steuer (max. 15 %)        {eur(k['creditable_foreign_tax_eur'])}",
        "",
        "Anlage SO (private Veräußerungsgeschäfte, Fremdwährung USD, Haltedauer <= 1 Jahr)",
        f"  Gewinne                                             {eur(so['currency_gains_within_one_year_eur'])}",
        f"  Verluste                                            {eur(so['currency_losses_within_one_year_eur'])}",
        f"  Saldo                                               {eur(so['currency_net_eur'])}"
        + ("   (unter der Freigrenze von 1.000 EUR)" if so["below_freigrenze"] else ""),
        "",
        f"Illustrative Abgeltungsteuer + Soli:                  {eur(s['illustrative_tax_eur'])}",
        f"  ({s['illustrative_tax_note']})",
        "",
        "Kurse: EZB-Referenzkurse USD/EUR am Handelstag; Aktien nach FIFO; Zeilennummern der Formulare",
        "bitte im aktuellen Vordruck prüfen.",
    ]
    if s["warnings"]:
        lines += ["", "Hinweise:"] + [f"  - {w}" for w in s["warnings"]]
    return "\n".join(lines)


def write_report(rep: TaxReport, out_dir: str) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_csv(out / "aktienverkaeufe.csv", rep.stock_sales)
    _write_csv(out / "waehrung_usd_23_estg.csv", rep.currency_disposals)
    _write_csv(out / "dividenden.csv", rep.dividends)
    (out / "summary.json").write_text(json.dumps(rep.summary(), indent=2, ensure_ascii=False))
    (out / "uebersicht.txt").write_text(summary_text(rep))
    return out
