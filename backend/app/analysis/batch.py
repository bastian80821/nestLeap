"""Batch analysis: stock universe + bulk runner."""

import concurrent.futures
import logging
import threading
import time

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import UserTicker
from .analyzer import analyze_stock, get_latest_analysis
from .metrics import InsufficientDataError

logger = logging.getLogger(__name__)

TOP_200_TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK-B", "TSM", "LLY",
    "AVGO", "JPM", "TSLA", "WMT", "UNH", "V", "XOM", "MA", "ORCL", "COST",
    "PG", "JNJ", "HD", "NFLX", "ABBV", "BAC", "CRM", "CVX", "MRK", "KO",
    "AMD", "TMUS", "PEP", "TMO", "CSCO", "LIN", "ACN", "WFC", "MCD", "ABT",
    "IBM", "PM", "GE", "ISRG", "NOW", "INTU", "CAT", "GS", "DIS", "QCOM",
    "VZ", "BKNG", "TXN", "AXP", "MS", "UBER", "BLK", "PFE", "RTX", "LOW",
    "SPGI", "AMGN", "HON", "NEE", "UNP", "DE", "T", "PLD", "AMAT", "BA",
    "COP", "SYK", "SCHW", "ELV", "TJX", "CB", "MDLZ", "BMY", "ADI", "LMT",
    "GILD", "ADP", "VRTX", "MMC", "SBUX", "FI", "SLB", "PGR", "MO",
    "SO", "CI", "DUK", "CME", "ICE", "CL", "BDX", "EOG", "REGN", "ITW",
    "MCK", "APD", "PYPL", "NOC", "SNPS", "CDNS", "WM", "CSX", "EMR", "USB",
    "PNC", "ORLY", "TGT", "MMM", "CARR", "GD", "AJG", "PSA", "HCA", "ROP",
    "FCX", "NSC", "NXPI", "WELL", "ECL", "GM", "SRE", "PCAR", "DHR",
    "AEP", "TFC", "F", "AIG", "MPC", "MCHP", "OKE", "AFL", "AZO", "FDX",
    "SPG", "HLT", "KMI", "PSX", "D", "TRV", "FTNT", "ROST", "PAYX",
    "O", "ALL", "TEL", "FAST", "CCI", "CMI", "CTAS", "MSCI", "AMP",
    "KHC", "MNST", "IDXX", "DXCM", "WEC", "EW", "HES", "VLO",
    "PRU", "GIS", "KR", "HPQ", "EA", "DD", "CTSH", "XEL", "GLW",
    "YUM", "EXC", "VRSK", "ED", "WBD", "GEHC", "BIIB", "TTWO", "DVN",
    "AWK", "BKR", "MTD", "ROK", "WAB", "CPAY", "FANG", "KEYS",
    "STT", "DAL", "ETR", "RMD", "ZBH", "CDW", "ACGL", "DOV",
    "FTV", "GPC", "PPG", "TROW", "WTW", "CHD", "ULTA", "NUE",
]

_batch_status = {
    "running": False,
    "total": 0,
    "completed": 0,
    "failed": 0,
    "failures": [],
    "current_ticker": None,
}
_batch_lock = threading.Lock()


def is_in_universe(ticker: str) -> bool:
    """Check if a ticker is in the batch universe (hardcoded or user-added)."""
    t = ticker.upper()
    if t in {x.upper() for x in TOP_200_TICKERS}:
        return True
    try:
        db = SessionLocal()
        exists = db.query(UserTicker).filter(UserTicker.ticker == t).first() is not None
        db.close()
        return exists
    except Exception:
        return False


def add_to_universe(ticker: str):
    """Add a user-discovered ticker to the persistent universe."""
    t = ticker.upper()
    if t in {x.upper() for x in TOP_200_TICKERS}:
        return
    try:
        db = SessionLocal()
        existing = db.query(UserTicker).filter(UserTicker.ticker == t).first()
        if not existing:
            db.add(UserTicker(ticker=t))
            db.commit()
            logger.info(f"Added {t} to user ticker universe")
        db.close()
    except Exception:
        pass


def get_batch_status() -> dict:
    with _batch_lock:
        return dict(_batch_status)


def _get_full_ticker_list() -> list[str]:
    """Merge hardcoded tickers with user-added ones from the DB."""
    base = list(TOP_200_TICKERS)
    base_set = {t.upper() for t in base}
    try:
        db = SessionLocal()
        user_tickers = db.query(UserTicker.ticker).all()
        db.close()
        for (t,) in user_tickers:
            if t.upper() not in base_set:
                base.append(t.upper())
                base_set.add(t.upper())
    except Exception:
        pass
    return base


def start_batch(tickers: list[str] | None = None):
    """Start batch analysis in a background thread."""
    with _batch_lock:
        if _batch_status["running"]:
            return False
        _batch_status["running"] = True

    target = tickers or _get_full_ticker_list()
    thread = threading.Thread(target=_run_batch, args=(target,), daemon=True)
    thread.start()
    return True


def _run_batch(tickers: list[str]):
    with _batch_lock:
        _batch_status["total"] = len(tickers)
        _batch_status["completed"] = 0
        _batch_status["failed"] = 0
        _batch_status["failures"] = []
        _batch_status["current_ticker"] = None

    db = SessionLocal()
    try:
        for ticker in tickers:
            with _batch_lock:
                _batch_status["current_ticker"] = ticker

            existing = get_latest_analysis(ticker, db, max_age_days=1)
            if existing and existing.valuation is not None:
                logger.info(f"Skipping {ticker} — recent complete analysis exists")
                with _batch_lock:
                    _batch_status["completed"] += 1
                continue

            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(analyze_stock, ticker, db)
                    future.result(timeout=90)
                logger.info(f"Analyzed {ticker}")
                with _batch_lock:
                    _batch_status["completed"] += 1
            except concurrent.futures.TimeoutError:
                logger.error(f"Timeout analyzing {ticker} (>90s)")
                with _batch_lock:
                    _batch_status["failed"] += 1
                    _batch_status["failures"].append(ticker)
            except InsufficientDataError as e:
                logger.warning(f"Skipping {ticker}: {e}")
                with _batch_lock:
                    _batch_status["completed"] += 1
            except Exception as e:
                logger.error(f"Failed to analyze {ticker}: {e}")
                with _batch_lock:
                    _batch_status["failed"] += 1
                    _batch_status["failures"].append(ticker)

            time.sleep(1)
    finally:
        db.close()
        with _batch_lock:
            _batch_status["running"] = False
            _batch_status["current_ticker"] = None

    from .portfolio import rebalance_portfolio
    try:
        rebalance_db = SessionLocal()
        rebalance_portfolio(rebalance_db)
        rebalance_db.close()
        logger.info("Portfolio rebalanced after batch")
    except Exception as e:
        logger.error(f"Portfolio rebalance failed: {e}")
