from pydantic import BaseModel
from datetime import datetime


class StockAnalysisResponse(BaseModel):
    ticker: str
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    current_price: float | None = None

    pe_ratio: float | None = None
    forward_pe: float | None = None
    peg_ratio: float | None = None
    pb_ratio: float | None = None
    ev_ebitda: float | None = None

    roe: float | None = None
    profit_margin: float | None = None
    operating_margin: float | None = None
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    fcf_yield: float | None = None

    revenue_growth: float | None = None
    earnings_growth: float | None = None
    dividend_yield: float | None = None
    beta: float | None = None

    sma_200_pct: float | None = None
    rsi_14: float | None = None
    week_52_low: float | None = None
    week_52_high: float | None = None

    quality_score: float | None = None
    value_score: float | None = None
    growth_score: float | None = None
    momentum_score: float | None = None
    overall_score: float | None = None

    fair_value: float | None = None
    buy_below: float | None = None
    sell_above: float | None = None
    valuation: str | None = None
    conviction: int | None = None
    summary: str | None = None
    risks: list[str] | None = None
    catalysts: list[str] | None = None
    outlook: str | None = None

    analyzed_at: datetime | None = None

    model_config = {"from_attributes": True}


class StockSearchResult(BaseModel):
    ticker: str
    name: str
    sector: str | None = None
    current_price: float | None = None
    overall_score: float | None = None
    valuation: str | None = None
    analyzed_at: datetime | None = None

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str
    analyzed_stocks: int


class DashboardOpportunity(BaseModel):
    ticker: str
    name: str | None = None
    sector: str | None = None
    current_price: float | None = None
    fair_value: float | None = None
    upside_pct: float | None = None
    overall_score: float | None = None
    valuation: str | None = None

    model_config = {"from_attributes": True}


class MarketSummary(BaseModel):
    total_analyzed: int
    undervalued_count: int
    fair_value_count: int
    overvalued_count: int
    avg_score: float | None = None


class DashboardResponse(BaseModel):
    summary: MarketSummary
    top_buys: list[DashboardOpportunity]
    urgent_sells: list[DashboardOpportunity]
    all_undervalued: list[DashboardOpportunity]
    all_fair_value: list[DashboardOpportunity]
    all_overvalued: list[DashboardOpportunity]


class BatchStatusResponse(BaseModel):
    running: bool
    total: int
    completed: int
    failed: int
    current_ticker: str | None = None
    failures: list[str]


class PortfolioPosition(BaseModel):
    ticker: str
    shares: float
    avg_cost: float
    current_price: float
    value: float
    gain_loss: float
    gain_loss_pct: float


class PortfolioTradeResponse(BaseModel):
    ticker: str
    action: str
    shares: float
    price: float
    total: float
    reason: str | None = None
    date: str | None = None


class PortfolioResponse(BaseModel):
    total_value: float
    cash: float
    holdings_value: float
    total_invested: float
    gain_loss: float
    gain_loss_pct: float
    sp500_value: float
    sp500_gain_pct: float
    num_holdings: int
    positions: list[PortfolioPosition]
    trades: list[PortfolioTradeResponse]


class PortfolioHistoryPoint(BaseModel):
    date: str
    portfolio: float
    sp500: float
    invested: float


class MarketIndicatorsResponse(BaseModel):
    sp500: float | None = None
    sp500_change_pct: float | None = None
    vix: float | None = None
    dow_change_pct: float | None = None
    nasdaq_change_pct: float | None = None
    treasury_10y: float | None = None


class AiMarketSummary(BaseModel):
    summary: str
    indicators: MarketIndicatorsResponse
    generated_at: str
