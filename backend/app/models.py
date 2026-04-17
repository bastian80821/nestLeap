from sqlalchemy import Column, Integer, String, Float, DateTime, Text, JSON, Date
from sqlalchemy.sql import func

from .database import Base


class StockAnalysis(Base):
    __tablename__ = "stock_analyses"

    id = Column(Integer, primary_key=True)
    ticker = Column(String, index=True, nullable=False)
    name = Column(String)
    sector = Column(String)
    industry = Column(String)
    market_cap = Column(Float)
    current_price = Column(Float)

    pe_ratio = Column(Float)
    forward_pe = Column(Float)
    peg_ratio = Column(Float)
    pb_ratio = Column(Float)
    ev_ebitda = Column(Float)

    roe = Column(Float)
    profit_margin = Column(Float)
    operating_margin = Column(Float)
    debt_to_equity = Column(Float)
    current_ratio = Column(Float)
    fcf_yield = Column(Float)

    revenue_growth = Column(Float)
    earnings_growth = Column(Float)

    dividend_yield = Column(Float)
    beta = Column(Float)

    sma_200_pct = Column(Float)
    rsi_14 = Column(Float)
    week_52_low = Column(Float)
    week_52_high = Column(Float)

    quality_score = Column(Float)
    value_score = Column(Float)
    growth_score = Column(Float)
    momentum_score = Column(Float)
    overall_score = Column(Float)

    fair_value = Column(Float)
    buy_below = Column(Float)
    sell_above = Column(Float)
    valuation = Column(String)
    conviction = Column(Integer)
    summary = Column(Text)
    risks = Column(JSON)
    catalysts = Column(JSON)
    outlook = Column(Text)

    analyzed_at = Column(DateTime, server_default=func.now())


class PortfolioTrade(Base):
    __tablename__ = "portfolio_trades"

    id = Column(Integer, primary_key=True)
    ticker = Column(String, nullable=False)
    action = Column(String, nullable=False)  # "buy" or "sell"
    shares = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    total = Column(Float, nullable=False)
    reason = Column(String)
    created_at = Column(DateTime, server_default=func.now())


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)
    total_value = Column(Float, nullable=False)
    cash = Column(Float, nullable=False)
    holdings_value = Column(Float, nullable=False)
    total_invested = Column(Float, nullable=False, default=0)
    sp500_shares = Column(Float, nullable=False, default=0)
    sp500_value = Column(Float, nullable=False)
    num_holdings = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class UserTicker(Base):
    __tablename__ = "user_tickers"

    id = Column(Integer, primary_key=True)
    ticker = Column(String, unique=True, nullable=False, index=True)
    added_at = Column(DateTime, server_default=func.now())


class ApiCallLog(Base):
    __tablename__ = "api_call_logs"

    id = Column(Integer, primary_key=True)
    model = Column(String)
    ticker = Column(String)
    prompt_tokens = Column(Integer)
    response_tokens = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())
