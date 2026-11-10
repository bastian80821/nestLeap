"""Interactive Brokers adapter (via IB Gateway + ib_async).

NOT YET RUN AGAINST IBKR — written against the ib_async API and verified only with
mocks. Before any trading, run `python -m app.trading.cli check` against the PAPER
gateway: it prints the account, cash and positions, and asks IBKR to *simulate* a
fractional order (whatIfOrder — nothing is placed) to confirm fractional API orders
are enabled on the account.

Broker order ids are IBKR permIds, which survive gateway restarts.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from .broker import BrokerPosition, Conversion, Execution, OrderUpdate

logger = logging.getLogger(__name__)

_STATUS = {
    "Filled": "filled",
    "Cancelled": "cancelled",
    "ApiCancelled": "cancelled",
    "Inactive": "failed",
    "PendingCancel": "submitted",
    "PreSubmitted": "submitted",
    "Submitted": "submitted",
    "PendingSubmit": "submitted",
    "ApiPending": "submitted",
}


def to_ib_symbol(ticker: str) -> str:
    return ticker.replace("-", " ")  # BRK-B -> "BRK B"


def from_ib_symbol(symbol: str) -> str:
    return symbol.replace(" ", "-")


class IBKRBroker:
    name = "ibkr"

    def __init__(self, host: str, port: int, client_id: int, account: str | None,
                 price_fn: Callable[[str], float | None]):
        self._host, self._port, self._client_id = host, port, client_id
        self._account = account
        self._price = price_fn
        self._ib = None

    # -- connection -----------------------------------------------------------
    def _conn(self):
        if self._ib is None or not self._ib.isConnected():
            from ib_async import IB

            ib = IB()
            ib.connect(self._host, self._port, clientId=self._client_id, timeout=20)
            self._ib = ib
            if not self._account:
                accounts = ib.managedAccounts()
                if len(accounts) != 1:
                    raise RuntimeError(f"Set IB_ACCOUNT: gateway manages {accounts}")
                self._account = accounts[0]
        return self._ib

    def close(self):
        if self._ib is not None and self._ib.isConnected():
            self._ib.disconnect()

    def _contract(self, ticker: str):
        from ib_async import Stock

        c = Stock(to_ib_symbol(ticker), "SMART", "USD")
        qualified = self._conn().qualifyContracts(c)
        if not qualified:
            raise RuntimeError(f"IBKR does not recognise {ticker}")
        return qualified[0]

    # -- Broker ---------------------------------------------------------------
    def account_id(self) -> str:
        self._conn()
        return self._account

    def cash_balances(self) -> dict[str, float]:
        """Cash per currency. IBKR reports per-currency balances as CashBalance or
        $LEDGER-CashBalance depending on the account; TotalCashValue (base currency only)
        is the fallback when neither is present."""
        values = self._conn().accountValues(self._account)
        out: dict[str, float] = {}
        for tag in ("CashBalance", "$LEDGER-CashBalance"):
            for v in values:
                if v.tag == tag and v.currency not in ("BASE", "") and float(v.value or 0):
                    out.setdefault(v.currency, float(v.value))
        if not out:
            for v in values:
                if v.tag == "TotalCashValue" and v.currency not in ("BASE", "") and float(v.value or 0):
                    out[v.currency] = float(v.value)
        return out

    def cash(self, currency: str = "USD") -> float:
        return self.cash_balances().get(currency, 0.0)

    def positions(self) -> dict[str, BrokerPosition]:
        out = {}
        for p in self._conn().positions(self._account):
            c = p.contract
            if c.secType == "STK" and c.currency == "USD" and p.position:
                t = from_ib_symbol(c.symbol)
                out[t] = BrokerPosition(t, float(p.position), float(p.avgCost))
        return out

    def last_price(self, ticker: str) -> float | None:
        return self._price(ticker)

    def _order(self, side: str, qty: float, limit_price: float, ref: str):
        from ib_async import LimitOrder

        return LimitOrder(
            side.upper(), qty, round(limit_price, 2),
            tif="DAY", outsideRth=False, orderRef=ref, account=self._account,
        )

    def place_limit(self, ticker, side, qty, limit_price, ref) -> str:
        ib = self._conn()
        trade = ib.placeOrder(self._contract(ticker), self._order(side, qty, limit_price, ref))
        for _ in range(20):  # permId arrives once IBKR acknowledges the order
            ib.sleep(0.5)
            if trade.order.permId:
                break
        if not trade.order.permId:
            raise RuntimeError(f"No permId from IBKR for {ticker} ({trade.orderStatus.status})")
        if trade.orderStatus.status == "Inactive":
            msgs = "; ".join(e.message for e in trade.log if e.message)
            raise RuntimeError(f"IBKR rejected {ticker}: {msgs}")
        return str(trade.order.permId)

    def _find_trade(self, perm_id: int):
        ib = self._conn()
        for t in ib.trades():
            if t.order.permId == perm_id:
                return t
        ib.reqOpenOrders()
        for t in ib.trades():
            if t.order.permId == perm_id:
                return t
        for t in ib.reqCompletedOrders(apiOnly=True):
            if t.order.permId == perm_id:
                return t
        return None

    def order_update(self, broker_order_id) -> OrderUpdate:
        ib = self._conn()
        perm = int(broker_order_id)
        fills = [f for f in ib.reqExecutions() if f.execution.permId == perm]
        filled = sum(float(f.execution.shares) for f in fills)
        avg = sum(float(f.execution.shares) * f.execution.price for f in fills) / filled if filled else None
        commission = sum((f.commissionReport.commission or 0.0) for f in fills if f.commissionReport)
        trade = self._find_trade(perm)
        status = _STATUS.get(trade.orderStatus.status, "submitted") if trade else ("filled" if filled else "submitted")
        if status == "submitted" and filled:
            status = "partially_filled"
        return OrderUpdate(status, filled, avg, round(commission, 4))

    def cancel(self, broker_order_id) -> None:
        trade = self._find_trade(int(broker_order_id))
        if trade and trade.orderStatus.status not in ("Filled", "Cancelled", "ApiCancelled", "Inactive"):
            self._conn().cancelOrder(trade.order)
            time.sleep(1)

    def convert(self, sell_currency, buy_currency, sell_amount) -> Conversion:
        """Market FX order on IDEALPRO, e.g. sell EUR for USD via the EUR.USD pair."""
        from ib_async import Forex, MarketOrder

        ib = self._conn()
        pair = Forex(f"{sell_currency}{buy_currency}")  # base = sell currency
        if not ib.qualifyContracts(pair):
            raise RuntimeError(f"IBKR does not recognise FX pair {sell_currency}{buy_currency}")
        order = MarketOrder("SELL", round(sell_amount, 2), account=self._account, orderRef="nestleap-fx")
        trade = ib.placeOrder(pair, order)
        for _ in range(60):
            ib.sleep(0.5)
            if trade.orderStatus.status in ("Filled", "Cancelled", "ApiCancelled", "Inactive"):
                break
        if trade.orderStatus.status != "Filled":
            msgs = "; ".join(e.message for e in trade.log if e.message)
            raise RuntimeError(f"FX conversion not filled ({trade.orderStatus.status}): {msgs}")
        filled = float(trade.orderStatus.filled)
        rate = float(trade.orderStatus.avgFillPrice)
        fee = sum((f.commissionReport.commission or 0.0) for f in trade.fills if f.commissionReport)
        return Conversion(sell_currency, filled, buy_currency, filled * rate - fee, rate, fee)

    def executions(self) -> list[Execution]:
        """Stock executions IBKR reports for this session (about the last day). The monthly
        Flex statement audit covers older history independently."""
        out = []
        for f in self._conn().reqExecutions():
            c, e = f.contract, f.execution
            if c.secType != "STK":
                continue
            out.append(Execution(str(e.permId), e.orderRef or "", from_ib_symbol(c.symbol),
                                 "buy" if e.side == "BOT" else "sell", float(e.shares), float(e.price),
                                 str(e.time)))
        return out

    # -- verification -------------------------------------------------------------
    def what_if(self, ticker: str, side: str, qty: float, limit_price: float):
        """Ask IBKR to evaluate an order without placing it."""
        return self._conn().whatIfOrder(self._contract(ticker), self._order(side, qty, limit_price, "whatif"))
