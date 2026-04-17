"use client";

import { useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function AdminPage() {
  const [key, setKey] = useState("");
  const [log, setLog] = useState<string[]>([]);
  const [ticker, setTicker] = useState("");

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
