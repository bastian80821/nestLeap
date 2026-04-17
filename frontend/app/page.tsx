"use client";

import { useEffect, useState } from "react";
import {
  AiMarketSummary,
  DashboardData,
  DashboardOpportunity,
  PortfolioData,
  PortfolioHistoryPoint,
  StockAnalysis,
  getDashboard,
  getMarketSummary,
  getPortfolio,
  getPortfolioHistory,
  getStockAnalysis,
} from "@/lib/api";

type Tab = "dashboard" | "portfolio";

export default function Home() {
  const [tab, setTab] = useState<Tab>("dashboard");
  const [query, setQuery] = useState("");
  const [analysis, setAnalysis] = useState<StockAnalysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dark, setDark] = useState(true);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  const goHome = () => {
    setAnalysis(null);
    setError(null);
    setQuery("");
    setTab("dashboard");
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    const ticker = query.trim().toUpperCase();
    if (!ticker) return;
    setLoading(true);
    setError(null);
    setAnalysis(null);
    setLoadingMessage(null);
    try {
      const data = await getStockAnalysis(ticker);
      if (!data) {
        setError(`No analysis found for ${ticker}. It will be included in the next weekly batch.`);
      } else {
        setAnalysis(data);
      }
    } catch (err: any) {
      setError(err.message || "Something went wrong");
    } finally {
      setLoading(false);
      setLoadingMessage(null);
    }
  };

  const handleTickerClick = async (ticker: string) => {
    setQuery(ticker);
    setLoading(true);
    setError(null);
    setAnalysis(null);
    try {
      const data = await getStockAnalysis(ticker);
      setAnalysis(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-surface-primary">
      <header className="border-b border-border bg-surface-primary/80 backdrop-blur-md sticky top-0 z-10">
        <div className="max-w-[1100px] mx-auto px-5 h-14 flex items-center gap-5">
          <button
            onClick={goHome}
            className="text-lg font-semibold text-accent tracking-tight shrink-0 hover:opacity-80 transition"
          >
            NestLeap
          </button>

          <nav className="flex gap-0.5 shrink-0">
            {(["dashboard", "portfolio"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => { setAnalysis(null); setError(null); setTab(t); }}
                className={`px-3 py-1.5 text-sm rounded-md transition font-medium capitalize ${
                  tab === t && !analysis
                    ? "bg-surface-tertiary text-txt-primary"
                    : "text-txt-tertiary hover:text-txt-secondary"
                }`}
              >
                {t}
              </button>
            ))}
          </nav>

          <form onSubmit={handleSearch} className="flex-1 max-w-xs ml-auto">
            <div className="relative">
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value.toUpperCase())}
                placeholder="Search ticker..."
                maxLength={6}
                className="w-full bg-surface-secondary border border-border rounded-md px-3 py-1.5 text-sm text-txt-primary placeholder-txt-tertiary focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/30 transition"
              />
              <button
                type="submit"
                disabled={loading || !query.trim()}
                className="absolute right-1 top-1/2 -translate-y-1/2 bg-accent hover:bg-accent-hover disabled:opacity-30 text-white text-xs px-2.5 py-1 rounded transition font-medium"
              >
                {loading ? "..." : "Go"}
              </button>
            </div>
          </form>

          <button
            onClick={() => setDark(!dark)}
            className="p-1.5 rounded-md text-txt-tertiary hover:text-txt-primary hover:bg-surface-tertiary transition"
            title={dark ? "Light mode" : "Dark mode"}
          >
            {dark ? (
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                <path d="M10 2a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-1.5 0v-1.5A.75.75 0 0 1 10 2Zm0 13a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-1.5 0v-1.5A.75.75 0 0 1 10 15Zm-8-5a.75.75 0 0 1 .75-.75h1.5a.75.75 0 0 1 0 1.5h-1.5A.75.75 0 0 1 2 10Zm13 0a.75.75 0 0 1 .75-.75h1.5a.75.75 0 0 1 0 1.5h-1.5A.75.75 0 0 1 15 10ZM4.343 4.343a.75.75 0 0 1 1.06 0l1.061 1.06a.75.75 0 1 1-1.06 1.061l-1.06-1.06a.75.75 0 0 1 0-1.06Zm9.193 9.193a.75.75 0 0 1 1.06 0l1.061 1.06a.75.75 0 0 1-1.06 1.061l-1.06-1.06a.75.75 0 0 1 0-1.061ZM4.343 15.657a.75.75 0 0 1 0-1.06l1.06-1.061a.75.75 0 1 1 1.061 1.06l-1.06 1.061a.75.75 0 0 1-1.061 0Zm9.193-9.193a.75.75 0 0 1 0-1.06l1.06-1.061a.75.75 0 1 1 1.061 1.06l-1.06 1.06a.75.75 0 0 1-1.061 0ZM10 7a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z" />
              </svg>
            ) : (
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                <path fillRule="evenodd" d="M7.455 2.004a.75.75 0 0 1 .26.77 7 7 0 0 0 9.958 7.967.75.75 0 0 1 1.067.853A8.5 8.5 0 1 1 6.647 1.921a.75.75 0 0 1 .808.083Z" clipRule="evenodd" />
              </svg>
            )}
          </button>
        </div>
      </header>

      <main className="max-w-[1100px] mx-auto px-5 py-6">
        {error && (
          <div className="bg-negative-bg border border-negative/20 text-negative px-4 py-3 rounded-lg mb-6 text-sm">
            {error}
          </div>
        )}
        {loading && (
          <div className="flex flex-col items-center justify-center py-24 text-txt-tertiary">
            <div className="w-7 h-7 border-2 border-accent border-t-transparent rounded-full animate-spin mb-3" />
            <p className="text-sm text-center max-w-md">
              {loadingMessage || "Analyzing..."}
            </p>
          </div>
        )}
        {!loading && analysis && (
          <AnalysisView analysis={analysis} />
        )}
        {!loading && !analysis && tab === "dashboard" && (
          <DashboardView onTickerClick={handleTickerClick} />
        )}
        {!loading && !analysis && tab === "portfolio" && <PortfolioView />}
      </main>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   CARD — unified container
   ═══════════════════════════════════════════════════════════════════════════ */

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-surface-secondary border border-border rounded-lg p-5 ${className}`}>
      {children}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xs font-semibold text-txt-tertiary uppercase tracking-wider mb-3">
      {children}
    </h2>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   DASHBOARD
   ═══════════════════════════════════════════════════════════════════════════ */

function DashboardView({ onTickerClick }: { onTickerClick: (t: string) => void }) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [marketSummary, setMarketSummary] = useState<AiMarketSummary | null>(null);
  const [marketLoading, setMarketLoading] = useState(false);

  useEffect(() => {
    getDashboard().then(setData).catch(() => {});
  }, []);

  useEffect(() => {
    setMarketLoading(true);
    getMarketSummary()
      .then((ms) => { if (ms) setMarketSummary(ms); })
      .catch(() => {})
      .finally(() => setMarketLoading(false));
  }, []);

  const [filter, setFilter] = useState<"undervalued" | "fair" | "overvalued" | null>(null);

  const s = data?.summary;
  const ind = marketSummary?.indicators;

  const filteredRows = filter === "undervalued" ? data?.all_undervalued
    : filter === "fair" ? data?.all_fair_value
    : filter === "overvalued" ? data?.all_overvalued
    : null;

  const filterLabel = filter === "undervalued" ? "Undervalued Stocks"
    : filter === "fair" ? "Fair Value Stocks"
    : filter === "overvalued" ? "Overvalued Stocks"
    : null;

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Market summary */}
      <Card>
        <SectionLabel>Market Summary</SectionLabel>
        {marketSummary ? (
          <>
            {ind && (
              <div className="flex flex-wrap gap-4 mb-3 text-sm font-mono">
                {ind.sp500 !== null && (
                  <span className="text-txt-secondary">
                    S&P {ind.sp500.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                    {ind.sp500_change_pct !== null && (
                      <span className={`ml-1 ${ind.sp500_change_pct >= 0 ? "text-positive" : "text-negative"}`}>
                        {ind.sp500_change_pct >= 0 ? "+" : ""}{ind.sp500_change_pct.toFixed(2)}%
                      </span>
                    )}
                  </span>
                )}
                {ind.vix !== null && <span className="text-txt-secondary">VIX {ind.vix.toFixed(1)}</span>}
                {ind.dow_change_pct !== null && (
                  <span className="text-txt-secondary">
                    Dow <span className={ind.dow_change_pct >= 0 ? "text-positive" : "text-negative"}>
                      {ind.dow_change_pct >= 0 ? "+" : ""}{ind.dow_change_pct.toFixed(2)}%
                    </span>
                  </span>
                )}
                {ind.nasdaq_change_pct !== null && (
                  <span className="text-txt-secondary">
                    Nasdaq <span className={ind.nasdaq_change_pct >= 0 ? "text-positive" : "text-negative"}>
                      {ind.nasdaq_change_pct >= 0 ? "+" : ""}{ind.nasdaq_change_pct.toFixed(2)}%
                    </span>
                  </span>
                )}
                {ind.treasury_10y !== null && <span className="text-txt-secondary">10Y {ind.treasury_10y}%</span>}
              </div>
            )}
            <p className="text-sm text-txt-primary leading-relaxed">{marketSummary.summary}</p>
            <p className="text-xs text-txt-tertiary mt-2">
              Updated {new Date(marketSummary.generated_at).toLocaleString()}
            </p>
          </>
        ) : (
          <p className="text-sm text-txt-tertiary">
            {marketLoading ? "Loading market summary..." : "Market summary will be available shortly."}
          </p>
        )}
      </Card>

      {/* Stats row — 3 cards, full width */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="Undervalued" value={s?.undervalued_count ?? 0} color="positive" onClick={() => setFilter(filter === "undervalued" ? null : "undervalued")} active={filter === "undervalued"} />
        <StatCard label="Fair Value" value={s?.fair_value_count ?? 0} onClick={() => setFilter(filter === "fair" ? null : "fair")} active={filter === "fair"} />
        <StatCard label="Overvalued" value={s?.overvalued_count ?? 0} color="negative" onClick={() => setFilter(filter === "overvalued" ? null : "overvalued")} active={filter === "overvalued"} />
      </div>

      {/* Filtered list or default tables */}
      {filteredRows ? (
        <div>
          <div className="flex items-center justify-between mb-3">
            <SectionLabel>{filterLabel}</SectionLabel>
            <button onClick={() => setFilter(null)} className="text-xs text-txt-tertiary hover:text-accent transition">
              Clear filter
            </button>
          </div>
          {filteredRows.length > 0 ? (
            <OpportunityTable rows={filteredRows} onClick={onTickerClick} />
          ) : (
            <Card><p className="text-sm text-txt-tertiary text-center py-4">No stocks in this category yet.</p></Card>
          )}
        </div>
      ) : (
        <>
          {data && data.top_buys.length > 0 && (
            <div>
              <SectionLabel>Top Buying Opportunities</SectionLabel>
              <OpportunityTable rows={data.top_buys} onClick={onTickerClick} />
            </div>
          )}

          {data && data.urgent_sells.length > 0 && (
            <div>
              <SectionLabel>Most Overvalued</SectionLabel>
              <OpportunityTable rows={data.urgent_sells} onClick={onTickerClick} />
            </div>
          )}
        </>
      )}
    </div>
  );
}

function StatCard({ label, value, color, onClick, active }: { label: string; value: number | string; color?: "positive" | "negative"; onClick?: () => void; active?: boolean }) {
  const valueColor = color === "positive" ? "text-positive" : color === "negative" ? "text-negative" : "text-txt-primary";
  return (
    <button
      onClick={onClick}
      className={`bg-surface-secondary border rounded-lg p-5 text-center transition cursor-pointer hover:border-accent/50 ${
        active ? "border-accent ring-1 ring-accent/20" : "border-border"
      }`}
    >
      <p className="text-xs text-txt-tertiary mb-1">{label}</p>
      <p className={`text-2xl font-semibold tabular-nums ${valueColor}`}>{value}</p>
    </button>
  );
}

function OpportunityTable({ rows, onClick }: { rows: DashboardOpportunity[]; onClick: (t: string) => void }) {
  return (
    <Card className="p-0 overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-txt-tertiary uppercase tracking-wider border-b border-border">
            <th className="text-left px-4 py-2.5 font-medium">Ticker</th>
            <th className="text-left px-4 py-2.5 font-medium hidden sm:table-cell">Sector</th>
            <th className="text-right px-4 py-2.5 font-medium">Price</th>
            <th className="text-right px-4 py-2.5 font-medium">Fair Value</th>
            <th className="text-right px-4 py-2.5 font-medium">Upside</th>
            <th className="text-right px-4 py-2.5 font-medium">Score</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.ticker}
              onClick={() => onClick(r.ticker)}
              className="border-b border-border last:border-0 hover:bg-surface-tertiary/50 cursor-pointer transition"
            >
              <td className="px-4 py-2.5">
                <span className="font-medium text-txt-primary">{r.ticker}</span>
                <span className="text-txt-tertiary ml-2 text-xs hidden md:inline">{r.name}</span>
              </td>
              <td className="px-4 py-2.5 text-txt-secondary hidden sm:table-cell">{r.sector || "—"}</td>
              <td className="px-4 py-2.5 text-right text-txt-primary tabular-nums">${r.current_price?.toFixed(2) ?? "—"}</td>
              <td className="px-4 py-2.5 text-right text-txt-secondary tabular-nums">${r.fair_value?.toFixed(2) ?? "—"}</td>
              <td className={`px-4 py-2.5 text-right font-medium tabular-nums ${
                (r.upside_pct ?? 0) > 0 ? "text-positive" : "text-negative"
              }`}>
                {r.upside_pct !== null ? `${r.upside_pct > 0 ? "+" : ""}${r.upside_pct}%` : "—"}
              </td>
              <td className="px-4 py-2.5 text-right">
                <ScoreBadge score={r.overall_score} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   PORTFOLIO
   ═══════════════════════════════════════════════════════════════════════════ */

function PortfolioView() {
  const [data, setData] = useState<PortfolioData | null>(null);
  const [history, setHistory] = useState<PortfolioHistoryPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getPortfolio()
      .then(setData)
      .catch((e) => setError(e.message || "Failed to load portfolio"))
      .finally(() => setLoading(false));
    getPortfolioHistory().then(setHistory).catch(() => {});
  }, []);

  if (loading) {
    return (
      <div className="text-center py-24 text-txt-tertiary animate-fade-in">
        <div className="inline-block h-6 w-6 border-2 border-current border-t-transparent rounded-full animate-spin mb-3" />
        <p className="text-sm">Loading portfolio...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-24 text-txt-tertiary animate-fade-in">
        <p className="text-base mb-1">Failed to load portfolio</p>
        <p className="text-sm">{error}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="text-center py-24 text-txt-tertiary animate-fade-in">
        <p className="text-base mb-1">No portfolio data yet</p>
        <p className="text-sm">Run a batch analysis from the Dashboard to start the AI portfolio.</p>
      </div>
    );
  }

  const noTrades = data.trades.length === 0 && data.positions.length === 0;
  if (noTrades) {
    return (
      <div className="text-center py-24 text-txt-tertiary animate-fade-in">
        <p className="text-base mb-1">Portfolio is empty</p>
        <p className="text-sm">The AI will buy and sell stocks after the first batch analysis completes.</p>
      </div>
    );
  }

  const fmt = (n: number) => n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const beating = data.gain_loss_pct - data.sp500_gain_pct;

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
        <Card className="text-center">
          <p className="text-xs text-txt-tertiary mb-1">Total Invested</p>
          <p className="text-xl font-semibold text-txt-primary tabular-nums">${fmt(data.total_invested)}</p>
          <p className="text-xs text-txt-tertiary mt-0.5">$1,000 / week</p>
        </Card>
        <Card className="text-center">
          <p className="text-xs text-txt-tertiary mb-1">Portfolio Value</p>
          <p className="text-xl font-semibold text-txt-primary tabular-nums">${fmt(data.total_value)}</p>
          <p className="text-xs text-txt-tertiary mt-0.5 tabular-nums">${fmt(data.cash)} cash</p>
        </Card>
        <Card className="text-center">
          <p className="text-xs text-txt-tertiary mb-1">AI Return</p>
          <p className={`text-xl font-semibold tabular-nums ${data.gain_loss >= 0 ? "text-positive" : "text-negative"}`}>
            {data.gain_loss >= 0 ? "+" : ""}{data.gain_loss_pct.toFixed(2)}%
          </p>
          <p className="text-xs text-txt-tertiary mt-0.5 tabular-nums">
            {data.gain_loss >= 0 ? "+" : ""}${fmt(data.gain_loss)}
          </p>
        </Card>
        <Card className="text-center">
          <p className="text-xs text-txt-tertiary mb-1">S&P 500 Return</p>
          <p className={`text-xl font-semibold tabular-nums ${data.sp500_gain_pct >= 0 ? "text-positive" : "text-negative"}`}>
            {data.sp500_gain_pct >= 0 ? "+" : ""}{data.sp500_gain_pct.toFixed(2)}%
          </p>
          <p className="text-xs text-txt-tertiary mt-0.5 tabular-nums">${fmt(data.sp500_value)}</p>
        </Card>
        <Card className="text-center">
          <p className="text-xs text-txt-tertiary mb-1">vs S&P 500</p>
          <p className={`text-xl font-semibold tabular-nums ${beating >= 0 ? "text-positive" : "text-negative"}`}>
            {beating >= 0 ? "+" : ""}{beating.toFixed(2)}%
          </p>
          <p className="text-xs text-txt-tertiary mt-0.5">{data.num_holdings} holdings</p>
        </Card>
      </div>

      {history.length > 1 && (
        <Card>
          <SectionLabel>Performance vs S&P 500</SectionLabel>
          <PerformanceChart data={history} />
        </Card>
      )}

      {data.positions.length > 0 && (
        <div>
          <SectionLabel>Current Holdings</SectionLabel>
          <Card className="p-0 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-txt-tertiary uppercase tracking-wider border-b border-border">
                  <th className="text-left px-4 py-2.5 font-medium">Ticker</th>
                  <th className="text-right px-4 py-2.5 font-medium">Shares</th>
                  <th className="text-right px-4 py-2.5 font-medium">Avg Cost</th>
                  <th className="text-right px-4 py-2.5 font-medium">Price</th>
                  <th className="text-right px-4 py-2.5 font-medium">Value</th>
                  <th className="text-right px-4 py-2.5 font-medium">P&L</th>
                </tr>
              </thead>
              <tbody>
                {data.positions.map((p) => (
                  <tr key={p.ticker} className="border-b border-border last:border-0">
                    <td className="px-4 py-2.5 font-medium text-txt-primary">{p.ticker}</td>
                    <td className="px-4 py-2.5 text-right text-txt-secondary tabular-nums">{p.shares.toFixed(2)}</td>
                    <td className="px-4 py-2.5 text-right text-txt-secondary tabular-nums">${p.avg_cost.toFixed(2)}</td>
                    <td className="px-4 py-2.5 text-right text-txt-primary tabular-nums">${p.current_price.toFixed(2)}</td>
                    <td className="px-4 py-2.5 text-right text-txt-primary tabular-nums">${p.value.toFixed(2)}</td>
                    <td className={`px-4 py-2.5 text-right font-medium tabular-nums ${
                      p.gain_loss >= 0 ? "text-positive" : "text-negative"
                    }`}>
                      {p.gain_loss >= 0 ? "+" : ""}{p.gain_loss_pct.toFixed(1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}

      {data.trades.length > 0 && (
        <div>
          <SectionLabel>Recent Trades</SectionLabel>
          <Card className="p-0 overflow-hidden divide-y divide-border">
            {data.trades.map((t, i) => (
              <div key={i} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <span className={`text-xs font-semibold px-2 py-0.5 rounded ${
                  t.action === "buy"
                    ? "bg-positive-bg text-positive"
                    : "bg-negative-bg text-negative"
                }`}>
                  {t.action.toUpperCase()}
                </span>
                <span className="font-medium text-txt-primary">{t.ticker}</span>
                <span className="text-txt-secondary tabular-nums">{t.shares.toFixed(2)} @ ${t.price.toFixed(2)}</span>
                <span className="text-txt-tertiary ml-auto text-xs">{t.reason}</span>
              </div>
            ))}
          </Card>
        </div>
      )}
    </div>
  );
}

function PerformanceChart({ data }: { data: PortfolioHistoryPoint[] }) {
  if (data.length < 2) return null;

  const allValues = data.flatMap((d) => [d.portfolio, d.sp500, d.invested]);
  const min = Math.min(...allValues) * 0.95;
  const max = Math.max(...allValues) * 1.05;
  const range = max - min || 1;

  const w = 600;
  const h = 200;
  const toX = (i: number) => (i / (data.length - 1)) * w;
  const toY = (v: number) => h - ((v - min) / range) * h;

  const portfolioPath = data.map((d, i) => `${i === 0 ? "M" : "L"}${toX(i)},${toY(d.portfolio)}`).join(" ");
  const sp500Path = data.map((d, i) => `${i === 0 ? "M" : "L"}${toX(i)},${toY(d.sp500)}`).join(" ");
  const investedPath = data.map((d, i) => `${i === 0 ? "M" : "L"}${toX(i)},${toY(d.invested)}`).join(" ");

  return (
    <div className="w-full overflow-x-auto">
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-48" preserveAspectRatio="none">
        <path d={investedPath} fill="none" stroke="var(--text-tertiary)" strokeWidth="1" strokeDasharray="4 3" opacity="0.4" />
        <path d={sp500Path} fill="none" stroke="var(--text-tertiary)" strokeWidth="1.5" opacity="0.6" />
        <path d={portfolioPath} fill="none" stroke="var(--accent)" strokeWidth="2" />
      </svg>
      <div className="flex gap-5 mt-2 text-xs text-txt-tertiary">
        <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-accent inline-block rounded" /> AI Portfolio</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-txt-tertiary inline-block rounded opacity-60" /> S&P 500</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 bg-txt-tertiary inline-block rounded opacity-40" style={{ borderTop: "1px dashed" }} /> Invested</span>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   STOCK ANALYSIS VIEW
   ═══════════════════════════════════════════════════════════════════════════ */

function AnalysisView({ analysis: a }: { analysis: StockAnalysis }) {
  const upside =
    a.current_price && a.fair_value
      ? ((a.fair_value - a.current_price) / a.current_price) * 100
      : null;

  return (
    <div className="animate-fade-in space-y-5">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2.5 mb-1">
          <h2 className="text-2xl font-bold text-txt-primary">{a.ticker}</h2>
          <ValuationBadge valuation={a.valuation} />
          <ScoreBadge score={a.overall_score} />
        </div>
        <p className="text-sm text-txt-secondary">
          {a.name} &middot; {a.sector} &middot; {a.industry}
        </p>
      </div>

      {/* Price section — uniform grid */}
      <Card>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
          <PriceCell label="Current Price" value={a.current_price} large />
          <PriceCell label="Fair Value" value={a.fair_value} />
          <PriceCell label="Buy Below" value={a.buy_below} />
          <PriceCell label="Sell Above" value={a.sell_above} />
          <div>
            <p className="text-xs text-txt-tertiary mb-1">Upside</p>
            {upside !== null ? (
              <p className={`text-lg font-semibold tabular-nums ${upside >= 0 ? "text-positive" : "text-negative"}`}>
                {upside >= 0 ? "+" : ""}{upside.toFixed(1)}%
              </p>
            ) : (
              <p className="text-lg text-txt-tertiary">—</p>
            )}
          </div>
        </div>
        {a.buy_below && a.sell_above && a.current_price && a.fair_value && (
          <PriceBar buyBelow={a.buy_below} fairValue={a.fair_value} sellAbove={a.sell_above} current={a.current_price} />
        )}
      </Card>

      {/* Thesis */}
      {a.summary && (
        <Card>
          <SectionLabel>Investment Thesis</SectionLabel>
          <p className="text-sm text-txt-primary leading-relaxed">{a.summary}</p>
        </Card>
      )}

      {/* Risks & Catalysts — side by side */}
      {(a.risks?.length || a.catalysts?.length) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {a.risks && a.risks.length > 0 && (
            <Card>
              <SectionLabel>Key Risks</SectionLabel>
              <ul className="space-y-2">
                {a.risks.map((r, i) => (
                  <li key={i} className="text-sm text-txt-secondary leading-relaxed flex gap-2">
                    <span className="text-negative mt-0.5 shrink-0">&#x2022;</span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {a.catalysts && a.catalysts.length > 0 && (
            <Card>
              <SectionLabel>Catalysts</SectionLabel>
              <ul className="space-y-2">
                {a.catalysts.map((c, i) => (
                  <li key={i} className="text-sm text-txt-secondary leading-relaxed flex gap-2">
                    <span className="text-positive mt-0.5 shrink-0">&#x2022;</span>
                    <span>{c}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}

      {/* Outlook */}
      {a.outlook && (
        <Card>
          <SectionLabel>2–5 Year Outlook</SectionLabel>
          <p className="text-sm text-txt-primary leading-relaxed">{a.outlook}</p>
        </Card>
      )}

      {/* Key Metrics */}
      <Card>
        <SectionLabel>Key Metrics</SectionLabel>
        <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-4 gap-x-6 gap-y-3">
          <MetricCell label="P/E" value={a.pe_ratio} fmt="ratio" />
          <MetricCell label="Forward P/E" value={a.forward_pe} fmt="ratio" />
          <MetricCell label="PEG" value={a.peg_ratio} fmt="ratio" />
          <MetricCell label="P/B" value={a.pb_ratio} fmt="ratio" />
          <MetricCell label="EV/EBITDA" value={a.ev_ebitda} fmt="ratio" />
          <MetricCell label="ROE" value={a.roe} fmt="pct" />
          <MetricCell label="Profit Margin" value={a.profit_margin} fmt="pct" />
          <MetricCell label="Op. Margin" value={a.operating_margin} fmt="pct" />
          <MetricCell label="Debt/Equity" value={a.debt_to_equity} fmt="ratio" />
          <MetricCell label="Current Ratio" value={a.current_ratio} fmt="ratio" />
          <MetricCell label="FCF Yield" value={a.fcf_yield} fmt="pct" />
          <MetricCell label="Rev Growth" value={a.revenue_growth} fmt="pct" />
          <MetricCell label="EPS Growth" value={a.earnings_growth} fmt="pct" />
          <MetricCell label="Div Yield" value={a.dividend_yield} fmt="pct" />
          <MetricCell label="Beta" value={a.beta} fmt="ratio" />
          <MetricCell label="RSI(14)" value={a.rsi_14} fmt="ratio" />
        </div>
      </Card>

      <p className="text-xs text-txt-tertiary text-right">
        Mkt cap: {a.market_cap ? `$${(a.market_cap / 1e9).toFixed(1)}B` : "—"} &middot; Analyzed: {a.analyzed_at ? new Date(a.analyzed_at).toLocaleDateString() : "—"}
      </p>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   SHARED COMPONENTS
   ═══════════════════════════════════════════════════════════════════════════ */

function PriceCell({ label, value, large }: { label: string; value: number | null | undefined; large?: boolean }) {
  return (
    <div>
      <p className="text-xs text-txt-tertiary mb-1">{label}</p>
      {value != null ? (
        <p className={`font-semibold tabular-nums text-txt-primary ${large ? "text-2xl" : "text-lg"}`}>
          ${value.toFixed(2)}
        </p>
      ) : (
        <p className={`text-txt-tertiary ${large ? "text-2xl" : "text-lg"}`}>—</p>
      )}
    </div>
  );
}

function PriceBar({ buyBelow, fairValue, sellAbove, current }: { buyBelow: number; fairValue: number; sellAbove: number; current: number }) {
  const allValues = [buyBelow, fairValue, sellAbove, current];
  const dataMin = Math.min(...allValues);
  const dataMax = Math.max(...allValues);
  const padding = (dataMax - dataMin) * 0.12 || dataMin * 0.05;
  const min = dataMin - padding;
  const max = dataMax + padding;
  const range = max - min || 1;
  const pos = (v: number) => ((v - min) / range) * 100;

  const markers: { value: number; label: string; color: string }[] = [
    { value: buyBelow, label: "Buy", color: "text-positive" },
    { value: fairValue, label: "Fair", color: "text-accent" },
    { value: sellAbove, label: "Sell", color: "text-negative" },
  ];

  return (
    <div className="mt-5 mb-1">
      {/* Labels above the bar */}
      <div className="relative h-8">
        {markers.map((m) => (
          <div
            key={m.label}
            className="absolute -translate-x-1/2 text-center"
            style={{ left: `${pos(m.value)}%` }}
          >
            <p className={`text-[10px] font-medium ${m.color}`}>{m.label}</p>
            <p className="text-[10px] text-txt-tertiary tabular-nums">${m.value.toFixed(0)}</p>
          </div>
        ))}
      </div>

      {/* Bar */}
      <div className="relative h-2 bg-surface-tertiary rounded-full">
        {/* Buy zone (green, left of buyBelow) */}
        <div className="absolute inset-y-0 bg-positive/15 rounded-l-full" style={{ left: 0, width: `${pos(buyBelow)}%` }} />
        {/* Sell zone (red, right of sellAbove) */}
        <div className="absolute inset-y-0 bg-negative/15 rounded-r-full" style={{ left: `${pos(sellAbove)}%`, right: 0 }} />

        {/* Marker ticks */}
        {markers.map((m) => (
          <div
            key={m.label}
            className="absolute top-0 bottom-0 w-px bg-txt-tertiary/40"
            style={{ left: `${pos(m.value)}%` }}
          />
        ))}

        {/* Current price dot */}
        <div
          className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-txt-primary border-2 border-surface-secondary shadow-sm"
          style={{ left: `${pos(current)}%`, marginLeft: "-6px" }}
        />
      </div>

      {/* Current price label below */}
      <div className="relative h-5">
        <div
          className="absolute -translate-x-1/2 text-center mt-0.5"
          style={{ left: `${pos(current)}%` }}
        >
          <p className="text-[10px] font-semibold text-txt-primary tabular-nums">${current.toFixed(0)} <span className="font-normal text-txt-tertiary">now</span></p>
        </div>
      </div>
    </div>
  );
}

function ScoreBadge({ score }: { score: number | null }) {
  if (score === null) return null;
  const s = Math.round(score);
  const color = s >= 65 ? "text-positive bg-positive-bg" : s >= 45 ? "text-warning bg-warning-bg" : "text-negative bg-negative-bg";
  return <span className={`text-xs font-semibold px-2 py-0.5 rounded ${color} tabular-nums`}>{s}</span>;
}

function ValuationBadge({ valuation }: { valuation: string | null }) {
  if (!valuation) return null;
  const styles: Record<string, string> = {
    Undervalued: "text-positive bg-positive-bg",
    "Fair Value": "text-warning bg-warning-bg",
    Overvalued: "text-negative bg-negative-bg",
  };
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded ${styles[valuation] || "text-txt-tertiary bg-surface-tertiary"}`}>
      {valuation}
    </span>
  );
}

function MetricCell({ label, value, fmt }: { label: string; value: number | null; fmt: "ratio" | "pct" }) {
  let display = "—";
  if (value !== null && value !== undefined) {
    display = fmt === "pct" ? `${value.toFixed(1)}%` : value.toFixed(2);
  }
  return (
    <div>
      <p className="text-xs text-txt-tertiary">{label}</p>
      <p className="text-sm text-txt-primary font-medium tabular-nums">{display}</p>
    </div>
  );
}
