"""IBKR adapter logic against a stub of the ib_async IB object (no gateway needed)."""

from types import SimpleNamespace as NS

import pytest

from app.trading.ibkr import IBKRBroker, from_ib_symbol, to_ib_symbol


class StubIB:
    def __init__(self):
        self.placed = []
        self.cancelled = []
        self._trades = []
        self._fills = []
        self.reject = False

    def isConnected(self):
        return True

    def managedAccounts(self):
        return ["DU123456"]

    def accountValues(self, acct):
        return [NS(tag="CashBalance", currency="AUD", value="5000"), NS(tag="CashBalance", currency="USD", value="812.5")]

    def positions(self, acct):
        return [NS(contract=NS(secType="STK", currency="USD", symbol="BRK B"), position=1.5, avgCost=480.0),
                NS(contract=NS(secType="OPT", currency="USD", symbol="AAPL"), position=1, avgCost=3.0)]

    def qualifyContracts(self, c):
        return [c]

    def placeOrder(self, contract, order):
        order.permId = 9001 + len(self.placed)
        status = "Inactive" if self.reject else "Submitted"
        trade = NS(contract=contract, order=order, orderStatus=NS(status=status),
                   log=[NS(message="Fractional orders not permitted")] if self.reject else [])
        self.placed.append(trade)
        self._trades.append(trade)
        return trade

    def sleep(self, s):
        pass

    def trades(self):
        return self._trades

    def reqOpenOrders(self):
        return []

    def reqCompletedOrders(self, apiOnly=True):
        return []

    def reqExecutions(self):
        return self._fills

    def fills(self):
        return self._fills

    def cancelOrder(self, order):
        self.cancelled.append(order.permId)


@pytest.fixture
def broker():
    b = IBKRBroker("x", 4004, 1, None, price_fn=lambda t: 100.0)
    b._ib = StubIB()
    b._account = "DU123456"
    return b


def test_symbol_mapping():
    assert to_ib_symbol("BRK-B") == "BRK B" and from_ib_symbol("BRK B") == "BRK-B"


def test_cash_is_usd_only(broker):
    assert broker.cash() == 812.5


def test_positions_only_us_stocks(broker):
    pos = broker.positions()
    assert list(pos) == ["BRK-B"] and pos["BRK-B"].shares == 1.5


def test_place_limit_returns_perm_id_and_sets_order_fields(broker):
    oid = broker.place_limit("BRK-B", "buy", 0.25, 481.234, ref="nestleap-7")
    order = broker._ib.placed[0].order
    assert oid == "9001"
    assert (order.action, order.totalQuantity, order.lmtPrice, order.tif, order.outsideRth, order.orderRef) == \
        ("BUY", 0.25, 481.23, "DAY", False, "nestleap-7")
    assert broker._ib.placed[0].contract.symbol == "BRK B"


def test_rejected_order_raises(broker):
    broker._ib.reject = True
    with pytest.raises(RuntimeError, match="Fractional orders not permitted"):
        broker.place_limit("AAPL", "buy", 0.25, 100.0, ref="x")


def test_order_update_aggregates_partial_fills(broker):
    oid = broker.place_limit("AAPL", "buy", 2.0, 101.0, ref="x")
    ib = broker._ib
    ib._fills = [
        NS(execution=NS(permId=9001, shares=0.5, price=100.0), commissionReport=NS(commission=0.5)),
        NS(execution=NS(permId=9001, shares=1.0, price=101.0), commissionReport=NS(commission=0.5)),
        NS(execution=NS(permId=1234, shares=9.0, price=1.0), commissionReport=NS(commission=9.0)),
    ]
    upd = broker.order_update(oid)
    assert upd.status == "partially_filled"
    assert upd.filled_qty == 1.5 and upd.avg_fill_price == pytest.approx(100.6667, rel=1e-4)
    assert upd.commission == 1.0
    ib.placed[0].orderStatus.status = "Filled"
    assert broker.order_update(oid).status == "filled"


def test_cancel_only_open_orders(broker):
    oid = broker.place_limit("AAPL", "buy", 1.0, 101.0, ref="x")
    broker.cancel(oid)
    assert broker._ib.cancelled == [9001]
    broker._ib.placed[0].orderStatus.status = "Filled"
    broker.cancel(oid)
    assert broker._ib.cancelled == [9001]


def test_cash_falls_back_to_ledger_and_total_cash(broker):
    broker._ib.accountValues = lambda acct: [NS(tag="$LEDGER-CashBalance", currency="EUR", value="1000000.00"),
                                             NS(tag="$LEDGER-CashBalance", currency="BASE", value="1000000.00")]
    assert broker.cash_balances() == {"EUR": 1000000.0}
    broker._ib.accountValues = lambda acct: [NS(tag="TotalCashValue", currency="EUR", value="1000000.00")]
    assert broker.cash("EUR") == 1000000.0 and broker.cash("USD") == 0.0


def test_conversion_fee_in_sold_currency_does_not_reduce_usd_received(broker):
    def place(contract, order):
        t = NS(contract=contract, order=order, log=[],
               orderStatus=NS(status="Filled", filled=100.0, avgFillPrice=1.12255),
               fills=[NS(commissionReport=NS(commission=1.78192, currency="EUR"))])
        return t
    broker._ib.placeOrder = place
    import ib_async
    conv = broker.convert("EUR", "USD", 100.0)
    assert conv.bought_amount == pytest.approx(112.255)
    assert conv.fee_usd == pytest.approx(1.78192 * 1.12255, abs=1e-4)
