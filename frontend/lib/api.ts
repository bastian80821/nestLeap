const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface StockAnalysis {
  ticker: string;
  name: string | null;
  sector: string | null;
  industry: string | null;
  market_cap: number | null;
  current_price: number | null;
  pe_ratio: number | null;
  forward_pe: number | null;
  peg_ratio: number | null;
  pb_ratio: number | null;
  ev_ebitda: number | null;
  roe: number | null;
  profit_margin: number | null;
  operating_margin: number | null;
  debt_to_equity: number | null;
  current_ratio: number | null;
  fcf_yield: number | null;
  revenue_growth: number | null;
  earnings_growth: number | null;
  dividend_yield: number | null;
  beta: number | null;
  sma_200_pct: number | null;
  rsi_14: number | null;
  week_52_low: number | null;
  week_52_high: number | null;
  overall_score: number | null;
  fair_value: number | null;
  buy_below: number | null;
  sell_above: number | null;
  valuation: string | null;
  summary: string | null;
  risks: string[] | null;
  catalysts: string[] | null;
  outlook: string | null;
  analyzed_at: string | null;
}

export interface DashboardOpportunity {
  ticker: string;
  name: string | null;
  sector: string | null;
  current_price: number | null;
  fair_value: number | null;
  upside_pct: number | null;
  overall_score: number | null;
  valuation: string | null;
}

export interface DashboardData {
  summary: {
    total_analyzed: number;
    undervalued_count: number;
    fair_value_count: number;
    overvalued_count: number;
    avg_score: number | null;
  };
  top_buys: DashboardOpportunity[];
  urgent_sells: DashboardOpportunity[];
  all_undervalued: DashboardOpportunity[];
  all_fair_value: DashboardOpportunity[];
  all_overvalued: DashboardOpportunity[];
}

export interface BatchStatus {
  running: boolean;
  total: number;
  completed: number;
  failed: number;
  current_ticker: string | null;
  failures: string[];
}

export interface PortfolioPosition {
  ticker: string;
  shares: number;
  avg_cost: number;
  current_price: number;
  value: number;
  gain_loss: number;
  gain_loss_pct: number;
}

export interface PortfolioTrade {
  ticker: string;
  action: string;
  shares: number;
  price: number;
  total: number;
  reason: string | null;
  date: string | null;
}

export interface PortfolioData {
  total_value: number;
  cash: number;
  holdings_value: number;
  total_invested: number;
  gain_loss: number;
  gain_loss_pct: number;
  sp500_value: number;
  sp500_gain_pct: number;
  num_holdings: number;
  positions: PortfolioPosition[];
  trades: PortfolioTrade[];
}

export interface PortfolioHistoryPoint {
  date: string;
  portfolio: number;
  sp500: number;
  invested: number;
}

export interface MarketIndicators {
  sp500: number | null;
  sp500_change_pct: number | null;
  vix: number | null;
  dow_change_pct: number | null;
  nasdaq_change_pct: number | null;
  treasury_10y: number | null;
}

export interface AiMarketSummary {
  summary: string;
  indicators: MarketIndicators;
  generated_at: string;
}

export async function getMarketSummary(): Promise<AiMarketSummary | null> {
  const res = await fetch(`${API_URL}/api/market-summary`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Market summary fetch failed: ${res.status}`);
  return res.json();
}

export async function generateMarketSummary(): Promise<AiMarketSummary> {
  const res = await fetch(`${API_URL}/api/market-summary`, { method: "POST" });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new Error(data?.detail || `Market summary failed: ${res.status}`);
  }
  return res.json();
}

export async function getDashboard(): Promise<DashboardData> {
  const res = await fetch(`${API_URL}/api/dashboard`);
  if (!res.ok) throw new Error(`Dashboard fetch failed: ${res.status}`);
  return res.json();
}

export async function getStockAnalysis(ticker: string): Promise<StockAnalysis | null> {
  const res = await fetch(`${API_URL}/api/stock/${ticker}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function checkUniverse(ticker: string): Promise<boolean> {
  const res = await fetch(`${API_URL}/api/stock/${ticker}/in-universe`);
  if (!res.ok) return false;
  const data = await res.json();
  return data.in_universe;
}

export async function runAnalysis(ticker: string): Promise<StockAnalysis> {
  const res = await fetch(`${API_URL}/api/stock/${ticker}/analyze`, { method: "POST" });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new Error(data?.detail || `Analysis failed: ${res.status}`);
  }
  return res.json();
}

export async function startBatch(): Promise<void> {
  const res = await fetch(`${API_URL}/api/batch/run`, { method: "POST" });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new Error(data?.detail || `Batch start failed: ${res.status}`);
  }
}

export async function getBatchStatus(): Promise<BatchStatus> {
  const res = await fetch(`${API_URL}/api/batch/status`);
  if (!res.ok) throw new Error(`Batch status failed: ${res.status}`);
  return res.json();
}

export async function getPortfolio(): Promise<PortfolioData> {
  const res = await fetch(`${API_URL}/api/portfolio`);
  if (!res.ok) throw new Error(`Portfolio fetch failed: ${res.status}`);
  return res.json();
}

export async function getPortfolioHistory(): Promise<PortfolioHistoryPoint[]> {
  const res = await fetch(`${API_URL}/api/portfolio/history`);
  if (!res.ok) return [];
  return res.json();
}
