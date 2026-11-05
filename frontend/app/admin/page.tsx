"use client";

import { useState } from "react";

type TradingOrder = {
  id: number; ticker: string; side: string; est_value: number; quantity: number; est_price: number;
  status: string; reason: string | null; block_reason: string | null; filled_qty: number | null;
  avg_fill_price: number | null; commission: number | null; limit_price: number | null;
};
type AuditCheck = { name: string; ok: boolean; severity: string; detail: string };
type TradingStatus = {
  mode: string; broker: string; approval: string; kill_switch: boolean; kill_reason: string | null;
  currency: string; pool: number; proceeds_usd: number; weekly_new_money: number; max_buys_per_week: number;
  run: null | { id: number; round_date: string; status: string; coverage: number | null; risk_off: boolean;
                budget_usd: number | null; allowance: number | null; drawn: number; note: string | null;
                orders: TradingOrder[] };
  audit: null | { id: number; kind: string; at: string | null; passed: boolean; critical_failures: number;
                  warnings: number; checks: AuditCheck[]; performance: Record<string, any> | null;
                  chain_head: string | null };
  events: { at: string | null; level: string; kind: string; message: string }[];
};

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function AdminPage() {
  const [key, setKey] = useState("");
  const [log, setLog] = useState<string[]>([]);
  const [ticker, setTicker] = useState("");
  const [trading, setTrading] = useState<TradingStatus | null>(null);

  const addLog = (msg: string) => setLog((prev) => [`[${new Date().toLocaleTimeString()}] ${msg}`, ...prev]);

  const adminFetch = async (path: string, method = "POST") => {
    const res = await fetch(`${API_URL}${path}`, {
      method,
      headers: { "X-Admin-Key": key },
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
  };

  const handleBatch = async () => {
    try {
      addLog("Starting batch analysis...");
      await adminFetch("/api/admin/batch/run");
      addLog("Batch started. Polling...");
      const poll = setInterval(async () => {
        try {
          const res = await fetch(`${API_URL}/api/batch/status`);
          const s = await res.json();
          addLog(`Batch: ${s.completed}/${s.total} (${s.current_ticker || "idle"}) ${s.failed} failed`);
          if (!s.running) {
            clearInterval(poll);
            addLog("Batch complete.");
          }
        } catch { /* ignore */ }
      }, 5000);
    } catch (e: any) {
      addLog(`Error: ${e.message}`);
    }
  };

  const handleMarketSummary = async () => {
    try {
      addLog("Generating market summary...");
      const data = await adminFetch("/api/admin/market-summary");
      addLog(`Market summary generated: "${data.summary.substring(0, 80)}..."`);
    } catch (e: any) {
      addLog(`Error: ${e.message}`);
    }
  };

  const handleAnalyze = async () => {
    if (!ticker.trim()) return;
    try {
      addLog(`Analyzing ${ticker.toUpperCase()}...`);
      const data = await adminFetch(`/api/admin/stock/${ticker.toUpperCase()}/analyze`);
      addLog(`${data.ticker}: ${data.valuation}, score ${data.overall_score}, fair value $${data.fair_value}`);
    } catch (e: any) {
      addLog(`Error: ${e.message}`);
    }
  };

  const handleRebalance = async () => {
    try {
      addLog("Rebalancing portfolio...");
      await adminFetch("/api/admin/portfolio/rebalance");
      addLog("Portfolio rebalanced.");
    } catch (e: any) {
      addLog(`Error: ${e.message}`);
    }
  };

  const loadTrading = async () => {
    try {
      setTrading(await adminFetch("/api/admin/trading", "GET"));
    } catch (e: any) {
      addLog(`Trading: ${e.message}`);
    }
  };

  const decideRun = async (runId: number, approve: boolean) => {
    if (!confirm(`${approve ? "Approve" : "Reject"} all proposed orders for run ${runId}?`)) return;
    try {
      const r = await adminFetch(`/api/admin/trading/runs/${runId}/${approve ? "approve" : "reject"}`);
      addLog(`Run ${r.run_id}: ${r.status}`);
      await loadTrading();
    } catch (e: any) {
      addLog(`Error: ${e.message}`);
    }
  };

  const toggleKill = async (on: boolean) => {
    const reason = prompt(on ? "Why are you halting trading?" : "Why is it safe to resume?") || "admin page";
    try {
      await adminFetch(`/api/admin/trading/kill?on=${on}&reason=${encodeURIComponent(reason)}`);
      addLog(`Kill switch ${on ? "ON" : "off"}`);
      await loadTrading();
    } catch (e: any) {
      addLog(`Error: ${e.message}`);
    }
  };

  const money = (v: number | null | undefined) =>
    v == null ? "—" : `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-200 p-8 font-mono">
      <h1 className="text-xl font-bold mb-6 text-white">NestLeap Admin</h1>

      <div className="mb-6">
        <label className="text-xs text-neutral-500 block mb-1">Admin Key</label>
        <input
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="Enter admin key..."
          className="bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm w-72 focus:outline-none focus:border-blue-500"
        />
      </div>

      <div className="flex flex-wrap gap-3 mb-6">
        <button onClick={handleBatch} className="bg-blue-600 hover:bg-blue-500 text-white text-sm px-4 py-2 rounded transition">
          Run Batch Analysis
        </button>
        <button onClick={handleMarketSummary} className="bg-blue-600 hover:bg-blue-500 text-white text-sm px-4 py-2 rounded transition">
          Refresh Market Summary
        </button>
        <button onClick={handleRebalance} className="bg-purple-600 hover:bg-purple-500 text-white text-sm px-4 py-2 rounded transition">
          Rebalance Portfolio
        </button>
      </div>

      <div className="flex gap-2 mb-8">
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          placeholder="TICKER"
          maxLength={6}
          className="bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm w-28 focus:outline-none focus:border-blue-500"
        />
        <button onClick={handleAnalyze} className="bg-green-700 hover:bg-green-600 text-white text-sm px-4 py-2 rounded transition">
          Analyze Stock
        </button>
      </div>

      <div className="mb-8">
        <div className="flex items-center gap-3 mb-3">
          <h2 className="text-xs text-neutral-500 uppercase tracking-wider">Broker trading</h2>
          <button onClick={loadTrading} className="bg-neutral-800 hover:bg-neutral-700 text-white text-xs px-3 py-1 rounded transition">
            {trading ? "Refresh" : "Load"}
          </button>
        </div>
        {trading && (
          <div className="bg-neutral-900 border border-neutral-800 rounded p-4 text-xs space-y-4">
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-neutral-400">
              <span>mode <b className={trading.mode === "live" ? "text-red-400" : "text-white"}>{trading.mode}</b></span>
              <span>broker <b className="text-white">{trading.broker}</b></span>
              <span>approval <b className="text-white">{trading.approval}</b></span>
              <span>pool <b className="text-white">{trading.currency} {trading.pool.toLocaleString(undefined, { maximumFractionDigits: 2 })}</b></span>
              <span>sale proceeds <b className="text-white">{money(trading.proceeds_usd)}</b></span>
              <span>new money/week <b className="text-white">max {trading.currency} {trading.weekly_new_money}, {trading.max_buys_per_week} buys</b></span>
              <span>
                kill switch{" "}
                <b className={trading.kill_switch ? "text-red-400" : "text-green-400"}>{trading.kill_switch ? "ON" : "off"}</b>
                {trading.kill_reason && trading.kill_switch && <span className="text-neutral-500"> ({trading.kill_reason})</span>}
              </span>
              <button
                onClick={() => toggleKill(!trading.kill_switch)}
                className={`${trading.kill_switch ? "bg-green-800 hover:bg-green-700" : "bg-red-800 hover:bg-red-700"} text-white px-2 py-0.5 rounded`}
              >
                {trading.kill_switch ? "Resume trading" : "Halt trading"}
              </button>
            </div>

            {!trading.run && <p className="text-neutral-600">No trading runs yet.</p>}
            {trading.run && (
              <div>
                <p className="text-neutral-300 mb-2">
                  Run {trading.run.id} · analyses of {trading.run.round_date} ·{" "}
                  <b className="text-white">{trading.run.status}</b>
                  {trading.run.risk_off && <span className="text-amber-400"> · RISK-OFF (holding cash)</span>}
                  {trading.run.coverage != null && <span className="text-neutral-500"> · coverage {(trading.run.coverage * 100).toFixed(0)}%</span>}
                  {trading.run.budget_usd != null && <span className="text-neutral-500"> · budget {money(trading.run.budget_usd)}</span>}
                  {trading.run.allowance != null && (
                    <span className="text-neutral-500"> · new money drawn {trading.currency} {trading.run.drawn.toFixed(2)} of {trading.run.allowance.toFixed(2)}</span>
                  )}
                  {trading.run.note && <span className="text-neutral-500"> · {trading.run.note}</span>}
                </p>
                <table className="w-full text-left">
                  <thead className="text-neutral-500">
                    <tr><th>side</th><th>ticker</th><th>value</th><th>status</th><th>fill</th><th>reason</th></tr>
                  </thead>
                  <tbody>
                    {trading.run.orders.map((o) => (
                      <tr key={o.id} className="border-t border-neutral-800 align-top">
                        <td className={o.side === "buy" ? "text-green-400" : "text-red-400"}>{o.side.toUpperCase()}</td>
                        <td className="text-white">{o.ticker}</td>
                        <td>{money(o.est_value)}</td>
                        <td>{o.status}{o.block_reason && <span className="text-amber-400"> — {o.block_reason}</span>}</td>
                        <td>{o.filled_qty ? `${o.filled_qty.toFixed(4)} @ ${money(o.avg_fill_price)} (fee ${money(o.commission)})` : "—"}</td>
                        <td className="text-neutral-500">{o.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {trading.run.status === "awaiting_approval" && (
                  <div className="flex gap-2 mt-3">
                    <button onClick={() => decideRun(trading.run!.id, true)} className="bg-green-700 hover:bg-green-600 text-white px-4 py-1.5 rounded">
                      Approve week
                    </button>
                    <button onClick={() => decideRun(trading.run!.id, false)} className="bg-neutral-700 hover:bg-neutral-600 text-white px-4 py-1.5 rounded">
                      Reject week
                    </button>
                  </div>
                )}
              </div>
            )}

            {trading.audit && (
              <div>
                <p className="text-neutral-300 mb-1">
                  Audit #{trading.audit.id} ({trading.audit.kind}) · {trading.audit.at?.replace("T", " ").slice(0, 16)} ·{" "}
                  <b className={trading.audit.passed ? "text-green-400" : "text-red-400"}>{trading.audit.passed ? "PASSED" : "FAILED"}</b>
                  {trading.audit.warnings > 0 && <span className="text-amber-400"> · {trading.audit.warnings} warnings</span>}
                </p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
                  {trading.audit.checks.map((c) => (
                    <p key={c.name} className={c.ok ? "text-neutral-400" : c.severity === "critical" ? "text-red-400" : "text-amber-400"}>
                      {c.ok ? "✓" : "✗"} {c.name} <span className="text-neutral-600">— {c.detail}</span>
                    </p>
                  ))}
                </div>
                {trading.audit.performance && !trading.audit.performance.error && (
                  <p className="text-neutral-300 mt-2">
                    Value {trading.audit.performance.currency} {trading.audit.performance.nav?.toLocaleString()} on{" "}
                    {trading.audit.performance.deposited?.toLocaleString()} deposited ({trading.audit.performance.new_money_invested?.toLocaleString()} invested) ·
                    SPY with the same deposits {trading.audit.performance.spy_same_deposits_nav?.toLocaleString()} ·
                    fees {money(trading.audit.performance.fees_usd)} + FX {trading.audit.performance.fx_fees}
                  </p>
                )}
                <p className="text-neutral-600 mt-1">chain head {trading.audit.chain_head?.slice(0, 16)}… (also in the audit notification)</p>
              </div>
            )}

            <div>
              <p className="text-neutral-500 mb-1">Recent events</p>
              <div className="max-h-48 overflow-y-auto space-y-1">
                {trading.events.map((e, i) => (
                  <p key={i} className={e.level === "error" ? "text-red-400" : e.level === "warning" ? "text-amber-400" : "text-neutral-400"}>
                    {e.at?.replace("T", " ").slice(0, 16)} [{e.kind}] {e.message}
                  </p>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      <div>
        <h2 className="text-xs text-neutral-500 uppercase tracking-wider mb-2">Log</h2>
        <div className="bg-neutral-900 border border-neutral-800 rounded p-4 h-96 overflow-y-auto text-xs space-y-1">
          {log.length === 0 && <p className="text-neutral-600">No activity yet.</p>}
          {log.map((l, i) => (
            <p key={i} className="text-neutral-400">{l}</p>
          ))}
        </div>
      </div>
    </div>
  );
}
