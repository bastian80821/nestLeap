import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session

from .analysis.analyzer import analyze_stock, get_latest_analysis
from .analysis.batch import add_to_universe, get_batch_status, is_in_universe, start_batch
from .analysis.market_summary import generate_market_summary, get_or_generate_summary
from .analysis.metrics import InsufficientDataError
from .analysis.portfolio import get_portfolio_history, get_portfolio_state, rebalance_portfolio
from .config import settings
from .database import Base, engine, get_db
from .models import ApiCallLog, StockAnalysis
from .schemas import (
    AiMarketSummary,
    BatchStatusResponse,
    DashboardOpportunity,
    DashboardResponse,
    HealthResponse,
    MarketSummary,
    PortfolioHistoryPoint,
    PortfolioResponse,
    StockAnalysisResponse,
    StockSearchResult,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")
    yield


app = FastAPI(title="NestLeap", version="2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_admin(x_admin_key: str = Header(None)):
    if x_admin_key != settings.admin_key:
        raise HTTPException(403, "Invalid admin key")


def _latest_per_ticker(db: Session):
    subq = (
        db.query(
            StockAnalysis.ticker,
            func.max(StockAnalysis.id).label("max_id"),
        )
        .group_by(StockAnalysis.ticker)
        .subquery()
    )
    return db.query(StockAnalysis).join(subq, StockAnalysis.id == subq.c.max_id)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/api/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)):
    count = db.query(func.count(StockAnalysis.id)).scalar() or 0
    return HealthResponse(status="ok", analyzed_stocks=count)


# ── Dashboard ────────────────────────────────────────────────────────────────

@app.get("/api/dashboard", response_model=DashboardResponse)
def dashboard(db: Session = Depends(get_db)):
    results = _latest_per_ticker(db).all()

    undervalued = [r for r in results if r.valuation == "Undervalued"]
    fair = [r for r in results if r.valuation == "Fair Value"]
    overvalued = [r for r in results if r.valuation == "Overvalued"]

    scores = [r.overall_score for r in results if r.overall_score is not None]

    summary = MarketSummary(
        total_analyzed=len(results),
        undervalued_count=len(undervalued),
        fair_value_count=len(fair),
        overvalued_count=len(overvalued),
        avg_score=round(sum(scores) / len(scores), 1) if scores else None,
    )

    def _to_opportunity(r: StockAnalysis) -> DashboardOpportunity:
        upside = None
        if r.fair_value and r.current_price and r.current_price > 0:
            upside = round(((r.fair_value - r.current_price) / r.current_price) * 100, 1)
        return DashboardOpportunity(
            ticker=r.ticker,
            name=r.name,
            sector=r.sector,
            current_price=r.current_price,
            fair_value=r.fair_value,
            upside_pct=upside,
            overall_score=r.overall_score,
            valuation=r.valuation,
        )

    top_buys = sorted(undervalued, key=lambda r: r.overall_score or 0, reverse=True)[:10]
    urgent_sells = sorted(overvalued, key=lambda r: r.overall_score or 100)[:10]

    all_undervalued = sorted(undervalued, key=lambda r: r.overall_score or 0, reverse=True)
    all_fair_sorted = sorted(fair, key=lambda r: r.overall_score or 0, reverse=True)
    all_overvalued = sorted(overvalued, key=lambda r: r.overall_score or 100)

    return DashboardResponse(
        summary=summary,
        top_buys=[_to_opportunity(r) for r in top_buys],
        urgent_sells=[_to_opportunity(r) for r in urgent_sells],
        all_undervalued=[_to_opportunity(r) for r in all_undervalued],
        all_fair_value=[_to_opportunity(r) for r in all_fair_sorted],
        all_overvalued=[_to_opportunity(r) for r in all_overvalued],
    )


# ── AI Market Summary ─────────────────────────────────────────────────────────

@app.get("/api/market-summary", response_model=AiMarketSummary)
def market_summary_get():
    try:
        result = get_or_generate_summary()
        return AiMarketSummary(**result)
    except Exception as e:
        logger.error(f"Market summary failed: {e}")
        raise HTTPException(500, f"Market summary unavailable: {str(e)}")


# ── Stock analysis (read-only for public) ────────────────────────────────────

@app.get("/api/stock/{ticker}", response_model=StockAnalysisResponse)
def get_stock(ticker: str, db: Session = Depends(get_db)):
    analysis = get_latest_analysis(ticker, db)
    if not analysis:
        raise HTTPException(404, f"No recent analysis for {ticker.upper()}")
    return analysis


@app.get("/api/stock/{ticker}/in-universe")
def check_universe(ticker: str):
    return {"in_universe": is_in_universe(ticker.upper().strip())}


@app.get("/api/stocks/analyzed", response_model=list[StockSearchResult])
def list_analyzed(db: Session = Depends(get_db)):
    results = _latest_per_ticker(db).order_by(StockAnalysis.overall_score.desc()).all()
    return [
        StockSearchResult(
            ticker=r.ticker,
            name=r.name or r.ticker,
            sector=r.sector,
            current_price=r.current_price,
            overall_score=r.overall_score,
            valuation=r.valuation,
            analyzed_at=r.analyzed_at,
        )
        for r in results
    ]


@app.get("/api/batch/status", response_model=BatchStatusResponse)
def batch_status():
    return BatchStatusResponse(**get_batch_status())


# ── Portfolio ────────────────────────────────────────────────────────────────

@app.get("/api/portfolio", response_model=PortfolioResponse)
def portfolio(db: Session = Depends(get_db)):
    return PortfolioResponse(**get_portfolio_state(db))


@app.get("/api/portfolio/history", response_model=list[PortfolioHistoryPoint])
def portfolio_history(db: Session = Depends(get_db)):
    return [PortfolioHistoryPoint(**p) for p in get_portfolio_history(db)]


# ── Stats ────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    total_analyses = db.query(func.count(StockAnalysis.id)).scalar() or 0
    unique_tickers = db.query(func.count(func.distinct(StockAnalysis.ticker))).scalar() or 0
    total_api_calls = db.query(func.count(ApiCallLog.id)).scalar() or 0
    return {
        "total_analyses": total_analyses,
        "unique_tickers": unique_tickers,
        "total_gemini_calls": total_api_calls,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN ENDPOINTS (require X-Admin-Key header)
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/admin/batch/run", dependencies=[Depends(_require_admin)])
def admin_run_batch():
    started = start_batch()
    if not started:
        raise HTTPException(409, "Batch analysis already running")
    return {"status": "started"}


@app.post("/api/admin/market-summary", response_model=AiMarketSummary, dependencies=[Depends(_require_admin)])
def admin_refresh_market_summary():
    try:
        result = generate_market_summary()
        return AiMarketSummary(**result)
    except Exception as e:
        logger.error(f"Market summary generation failed: {e}")
        raise HTTPException(500, f"Market summary failed: {str(e)}")


@app.post("/api/admin/stock/{ticker}/analyze", response_model=StockAnalysisResponse, dependencies=[Depends(_require_admin)])
def admin_analyze_stock(ticker: str, db: Session = Depends(get_db)):
    ticker = ticker.upper().strip()
    if not all(c.isalpha() or c in ".-" for c in ticker) or len(ticker) > 6:
        raise HTTPException(400, "Invalid ticker format")
    try:
        result = analyze_stock(ticker, db)
        add_to_universe(ticker)
        return result
    except InsufficientDataError as e:
        raise HTTPException(422, str(e))
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Analysis failed for {ticker}: {e}")
        raise HTTPException(500, f"Analysis failed: {str(e)}")


@app.post("/api/admin/portfolio/rebalance", dependencies=[Depends(_require_admin)])
def admin_rebalance(db: Session = Depends(get_db)):
    try:
        rebalance_portfolio(db)
        return {"status": "rebalanced"}
    except Exception as e:
        logger.error(f"Rebalance failed: {e}")
        raise HTTPException(500, f"Rebalance failed: {str(e)}")
