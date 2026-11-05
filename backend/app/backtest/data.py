"""Data loading for backtests: stored analyses (SQLite snapshot) and cached price history."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..analysis.strategy import Signal, build_rounds

CACHE_DIR = Path(__file__).resolve().parents[3] / "backtest_data" / "cache"


def load_rounds(db_path: str | Path) -> list[tuple[object, dict[str, Signal]]]:
    """All analysis rounds from a NestLeap database file (read-only)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = con.execute(
        "select ticker, analyzed_at, current_price, fair_value, valuation, overall_score, conviction "
        "from stock_analyses order by analyzed_at, id"
    ).fetchall()
    con.close()
    parsed = [(t, datetime.fromisoformat(a), p, fv, v, s, c) for t, a, p, fv, v, s, c in rows]
    return build_rounds(parsed)


def load_snapshots(db_path: str | Path) -> pd.DataFrame:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    df = pd.read_sql(
        "select id, date, total_value, cash, total_invested, sp500_value, num_holdings "
        "from portfolio_snapshots order by id",
        con,
    )
    con.close()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def load_latest_signals(db_path: str | Path) -> pd.DataFrame:
    """Latest valid analysis per ticker (for calibrating synthetic signals)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    df = pd.read_sql(
        "select ticker, date(analyzed_at) d, current_price price, fair_value fv, overall_score score, "
        "conviction, sector from stock_analyses where fair_value > 0 order by analyzed_at",
        con,
    )
    con.close()
    return df


def daily_closes(
    tickers: list[str], start: str, end: str | None = None, adjusted: bool = True
) -> pd.DataFrame:
    """Daily closes (columns = tickers), cached on disk. `adjusted` includes dividends/splits."""
    import yfinance as yf

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{sorted(tickers)}|{start}|{end}|{adjusted}".encode()).hexdigest()[:16]
    path = CACHE_DIR / f"closes_{key}.pkl"
    if path.exists():
        return pd.read_pickle(path)

    data = yf.download(
        sorted(set(tickers)), start=start, end=end, auto_adjust=adjusted,
        progress=False, threads=True, group_by="column",
    )
    closes = data["Close"]
    if isinstance(closes, pd.Series):
        closes = closes.to_frame(tickers[0])
    closes.index = pd.to_datetime(closes.index).tz_localize(None)
    closes = closes.sort_index().dropna(axis=1, how="all")
    if closes.empty:
        raise RuntimeError(f"No price data downloaded for {len(tickers)} tickers from {start}")
    closes.to_pickle(path)
    return closes
