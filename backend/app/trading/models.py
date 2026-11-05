"""Audit trail for broker trading. Rows are appended and updated, never deleted."""

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, func

from ..database import Base


class TradingRun(Base):
    """One weekly decision: what the strategy proposed after a batch."""

    __tablename__ = "trading_runs"

    id = Column(Integer, primary_key=True)
    mode = Column(String, nullable=False)  # paper | live
    broker = Column(String, nullable=False)
    round_date = Column(Date, nullable=False, index=True)  # date of the analyses used
    # awaiting_approval | approved | rejected | submitted | done | no_trades | skipped | expired
    status = Column(String, nullable=False)
    coverage = Column(Float)
    risk_off = Column(Integer)
    fx_rate = Column(Float)  # USD per unit of the pool currency at proposal time
    pool_before = Column(Float)  # pool balance (pool currency) at proposal time
    allowance = Column(Float)  # new money this week may draw (pool currency)
    proceeds_before = Column(Float)  # sale-proceeds cash (USD) at proposal time
    budget_usd = Column(Float)  # proceeds + allowance, what the strategy could spend
    holdings_value = Column(Float)
    # Everything decide() saw, so the audit can recompute the decision independently.
    inputs = Column(JSON)
    note = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    decided_at = Column(DateTime)


class TradingOrder(Base):
    __tablename__ = "trading_orders"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("trading_runs.id"), nullable=False, index=True)
    ticker = Column(String, nullable=False)
    side = Column(String, nullable=False)  # buy | sell
    quantity = Column(Float, nullable=False)  # proposed shares
    est_price = Column(Float, nullable=False)  # price the strategy used
    est_value = Column(Float, nullable=False)
    strategy_quantity = Column(Float)  # what decide() produced, before safety clipping
    reason = Column(String)  # strategy's reason
    analysis_id = Column(Integer)  # StockAnalysis row behind the decision (Gemini reasoning)
    # proposed | approved | rejected | blocked | submitted | partially_filled | filled | cancelled | failed | expired
    status = Column(String, nullable=False)
    block_reason = Column(String)
    limit_price = Column(Float)
    submitted_quantity = Column(Float)
    broker_order_id = Column(String)
    filled_qty = Column(Float, default=0.0)
    avg_fill_price = Column(Float)
    commission = Column(Float, default=0.0)
    error = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    approved_at = Column(DateTime)
    submitted_at = Column(DateTime)
    updated_at = Column(DateTime)


class TradingLedger(Base):
    """Two buckets of money the strategy may use:
    pool      deposits in the pool currency (e.g. EUR); drawn at most N per week for buys
    proceeds  USD from sales, re-bought or held by the strategy
    Every fill writes the entries that fund or receive it."""

    __tablename__ = "trading_ledger"

    id = Column(Integer, primary_key=True)
    mode = Column(String, nullable=False, index=True)
    bucket = Column(String, nullable=False)  # pool | proceeds
    currency = Column(String, nullable=False)
    kind = Column(String, nullable=False)  # deposit | withdrawal | draw | buy | sell | adjustment
    amount = Column(Float, nullable=False)  # + adds, - spends
    fx_rate = Column(Float)
    run_id = Column(Integer)
    order_id = Column(Integer)
    note = Column(String)
    created_at = Column(DateTime, server_default=func.now())


class TradingEvent(Base):
    """Hash-chained: each row's hash covers its content and the previous row's hash, so
    any later edit or deletion breaks the chain (the audit checks it)."""

    __tablename__ = "trading_events"

    id = Column(Integer, primary_key=True)
    level = Column(String, nullable=False)  # info | warning | error
    kind = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    details = Column(JSON)
    created_at = Column(DateTime, server_default=func.now())
    prev_hash = Column(String)
    hash = Column(String)


class TradingSetting(Base):
    __tablename__ = "trading_settings"

    key = Column(String, primary_key=True)
    value = Column(Text)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AuditReport(Base):
    __tablename__ = "audit_reports"

    id = Column(Integer, primary_key=True)
    mode = Column(String, nullable=False)
    kind = Column(String, nullable=False)  # weekly | statement
    run_id = Column(Integer)
    passed = Column(Boolean, nullable=False)
    critical_failures = Column(Integer, default=0)
    warnings = Column(Integer, default=0)
    checks = Column(JSON)  # [{name, ok, severity, detail}]
    performance = Column(JSON)
    chain_head = Column(String)  # latest event hash at audit time (also sent in the notification)
    created_at = Column(DateTime, server_default=func.now())
