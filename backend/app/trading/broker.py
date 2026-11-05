"""Broker interface plus a simulated broker.

SimBroker fills limit orders against live market prices and charges IBKR-style fees
(stocks, fixed pricing: $0.005/share, $1 minimum, at most 1% of value; currency
conversion: USD 2 minimum). With TRADING_BROKER=sim the whole weekly pipeline runs for
real, minus the money.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol


@dataclass
class BrokerPosition:
    ticker: str
    shares: float
    avg_cost: float


@dataclass
class OrderUpdate:
    status: str  # submitted | partially_filled | filled | cancelled | failed
    filled_qty: float = 0.0
    avg_fill_price: float | None = None
    commission: float = 0.0


@dataclass
class Conversion:
    sold_currency: str
    sold_amount: float
    bought_currency: str
    bought_amount: float  # after fees
    rate: float  # bought per sold
    fee_usd: float


@dataclass
class Execution:
    broker_order_id: str
    ref: str  # order reference; NestLeap orders use "nestleap-<id>"
    ticker: str
    side: str
    shares: float
    price: float
    time: str


class Broker(Protocol):
    name: str

    def account_id(self) -> str: ...
    def cash(self, currency: str = "USD") -> float: ...
    def cash_balances(self) -> dict[str, float]: ...
    def positions(self) -> dict[str, BrokerPosition]: ...
    def last_price(self, ticker: str) -> float | None: ...
    def place_limit(self, ticker: str, side: str, qty: float, limit_price: float, ref: str) -> str: ...
    def order_update(self, broker_order_id: str) -> OrderUpdate: ...
    def cancel(self, broker_order_id: str) -> None: ...
    def convert(self, sell_currency: str, buy_currency: str, sell_amount: float) -> Conversion: ...
    def executions(self) -> list[Execution]: ...


def ibkr_fee(shares: float, price: float) -> float:
    return round(min(max(1.0, 0.005 * shares), 0.01 * shares * price), 2)


def fx_rate(currency: str) -> float | None:
    """USD per one unit of `currency` (live, via yfinance)."""
    if currency.upper() == "USD":
        return 1.0
    from ..analysis.portfolio import _get_live_price

    return _get_live_price(f"{currency.upper()}USD=X")


@dataclass
class _SimState:
    cash: dict = field(default_factory=dict)  # currency -> amount
    positions: dict = field(default_factory=dict)  # ticker -> [shares, avg_cost]
    orders: dict = field(default_factory=dict)  # id -> {...}
    fills: list = field(default_factory=list)
    next_id: int = 1


class SimBroker:
    """Simulated multi-currency account. Orders fill immediately if the market price
    satisfies the limit, else stay open until cancelled. Persists to JSON if given a path."""

    name = "sim"
    FX_FEE_USD = 2.0

    def __init__(self, price_fn: Callable[[str], float | None], state_path: str | None = None,
                 account: str = "SIM-PAPER", fx_fn: Callable[[str], float | None] | None = None):
        self._price = price_fn
        self._fx = fx_fn or fx_rate
        self._path = Path(state_path) if state_path else None
        self._account = account
        if self._path and self._path.exists():
            self.s = _SimState(**json.loads(self._path.read_text()))
        else:
            self.s = _SimState()

    def _save(self):
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self.s), indent=1))
            os.replace(tmp, self._path)

    def deposit(self, amount: float, currency: str = "USD"):
        self.s.cash[currency] = self.s.cash.get(currency, 0.0) + amount
        self._save()

    # -- Broker ---------------------------------------------------------------
    def account_id(self) -> str:
        return self._account

    def cash(self, currency: str = "USD") -> float:
        return self.s.cash.get(currency, 0.0)

    def cash_balances(self) -> dict[str, float]:
        return {k: v for k, v in self.s.cash.items() if abs(v) > 1e-9}

    def positions(self) -> dict[str, BrokerPosition]:
        return {t: BrokerPosition(t, p[0], p[1]) for t, p in self.s.positions.items() if p[0] > 1e-9}

    def last_price(self, ticker: str) -> float | None:
        return self._price(ticker)

    def place_limit(self, ticker, side, qty, limit_price, ref) -> str:
        oid = str(self.s.next_id)
        self.s.next_id += 1
        self.s.orders[oid] = {"ticker": ticker, "side": side, "qty": qty, "limit": limit_price,
                              "ref": ref, "status": "submitted", "filled": 0.0, "price": None, "fee": 0.0}
        self._try_fill(oid)
        self._save()
        return oid

    def _try_fill(self, oid):
        o = self.s.orders[oid]
        if o["status"] != "submitted":
            return
        px = self._price(o["ticker"])
        if px is None:
            return
        if not (px <= o["limit"] if o["side"] == "buy" else px >= o["limit"]):
            return
        qty, fee = o["qty"], ibkr_fee(o["qty"], px)
        pos = self.s.positions.get(o["ticker"], [0.0, 0.0])
        usd = self.s.cash.get("USD", 0.0)
        if o["side"] == "buy":
            if qty * px + fee > usd + 1e-6:
                o["status"] = "failed"
                return
            new = pos[0] + qty
            pos = [new, (pos[0] * pos[1] + qty * px) / new]
            usd -= qty * px + fee
        else:
            if qty > pos[0] + 1e-9:
                o["status"] = "failed"
                return
            pos = [pos[0] - qty, pos[1]]
            usd += qty * px - fee
        self.s.cash["USD"] = usd
        self.s.positions[o["ticker"]] = pos
        o.update(status="filled", filled=qty, price=px, fee=fee)
        self.s.fills.append({"id": oid, "ref": o["ref"], "ticker": o["ticker"], "side": o["side"],
                             "shares": qty, "price": px, "time": datetime.now(timezone.utc).isoformat()})

    def order_update(self, broker_order_id) -> OrderUpdate:
        self._try_fill(broker_order_id)
        self._save()
        o = self.s.orders[broker_order_id]
        return OrderUpdate(o["status"], o["filled"], o["price"], o["fee"])

    def cancel(self, broker_order_id) -> None:
        o = self.s.orders[broker_order_id]
        if o["status"] == "submitted":
            o["status"] = "cancelled"
        self._save()

    def convert(self, sell_currency, buy_currency, sell_amount) -> Conversion:
        if sell_amount > self.cash(sell_currency) + 1e-6:
            raise RuntimeError(f"Not enough {sell_currency} to convert {sell_amount:.2f}")
        usd_per_sell, usd_per_buy = self._fx(sell_currency), self._fx(buy_currency)
        if not usd_per_sell or not usd_per_buy:
            raise RuntimeError("No FX rate available")
        rate = usd_per_sell / usd_per_buy
        fee_in_buy = self.FX_FEE_USD / usd_per_buy
        bought = sell_amount * rate - fee_in_buy
        self.s.cash[sell_currency] = self.cash(sell_currency) - sell_amount
        self.s.cash[buy_currency] = self.cash(buy_currency) + bought
        self._save()
        return Conversion(sell_currency, sell_amount, buy_currency, bought, rate, self.FX_FEE_USD)

    def executions(self) -> list[Execution]:
        return [Execution(f["id"], f["ref"], f["ticker"], f["side"], f["shares"], f["price"], f["time"])
                for f in self.s.fills]


def make_broker(settings=None) -> Broker:
    from ..config import settings as default_settings
    from ..analysis.portfolio import _get_live_price

    s = settings or default_settings
    if s.trading_broker == "sim":
        return SimBroker(_get_live_price, s.trading_sim_state, account=f"SIM-{s.trading_mode.upper()}")
    if s.trading_broker == "ibkr":
        from .ibkr import IBKRBroker

        return IBKRBroker(s.ib_host, s.ib_port, s.ib_client_id, s.ib_account or None, _get_live_price)
    raise ValueError(f"Unknown TRADING_BROKER {s.trading_broker!r}")
