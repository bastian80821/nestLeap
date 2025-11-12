from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from .database import get_db, engine, SessionLocal
from .models import Base, MarketArticle, MarketNewsSummary, EconomicIndicator, EconomicEvent, FundamentalsAnalysis
from .config import settings
from .services.stock_screener import StockScreener
from .services.market_sentiment_collector import market_sentiment_collector, MarketSentimentCollector
from .services.historical_market_collector import historical_collector
from .services.llm_sentiment_analyzer import llm_sentiment_analyzer
from .services.simple_market_news import SimpleMarketNews
from .services.economic_fundamentals_collector import economic_fundamentals_collector
import asyncio
from typing import List, Dict, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta, date, timezone
from sqlalchemy import desc, and_
from loguru import logger
from contextlib import asynccontextmanager
from collections import defaultdict
from . import api
from .api import router as debug_router
from .auth import verify_admin_key

# ✅ RESTORED AGENT IMPORTS
from .agents.market_sentiment_agent import MarketSentimentAgent
from .agents.news_agent import NewsAgent
from .agents.stock_master_agent import StockMasterAgent
from .agents.stock_master_agent_v2 import StockMasterAgentV2
from .agents.news_history_agent import NewsHistoryAgent
from .models import (
    MarketSentiment, AgentFinding, AgentState, MarketSentimentAnalysis, 
    MarketArticle, EconomicIndicator, MarketIndicator
)

# Create database tables automatically (for fresh Railway deployment)
Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("🚀 Stock Platform API starting up...")
    
    # Start the 3-hour news processing scheduler
    async def scheduled_news_processor():
        """Background task that runs news processing every 3 hours"""
        while True:
            try:
                await asyncio.sleep(3 * 60 * 60)  # Wait 3 hours
                logger.info("🕐 Running scheduled 3-hour news processing cycle...")
                result = await market_news_service.scheduled_news_cycle(force=False)
                logger.info(f"✅ Scheduled news cycle completed: {result}")
            except Exception as e:
                logger.error(f"❌ Error in scheduled news processing: {e}")
                # Continue the loop even if there's an error
                continue
    
    # Start the daily fundamentals data collection scheduler
    async def scheduled_fundamentals_collector():
        """Background task that runs fundamentals data collection daily"""
        while True:
            try:
                await asyncio.sleep(24 * 60 * 60)  # Wait 24 hours
                logger.info("📊 Running scheduled daily fundamentals data collection...")
                result = await economic_fundamentals_collector.collect_latest_data()
                logger.info(f"✅ Scheduled fundamentals collection completed: {result}")
            except Exception as e:
                logger.error(f"❌ Error in scheduled fundamentals collection: {e}")
                # Continue the loop even if there's an error
                continue
    
    # Start the daily stock data collection and analysis scheduler
    async def scheduled_stock_updates():
        """Background task that runs stock data collection and analysis daily"""
        from .services.stock_data_collector import StockDataCollector
        from .agents.stock_master_agent_v2 import StockMasterAgentV2
        
        stock_collector = StockDataCollector()
        
        while True:
            try:
                # Run at 6 PM EST (after market close) - wait 24 hours between runs
                await asyncio.sleep(24 * 60 * 60)
                
                logger.info("📈 Running scheduled daily stock data collection...")
                
                # Collect data for all tracked stocks
                collection_result = await stock_collector.collect_daily_data_for_tracked_stocks()
                logger.info(f"✅ Stock data collection: {collection_result.get('successful', 0)}/{collection_result.get('total_stocks', 0)} stocks")
                
                # Run analysis for tracked stocks (with delay between each)
                if collection_result.get('successful', 0) > 0:
                    logger.info("🤖 Running stock analysis for tracked stocks...")
                    from .models import TrackedStock
                    
                    db = SessionLocal()
                    try:
                        tracked_stocks = db.query(TrackedStock).filter(
                            TrackedStock.is_active == True
                        ).order_by(TrackedStock.priority).limit(10).all()  # Limit to 10 per day for API quotas
                        
                        for stock in tracked_stocks:
                            try:
                                logger.info(f"  Analyzing {stock.ticker}...")
                                master_agent = StockMasterAgentV2(stock.ticker)
                                await master_agent.run_cycle()
                                
                                # Update tracked stock stats
                                stock.analysis_count += 1
                                stock.last_analysis_date = datetime.utcnow()
                                db.commit()
                                
                                # Delay to avoid rate limits
                                await asyncio.sleep(5)
                                
                            except Exception as e:
                                logger.error(f"  Error analyzing {stock.ticker}: {e}")
                                continue
                        
                        logger.info(f"✅ Stock analysis completed for {len(tracked_stocks)} stocks")
                        
                    finally:
                        db.close()
                
            except Exception as e:
                logger.error(f"❌ Error in scheduled stock updates: {e}")
                continue
    
    # Hourly opportunity scanner
    async def scheduled_opportunity_scanner():
        """Background task that scans for opportunities every hour"""
        from .services.opportunity_scanner import OpportunityScanner
        
        scanner = OpportunityScanner()
        
        # Initial delay to let application start up
        logger.info("📅 Opportunity scanner will run first scan in 5 minutes")
        await asyncio.sleep(300)  # 5 minute initial delay
        
        while True:
            try:
                logger.info("🔍 Starting hourly opportunity scan...")
                await scanner.scan_all_opportunities()
                
                # Sleep for 1 hour
                await asyncio.sleep(3600)
                
            except Exception as e:
                logger.error(f"❌ Error in scheduled opportunity scanner: {e}")
                await asyncio.sleep(3600)  # Try again in an hour
                continue
    
    # Start the background schedulers
    news_scheduler_task = asyncio.create_task(scheduled_news_processor())
    fundamentals_scheduler_task = asyncio.create_task(scheduled_fundamentals_collector())
    stock_scheduler_task = asyncio.create_task(scheduled_stock_updates())
    opportunity_scanner_task = asyncio.create_task(scheduled_opportunity_scanner())
    logger.info("📅 Started 3-hour news processing scheduler")
    logger.info("📅 Started daily fundamentals data collection scheduler")
    logger.info("📅 Started daily stock data collection and analysis scheduler")
    logger.info("📅 Started hourly opportunity scanner")
    
    yield
    
    # Shutdown
    print("📉 Stock Platform API shutting down...")
    # Cancel the background tasks
    news_scheduler_task.cancel()
    fundamentals_scheduler_task.cancel()
    stock_scheduler_task.cancel()
    opportunity_scanner_task.cancel()
    try:
        await news_scheduler_task
    except asyncio.CancelledError:
        logger.info("🛑 News scheduler task cancelled during shutdown")
    try:
        await fundamentals_scheduler_task
    except asyncio.CancelledError:
        logger.info("🛑 Fundamentals scheduler task cancelled during shutdown")
    try:
        await stock_scheduler_task
    except asyncio.CancelledError:
        logger.info("🛑 Stock scheduler task cancelled during shutdown")
    try:
        await opportunity_scanner_task
    except asyncio.CancelledError:
        logger.info("🛑 Opportunity scanner task cancelled during shutdown")

# Initialize FastAPI app
app = FastAPI(
    title="Stock Platform API",
    description="Advanced stock analysis and market intelligence platform",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Add CORS middleware with support for Vercel preview deployments
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",  # Allow all Vercel deployments
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
stock_screener = StockScreener()
market_news_service = SimpleMarketNews()

# Initialize market sentiment agent
market_sentiment_agent = MarketSentimentAgent()

# Pydantic models for API requests/responses
class StockSearchRequest(BaseModel):
    ticker: str

class RecommendationResponse(BaseModel):
    ticker: str
    action: str
    confidence_score: float
    reasoning: str
    key_factors: List[str]
    valuation_signal: float
    technical_signal: float
    news_sentiment_signal: float
    buy_range_low: Optional[float] = None
    buy_range_high: Optional[float] = None
    sell_range_low: Optional[float] = None
    sell_range_high: Optional[float] = None
    risk_level: str
    volatility_score: float
    created_at: datetime

class NewsArticleResponse(BaseModel):
    title: str
    summary: Optional[str]
    source: str
    sentiment_label: Optional[str]
    sentiment_score: Optional[float]
    impact_level: Optional[str]
    published_at: Optional[datetime]

class StockAnalysisResponse(BaseModel):
    ticker: str
    company_name: str
    current_price: Optional[float]
    market_cap: Optional[float]
    pe_ratio: Optional[float]
    quality_score: Optional[float]
    margin_of_safety: Optional[float]
    recommendation: Optional[RecommendationResponse]
    recent_news: List[NewsArticleResponse]

class NewsSentimentRequest(BaseModel):
    force_refresh: Optional[bool] = False
    sources: Optional[List[str]] = None  # ['alphavantage_news', 'general_news']

# API Routes

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": "Stock Platform API v2.0",
        "description": "Advanced market intelligence with LLM-powered sentiment analysis",
        "features": [
            "Historical market data collection",
            "LLM-based sentiment analysis", 
            "News sentiment analysis from multiple sources",
            "Real-time market indicators",
            "AI-enhanced market news"
        ],
        "endpoints": {
            "market_sentiment": "/api/market-sentiment",
            "sentiment_analysis": "/api/sentiment-analysis/latest",
            "market_data": "/api/market-data/historical",
            "market_data_collect": "/api/market-data/collect",
            "historical_backfill": "/api/market-data/backfill",
            "market_news": "/api/market-news",
            "health": "/health"
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "database": "connected",
            "market_data_collector": "active",
            "llm_analyzer": "configured" if llm_sentiment_analyzer.model else "not_configured"
        }
    }

@app.get("/api/stocks/trending")
async def get_trending_stocks():
    """Get trending stocks based on market activity."""
    try:
        trending_stocks = await stock_screener.get_trending_stocks()
        return {"stocks": trending_stocks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stocks/search")
async def search_stocks(query: str):
    """Search for stocks by symbol or company name."""
    try:
        results = await stock_screener.search_stocks(query)
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/market-news")
async def get_market_news(background_tasks: BackgroundTasks):
    """Get processed market news with AI summaries. Returns cached data from database."""
    try:
        # Query and return cached articles from database - no background processing
        db = SessionLocal()
        try:
            all_recent = db.query(MarketArticle).filter(
                MarketArticle.published_at >= datetime.now(timezone.utc) - timedelta(hours=24)
            ).order_by(desc(MarketArticle.published_at)).all()
            formatted = market_news_service._format_articles_for_frontend(all_recent)
            for a in formatted:
                a['relevance_score'] = market_news_service._relevance_score(a)
            def utc_ts(dt):
                if dt is None:
                    return 0
                if isinstance(dt, str):
                    try:
                        dt = datetime.fromisoformat(dt)
                    except Exception:
                        return 0
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            top = sorted(formatted, key=lambda x: (-x['relevance_score'], -utc_ts(x.get('published_at'))))[:10]
            top = sorted(top, key=lambda x: -utc_ts(x.get('published_at')))
        finally:
            db.close()
        
        # Get the most recent summary from database
        db = SessionLocal()
        try:
            latest_summary = db.query(MarketNewsSummary).order_by(MarketNewsSummary.created_at.desc()).first()
            news_summary = latest_summary.summary if latest_summary else None
        finally:
            db.close()
        
        # Calculate sentiment breakdown from articles
        sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
        for article in top:
            signal = article.get("market_signal", "neutral").lower()
            if signal in ["bullish", "positive"]:
                sentiment_counts["positive"] += 1
            elif signal in ["bearish", "negative"]:
                sentiment_counts["negative"] += 1
            else:
                sentiment_counts["neutral"] += 1
        
        return {
            "articles": top,
            "summary": news_summary or "No recent market news summary available.",
            "total_articles": len(top),
            "sentiment_breakdown": sentiment_counts,
            "agent_intelligence": {
                "has_ai_analysis": bool(news_summary),
                "last_updated": latest_summary.created_at.isoformat() if latest_summary else datetime.now(timezone.utc).isoformat(),
                "analysis_quality": "high" if len(top) >= 5 else "medium"
            },
            # Legacy fields for backwards compatibility
            "hours_lookback": 24,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "sources_covered": [s["name"] for s in market_news_service.news_sources],
            "cache_status": "fresh"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/market-news/enhanced")
async def get_market_news_enhanced():
    """Get enhanced market news with proper structure for frontend - returns cached data only"""
    try:
        # Get recent articles from database - no processing
        db = SessionLocal()
        try:
            all_recent = db.query(MarketArticle).filter(
                MarketArticle.published_at >= datetime.now(timezone.utc) - timedelta(hours=24)
            ).order_by(desc(MarketArticle.published_at)).limit(20).all()
            
            # Format articles for frontend
            formatted = market_news_service._format_articles_for_frontend(all_recent)
            for a in formatted:
                a['relevance_score'] = market_news_service._relevance_score(a)
                
            # Sort by relevance and recency, take top 10
            def utc_ts(dt):
                if dt is None:
                    return 0
                if isinstance(dt, str):
                    try:
                        dt = datetime.fromisoformat(dt)
                    except Exception:
                        return 0
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
                
            top_articles = sorted(formatted, key=lambda x: (-x['relevance_score'], -utc_ts(x.get('published_at'))))[:10]
            
            # Get latest news summary
            latest_summary = db.query(MarketNewsSummary).order_by(MarketNewsSummary.created_at.desc()).first()
            news_summary = latest_summary.summary if latest_summary else "No recent market news summary available."
            
        finally:
            db.close()
        
        # Calculate sentiment breakdown from articles
        sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
        for article in top_articles:
            signal = article.get("market_signal", "neutral").lower()
            if signal in ["bullish", "positive"]:
                sentiment_counts["positive"] += 1
            elif signal in ["bearish", "negative"]:
                sentiment_counts["negative"] += 1
            else:
                sentiment_counts["neutral"] += 1
        
        # Format articles with expected frontend structure
        formatted_articles = []
        for article in top_articles:
            # Clean up title - remove .html and improve formatting
            clean_title = article["title"]
            if clean_title.lower().endswith('.html'):
                clean_title = clean_title[:-5]  # Remove .html
            # Replace underscores with spaces and title case
            clean_title = clean_title.replace('_', ' ').replace('-', ' ')
            # Basic title case (capitalize first letter of each word)
            clean_title = ' '.join(word.capitalize() for word in clean_title.split())
            
            formatted_articles.append({
                "title": clean_title,
                "summary": article.get("brief_headline", clean_title),
                "source": article["source"],
                "published_at": article["published_at"],
                "url": article.get("url", ""),
                "market_signal": article.get("market_signal", "neutral"),
                "significance_score": article.get("confidence", 0.5),
                "sentiment_label": article.get("market_signal", "neutral"),
                "sentiment_score": article.get("confidence", 0.5),
                "key_points": article.get("bullet_points", []),
                "impact_level": "high" if article.get("confidence", 0.5) > 0.7 else "medium"
            })
        
        return {
            "articles": formatted_articles,
            "summary": news_summary,
            "total_articles": len(formatted_articles),
            "sentiment_breakdown": sentiment_counts,
            "agent_intelligence": {
                "has_ai_analysis": bool(latest_summary),
                "last_updated": latest_summary.created_at.isoformat() if latest_summary else datetime.now(timezone.utc).isoformat(),
                "analysis_quality": "high" if len(formatted_articles) >= 5 else "medium"
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting enhanced market news: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/market-news/refresh")
async def refresh_market_news(background_tasks: BackgroundTasks):
    """Refresh market news (legacy endpoint - processing now happens on 3-hour schedule)"""
    try:
        # Note: Actual processing now happens on 3-hour schedule or via force-refresh
        # This endpoint now just confirms the system is operational
        
        return {
            "status": "success",
            "message": "Market news system operational. Processing happens every 3 hours automatically or via force-refresh.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "note": "Use /api/market-news/force-refresh-summary for immediate processing"
        }
    except Exception as e:
        logger.error(f"Error in refresh endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/market-news/force-refresh-summary", dependencies=[Depends(verify_admin_key)])
async def force_refresh_news_summary():
    """Force refresh news summary (non-blocking)"""
    try:
        # Start background processing without waiting
        asyncio.create_task(market_news_service.scheduled_news_cycle(force=True))
        
        return {
            "status": "processing",
            "message": "News refresh started in background. Current news will remain visible while processing."
        }
        
    except Exception as e:
        logger.error(f"Error starting news refresh: {e}")
        return {
            "status": "error", 
            "message": f"Failed to start news refresh: {str(e)}"
        }

@app.post("/api/market-news/scheduled-cycle", dependencies=[Depends(verify_admin_key)])
async def trigger_scheduled_news_cycle():
    """Trigger the scheduled 3-hour news processing cycle"""
    try:
        result = await market_news_service.scheduled_news_cycle(force=False)
        
        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("error"))
            
        return result
        
    except Exception as e:
        logger.error(f"Error in scheduled news cycle: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/market-news/historical-context")
async def get_news_historical_context(days_back: int = 5):
    """Test endpoint to view historical context analysis"""
    try:
        history_agent = NewsHistoryAgent()
        context = await history_agent.generate_historical_context(days_back=days_back)
        
        return {
            "status": "success",
            "days_analyzed": days_back,
            **context
        }
        
    except Exception as e:
        logger.error(f"Error generating historical context: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/market-data/collect")
async def collect_market_data():
    """Collect current market indicator data including Fear & Greed Index."""
    try:
        # Collect traditional market indicators
        results = await historical_collector.collect_all_indicators()
        
        # Also collect Fear & Greed Index only (removing news sentiment)
        logger.info("Collecting Fear & Greed Index")
        fear_greed_data = await market_sentiment_collector.collect_fear_greed_index()
        
        # Count successful collections by checking if data has valid values
        successful = len([r for r in results if r and r.get('value') is not None])
        
        # Add Fear & Greed data to results if available
        if fear_greed_data:
            results.append({
                'indicator_type': 'fear_greed_index',
                'value': fear_greed_data['value'],
                'label': fear_greed_data['label'],
                'source': fear_greed_data['source'],
                'timestamp': fear_greed_data['timestamp']
            })
            successful += 1
        
        return {
            "message": "Market data and Fear & Greed Index collection completed",
            "indicators_collected": len(results),
            "successful_collections": successful,
            "fear_greed_index": fear_greed_data,
            "data": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/market-data/historical")
async def get_historical_data(days_back: int = 30):
    """Get historical market data for analysis."""
    try:
        if days_back < 1 or days_back > 90:
            raise HTTPException(status_code=400, detail="days_back must be between 1 and 90")
            
        data = await historical_collector.get_historical_data(days_back)
        
        return {
            "days_back": days_back,
            "indicators": list(data.keys()),
            "data": data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/market-data/backfill")
async def backfill_historical_data(days_back: int = 30, background_tasks: BackgroundTasks = None):
    """Backfill historical market data for the past N days."""
    try:
        if days_back < 1 or days_back > 90:
            raise HTTPException(status_code=400, detail="days_back must be between 1 and 90")
        
        if background_tasks:
            # Run backfill in background for large requests
            background_tasks.add_task(historical_collector.backfill_historical_data, days_back)
            return {
                "message": f"Historical backfill started for {days_back} days",
                "status": "background_task_started"
            }
        else:
            # Run synchronously for smaller requests
            result = await historical_collector.backfill_historical_data(days_back)
            return result
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/market-data/create-mock-data")
async def create_mock_historical_data(days_back: int = 30):
    """Create mock historical data for testing purposes."""
    try:
        if days_back < 1 or days_back > 90:
            raise HTTPException(status_code=400, detail="days_back must be between 1 and 90")
            
        mock_data = await historical_collector.create_mock_data(days_back)
        
        return {
            "message": f"Mock historical data created for {days_back} days",
            "mock_data": mock_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sentiment-analysis/generate")
async def generate_sentiment_analysis(days_back: int = 30):
    """Generate new LLM-based sentiment analysis."""
    try:
        if days_back < 1 or days_back > 90:
            raise HTTPException(status_code=400, detail="days_back must be between 1 and 90")
            
        analysis = await llm_sentiment_analyzer.generate_sentiment_analysis(days_back)
        
        if analysis:
            return {
                "message": "Sentiment analysis generated successfully",
                "analysis": analysis
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to generate sentiment analysis")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sentiment-analysis/latest")
async def get_latest_sentiment_analysis():
    """Get the most recent sentiment analysis."""
    try:
        analysis = await llm_sentiment_analyzer.get_latest_analysis()
        
        if analysis:
            return {"analysis": analysis}
        else:
            return {"analysis": None, "message": "No sentiment analysis available"}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/market-sentiment")
async def get_market_sentiment():
    """Get current market sentiment (combines latest data + LLM analysis) - NO NEWS SENTIMENT."""
    try:
        # Get latest sentiment analysis
        analysis = await llm_sentiment_analyzer.get_latest_analysis()
        
        # Get FRESH current market indicators (not historical time series)
        logger.info("Collecting fresh current market indicators for market sentiment endpoint")
        current_indicators = {}
        
        # Collect fresh data for each indicator (same as market-data/collect does)
        indicators_config = {
            'sp500': '^GSPC',
            'dow': '^DJI', 
            'nasdaq': '^IXIC',
            'vix': '^VIX',
            'treasury_10y': '^TNX',
            'dxy': 'DX-Y.NYB'
        }
        
        for indicator_type, symbol in indicators_config.items():
            try:
                indicator_data = await historical_collector.collect_indicator_data(indicator_type, symbol)
                if indicator_data:
                    current_indicators[indicator_type] = {
                        'value': indicator_data['value'],
                        'change_pct': indicator_data['change_pct'],
                        'data_source': indicator_data['data_source']
                    }
                    logger.info(f"Fresh {indicator_type}: {indicator_data['value']:.2f} ({indicator_data['change_pct']:+.2f}%)")
                else:
                    logger.warning(f"Failed to get fresh data for {indicator_type}")
            except Exception as e:
                logger.error(f"Error collecting fresh {indicator_type} data: {e}")
        
        # Get current Fear & Greed Index ONLY (no news sentiment)
        fear_greed_data = await market_sentiment_collector.collect_fear_greed_index()
        if fear_greed_data:
            current_indicators['fear_greed_index'] = fear_greed_data
        
        # Combine analysis with current data
        response = {
            "sentiment_analysis": analysis,
            "current_indicators": current_indicators,
            "data_timestamp": datetime.utcnow().isoformat(),
            "market_session": "regular" if historical_collector.is_market_open() else "closed"
        }
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/fear-greed-index")
async def get_fear_greed_index():
    """Get current Fear & Greed Index."""
    try:
        fear_greed_data = await market_sentiment_collector.collect_fear_greed_index()
        
        if fear_greed_data:
            return {
                "fear_greed_index": fear_greed_data,
                "interpretation": {
                    "0-25": "Extreme Fear",
                    "25-45": "Fear", 
                    "45-55": "Neutral",
                    "55-75": "Greed",
                    "75-100": "Extreme Greed"
                }
            }
        else:
            return {
                "fear_greed_index": None,
                "message": "Fear & Greed Index not available"
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Economic Fundamentals endpoints
@app.get("/api/fundamentals")
async def get_fundamentals_data():
    """Get current economic fundamentals data with LLM analysis."""
    try:
        db = SessionLocal()
        try:
            # Get latest indicators by category
            categories = ['inflation', 'employment', 'interest_rates', 'gdp', 'consumer', 'manufacturing', 'home_prices']
            fundamentals_data = {}
            
            for category in categories:
                # Get the most recent indicators for each indicator_name in this category
                indicators = db.query(EconomicIndicator).filter(
                    EconomicIndicator.category == category
                ).order_by(
                    EconomicIndicator.indicator_name,
                    EconomicIndicator.reference_date.desc()
                ).all()
                # Group by indicator_name, take up to 5 most recent for each
                grouped = defaultdict(list)
                for ind in indicators:
                    grouped[ind.indicator_name].append(ind)
                recent_indicators = []
                for inds in grouped.values():
                    recent_indicators.extend(inds[:5])
                # Sort by reference_date descending
                recent_indicators = sorted(recent_indicators, key=lambda x: x.reference_date, reverse=True)
                fundamentals_data[category] = [
                    {
                        'indicator_name': ind.indicator_name,
                        'value': ind.value,
                        'unit': ind.unit,
                        'reference_date': ind.reference_date.isoformat(),
                        'previous_value': ind.previous_value,
                        'period_type': ind.period_type,
                        'source': ind.source
                    }
                    for ind in recent_indicators
                ]
            
            # Get latest fundamentals analysis
            latest_analysis = db.query(FundamentalsAnalysis).order_by(
                FundamentalsAnalysis.analysis_date.desc()
            ).first()
            
            analysis_data = None
            if latest_analysis:
                analysis_data = {
                    'overall_assessment': latest_analysis.overall_assessment,
                    'economic_cycle_stage': latest_analysis.economic_cycle_stage,
                    'inflation_outlook': latest_analysis.inflation_outlook,
                    'employment_outlook': latest_analysis.employment_outlook,
                    'monetary_policy_stance': latest_analysis.monetary_policy_stance,
                    'key_insights': latest_analysis.key_insights,
                    'market_implications': latest_analysis.market_implications,
                    'sector_impacts': latest_analysis.sector_impacts,
                    'risk_factors': latest_analysis.risk_factors,
                    'confidence_level': latest_analysis.confidence_level,
                    'analysis_date': latest_analysis.analysis_date.isoformat(),
                    'explanation': latest_analysis.explanation
                }
            
            return {
                'fundamentals_data': fundamentals_data,
                'analysis': analysis_data,
                "data_timestamp": datetime.utcnow().isoformat(),
                'categories': categories
            }
            
        finally:
            db.close()
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/fundamentals/collect")
async def collect_fundamentals_data(background_tasks: BackgroundTasks):
    """Collect fresh economic fundamentals data (incremental - only new dates)."""
    try:
        # Start incremental collection in background
        background_tasks.add_task(economic_fundamentals_collector.collect_latest_data)
        
        return {
            "message": "Incremental economic fundamentals data collection started",
            "description": "Only new data points will be added, existing dates will be skipped",
            "status": "background_task_started",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/fundamentals/backfill")
async def backfill_fundamentals_data(days_back: int = 730, background_tasks: BackgroundTasks = None):
    """Backfill historical economic fundamentals data."""
    try:
        if days_back < 30 or days_back > 3650:
            raise HTTPException(status_code=400, detail="days_back must be between 30 and 3650 (10 years)")
        
        if background_tasks:
            # Run backfill in background for large requests
            background_tasks.add_task(economic_fundamentals_collector.backfill_historical_data, days_back)
            return {
                "message": f"Historical economic data backfill started for {days_back} days",
                "description": "This will collect full time series data from FRED API",
                "status": "background_task_started",
                "days_back": days_back,
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            # Run synchronously for smaller requests
            result = await economic_fundamentals_collector.backfill_historical_data(days_back)
            return result
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/fundamentals/analyze")
async def generate_fundamentals_analysis():
    """Generate new LLM analysis of economic fundamentals."""
    try:
        analysis = await economic_fundamentals_collector.generate_fundamentals_analysis()
        
        if analysis:
            # Store the analysis
            stored = await economic_fundamentals_collector._store_analysis(analysis)
            return {
                "message": "Fundamentals analysis generated successfully",
                "analysis": analysis,
                "stored": stored
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to generate fundamentals analysis")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/fundamentals/events")
async def get_upcoming_economic_events():
    """Get upcoming economic events and data releases."""
    try:
        db = SessionLocal()
        try:
            # Get upcoming events in the next 30 days
            start_date = datetime.utcnow()
            end_date = start_date + timedelta(days=30)
            
            upcoming_events = db.query(EconomicEvent).filter(
                and_(
                    EconomicEvent.scheduled_date >= start_date,
                    EconomicEvent.scheduled_date <= end_date
                )
            ).order_by(EconomicEvent.scheduled_date).all()
            
            events_data = [
                {
                    'event_name': event.event_name,
                    'category': event.category,
                    'scheduled_date': event.scheduled_date.isoformat(),
                    'importance': event.importance,
                    'previous_value': event.previous_value,
                    'forecast_value': event.forecast_value,
                    'actual_value': event.actual_value,
                    'impact_description': event.impact_description,
                    'is_released': event.is_released
                }
                for event in upcoming_events
            ]
            
            return {
                'upcoming_events': events_data,
                'period_start': start_date.isoformat(),
                'period_end': end_date.isoformat(),
                'total_events': len(events_data)
            }
            
        finally:
            db.close()
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/fundamentals/stats")
async def get_fundamentals_stats():
    """Get statistics about economic fundamentals data coverage."""
    try:
        db = SessionLocal()
        try:
            total_indicators = db.query(EconomicIndicator).count()
            latest_update = db.query(EconomicIndicator).order_by(
                EconomicIndicator.reference_date.desc()
            ).first()
            
            categories = db.query(EconomicIndicator.category).distinct().all()
            category_counts = {}
            for cat in categories:
                if cat[0]:  # Skip None categories
                    count = db.query(EconomicIndicator).filter(
                        EconomicIndicator.category == cat[0]
                    ).count()
                    category_counts[cat[0]] = count
            
            return {
                "total_indicators": total_indicators,
                "latest_update": latest_update.reference_date.isoformat() if latest_update else None,
                "categories": category_counts,
                "coverage_period": {
                    "start": "2000-01-01",  # Approximate start of FRED data
                    "end": datetime.utcnow().date().isoformat()
                }
            }
            
        finally:
            db.close()
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/fundamentals/enhanced")
async def get_enhanced_fundamentals_data():
    """Get enhanced fundamentals data with agent analysis for frontend"""
    try:
        db = SessionLocal()
        try:
            # Use the 8 key indicators we carefully designed
            key_indicators = [
                'gdp_yoy_growth_bea',
                'cpi_yoy_inflation', 
                'fed_funds_rate',
                'unemployment_rate',
                'retail_sales',
                'industrial_production',
                'home_price_index',
                'treasury_10y_yield'
            ]
            
            indicators_data = []
            
            for indicator_name in key_indicators:
                # Get latest indicator with historical data for trend calculation
                latest_indicator = db.query(EconomicIndicator).filter(
                    EconomicIndicator.indicator_name == indicator_name
                ).order_by(EconomicIndicator.reference_date.desc()).first()
                
                if latest_indicator:
                    # Get previous period for change calculation
                    previous_indicator = db.query(EconomicIndicator).filter(
                        EconomicIndicator.indicator_name == indicator_name,
                        EconomicIndicator.reference_date < latest_indicator.reference_date
                    ).order_by(EconomicIndicator.reference_date.desc()).first()
                    
                    # Calculate period change according to our design rules
                    period_change_pct = None
                    period_change_display = None
                    change_type = 'percentage'
                    
                    if previous_indicator:
                        # RULE: Percentage-based indicators show ABSOLUTE change
                        # RULE: Absolute indicators show PERCENTAGE change
                        
                        if indicator_name in ['gdp_yoy_growth_bea', 'cpi_yoy_inflation', 'fed_funds_rate', 'unemployment_rate', 'treasury_10y_yield']:
                            # These are already percentages, so show absolute change in percentage points
                            period_change_display = latest_indicator.value - previous_indicator.value
                            change_type = 'percentage_points'
                        else:
                            # These are absolute values (sales, production index, price index), so show percentage change
                            period_change_pct = ((latest_indicator.value - previous_indicator.value) / previous_indicator.value) * 100
                            period_change_display = period_change_pct
                            change_type = 'percentage'
                    
                    # Determine market impact based on indicator and change
                    market_impact = 'neutral'
                    if period_change_display is not None:
                        if indicator_name in ['gdp_yoy_growth_bea']:
                            # GDP growth: absolute change in percentage points (e.g., 2.5% to 1.8% = -0.7pp)
                            market_impact = 'bullish' if period_change_display > 0.2 else 'bearish' if period_change_display < -0.2 else 'neutral'
                        elif indicator_name in ['retail_sales', 'industrial_production']:
                            # These show percentage change, so use percentage thresholds
                            market_impact = 'bullish' if period_change_display > 0.5 else 'bearish' if period_change_display < -0.5 else 'neutral'
                        elif indicator_name == 'unemployment_rate':
                            # Unemployment: absolute change in percentage points (e.g., 4.1% to 4.3% = +0.2pp)
                            # Rising unemployment is bearish, falling is bullish
                            market_impact = 'bearish' if period_change_display > 0.1 else 'bullish' if period_change_display < -0.1 else 'neutral'
                        elif indicator_name == 'cpi_yoy_inflation':
                            # Inflation: absolute change in percentage points (e.g., 3.1% to 2.8% = -0.3pp)
                            # Rising inflation is generally bearish, falling is bullish
                            market_impact = 'bearish' if period_change_display > 0.2 else 'bullish' if period_change_display < -0.2 else 'neutral'
                        elif indicator_name in ['fed_funds_rate', 'treasury_10y_yield']:
                            # Interest rates: absolute change in percentage points (e.g., 4.25% to 4.50% = +0.25pp)
                            # Rising rates can be bearish for equities
                            market_impact = 'bearish' if period_change_display > 0.25 else 'bullish' if period_change_display < -0.25 else 'neutral'
                        elif indicator_name == 'home_price_index':
                            # Home prices: percentage change
                            market_impact = 'bullish' if period_change_display > 1.0 else 'bearish' if period_change_display < -0.5 else 'neutral'
                    
                    # Map indicator names to display names
                    display_names = {
                        'gdp_yoy_growth_bea': 'Real GDP Growth',
                        'cpi_yoy_inflation': 'Inflation (CPI)',
                        'fed_funds_rate': 'Fed Funds Rate',
                        'unemployment_rate': 'Unemployment Rate',
                        'retail_sales': 'Retail Sales',
                        'industrial_production': 'Industrial Production',
                        'home_price_index': 'Home Price Index',
                        'treasury_10y_yield': '10-Year Treasury Yield'
                    }
                    
                    # Determine period description
                    period_desc = 'Month-over-Month'
                    if latest_indicator.period_type == 'quarterly':
                        period_desc = 'Quarter-over-Quarter'
                    elif latest_indicator.period_type == 'annual':
                        period_desc = 'Year-over-Year'
                    
                    indicators_data.append({
                        'indicator_name': display_names.get(indicator_name, latest_indicator.indicator_name),
                        'value': latest_indicator.value,
                        'reference_date': latest_indicator.reference_date.isoformat(),
                        'unit': latest_indicator.unit or '',
                        'category': latest_indicator.category,
                        'period_type': latest_indicator.period_type or 'monthly',
                        'market_impact': market_impact,
                        'period_change_pct': period_change_pct,
                        'period_desc': period_desc,
                        'period_change_display': period_change_display,
                        'change_type': change_type
                    })
            
            # Get latest agent analysis
            from .models import FundamentalsAnalysis
            from .agents.economic_fundamentals_agent import EconomicFundamentalsAgent
            
            latest_analysis = db.query(FundamentalsAnalysis).order_by(
                FundamentalsAnalysis.analysis_date.desc()
            ).first()
            
            if latest_analysis:
                # Get frontend-friendly summary from agent
                agent = EconomicFundamentalsAgent()
                frontend_summary = await agent.get_frontend_summary()
                
                return {
                    'indicators': indicators_data,  # Our carefully designed 8 indicators
                    'summary': frontend_summary,  # Short summary for frontend display
                    'economic_cycle': latest_analysis.economic_cycle_stage or 'Unknown',
                    'monetary_policy': latest_analysis.monetary_policy_stance or 'Unknown',
                    'inflation_trend': latest_analysis.inflation_outlook or 'Unknown',
                    'growth_outlook': latest_analysis.employment_outlook or 'Unknown',
                    'market_implications': {
                        'equities': 'Economic conditions influencing equity markets',
                        'bonds': 'Interest rate environment affecting fixed income', 
                        'commodities': 'Growth and inflation impacting commodity demand',
                        'dollar': 'Monetary policy and growth affecting dollar strength'
                    },
                    'agent_intelligence': {
                        'has_ai_analysis': True,
                        'last_updated': latest_analysis.analysis_date.isoformat(),
                        'comprehensive_analysis_available': True,  # Indicate full analysis exists
                        'analysis_fields': ['comprehensive_analysis', 'sector_impacts', 'market_implications', 'key_insights']
                    }
                }
            else:
                return {
                    'indicators': indicators_data,
                    'summary': 'Economic fundamentals data from Federal Reserve and Bureau of Economic Analysis. AI analysis pending.',
                    'economic_cycle': 'Unknown',
                    'monetary_policy': 'Unknown', 
                    'inflation_trend': 'Unknown',
                    'growth_outlook': 'Unknown',
                    'market_implications': {
                        'equities': 'Analysis pending',
                        'bonds': 'Analysis pending',
                        'commodities': 'Analysis pending', 
                        'dollar': 'Analysis pending'
                    },
                    'agent_intelligence': {
                        'has_ai_analysis': False,
                        'last_updated': datetime.utcnow().isoformat()
                    }
                }
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error getting enhanced fundamentals data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/fundamentals/force-refresh", dependencies=[Depends(verify_admin_key)])
async def force_refresh_fundamentals():
    """Force refresh economic fundamentals (non-blocking)"""
    try:
        # Start background processing without waiting
        async def background_refresh():
            from .agents.economic_fundamentals_agent import EconomicFundamentalsAgent
            logger.info("Force refreshing economic fundamentals analysis in background")
            agent = EconomicFundamentalsAgent()
            await agent.run_cycle(force=True)
        
        asyncio.create_task(background_refresh())
        
        return {
            "status": "processing",
            "message": "Fundamentals refresh started in background. Current analysis will remain visible while processing."
        }
        
    except Exception as e:
        logger.error(f"Error starting fundamentals refresh: {e}")
        return {
            "status": "error", 
            "message": f"Failed to start fundamentals refresh: {str(e)}"
        }

# 🧠 AGENT INTELLIGENCE ENDPOINTS

@app.get("/api/market-sentiment/latest")
async def get_latest_market_sentiment():
    """Get latest market sentiment with agent intelligence (enhanced for frontend)"""
    db = SessionLocal()
    try:
        # Get the most recent sentiment data
        latest_sentiment = db.query(MarketSentiment).order_by(
            MarketSentiment.recorded_at.desc()
        ).first()
        
        if not latest_sentiment:
            return {"error": "No sentiment data available"}
        
        # Structure data for frontend consumption
        sentiment_data = {
            # Basic Market Data
            "sp500_change_pct": latest_sentiment.sp500_change_pct or 0,
            "nasdaq_change_pct": latest_sentiment.nasdaq_change_pct or 0,
            "vix_value": latest_sentiment.vix_value or 0,
            "vix_change_pct": latest_sentiment.vix_change_pct or 0,
            "overall_sentiment_score": latest_sentiment.overall_sentiment_score or 5.0,
            "sentiment_label": latest_sentiment.sentiment_label or "Neutral",
            
            # 🧠 Agent Intelligence (if available)
            "agent_sentiment_score": latest_sentiment.agent_sentiment_score,
            "agent_sentiment_label": latest_sentiment.agent_sentiment_label,
            "agent_confidence": latest_sentiment.agent_confidence,
            "agent_key_insights": latest_sentiment.agent_key_insights,
            "agent_historical_context": latest_sentiment.agent_historical_context,
            "agent_risk_factors": latest_sentiment.agent_risk_factors,
            "agent_trend_direction": latest_sentiment.agent_trend_direction,
            "agent_volatility_assessment": latest_sentiment.agent_volatility_assessment,
            "agent_last_updated": latest_sentiment.agent_last_updated.isoformat() if latest_sentiment.agent_last_updated else None,
            "has_agent_analysis": latest_sentiment.has_agent_analysis or False,
            
            # Metadata
            "recorded_at": latest_sentiment.recorded_at.isoformat(),
            "data_completeness": latest_sentiment.data_completeness or 0.8
        }
        
        return sentiment_data
        
    except Exception as e:
        logger.error(f"Error fetching latest sentiment: {e}")
        return {"error": str(e)}
    finally:
        db.close()


@app.post("/api/agents/sentiment/trigger")
async def trigger_sentiment_agent(background_tasks: BackgroundTasks):
    """Trigger market sentiment agent analysis"""
    try:
        # Initialize market sentiment agent
        sentiment_agent = MarketSentimentAgent()
        
        # Trigger analysis in background
        background_tasks.add_task(sentiment_agent.run_cycle)
        
        return {
            "status": "success",
            "message": "Market sentiment analysis triggered via agent",
            "agent_id": sentiment_agent.agent_id
        }
    except Exception as e:
        logger.error(f"Error triggering sentiment analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/agents/news/trigger")
async def trigger_news_agent(background_tasks: BackgroundTasks):
    """Trigger news agent analysis"""
    try:
        # Initialize news agent
        news_agent = NewsAgent()
        
        # Trigger analysis in background
        background_tasks.add_task(news_agent.run_cycle)
        
        return {
            "status": "success",
            "message": "News analysis triggered via agent",
            "agent_id": news_agent.agent_id
        }
    except Exception as e:
        logger.error(f"Error triggering news analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/market-news/latest-with-intelligence")
async def get_latest_news_with_intelligence():
    """Get latest news with agent intelligence"""
    db = SessionLocal()
    try:
        # Get recent news articles with agent analysis
        recent_articles = db.query(MarketArticle).order_by(
            MarketArticle.published_at.desc()
        ).limit(10).all()
        
        # Get latest news summary
        latest_summary = db.query(MarketNewsSummary).order_by(
            MarketNewsSummary.created_at.desc()
        ).first()
        
        # Get latest news agent findings
        news_agent_findings = db.query(AgentFinding).filter(
            AgentFinding.agent_id.like("news_%")
        ).order_by(AgentFinding.created_at.desc()).limit(5).all()
        
        # Format articles with intelligence
        formatted_articles = []
        for article in recent_articles:
            formatted_articles.append({
                "id": article.id,
                "title": article.title,
                "summary": article.summary,
                "source": article.source,
                "published_at": article.published_at.isoformat(),
                
                # Agent Intelligence
                "market_signal": article.market_signal,
                "significance_score": article.significance_score or 0.5,
                "affected_sectors": article.affected_sectors or [],
                "key_points": article.key_points or []
            })
        
        # Format agent findings
        agent_insights = []
        for finding in news_agent_findings:
            if finding.finding_type in ['market_alert', 'sector_impact', 'news_sentiment']:
                agent_insights.append({
                    "finding_type": finding.finding_type,
                    "subject": finding.subject,
                    "confidence": finding.confidence_score,
                    "data": finding.finding_data,
                    "created_at": finding.created_at.isoformat()
                })
        
        return {
            "articles": formatted_articles,
            "latest_summary": latest_summary.summary if latest_summary else None,
            "agent_insights": agent_insights,
            "has_agent_analysis": len(agent_insights) > 0,
            "last_updated": recent_articles[0].published_at.isoformat() if recent_articles else None
        }
        
    except Exception as e:
        logger.error(f"Error fetching news with intelligence: {e}")
        return {"error": str(e)}
    finally:
        db.close()


@app.post("/api/agents/trigger-all")
async def trigger_all_agents(background_tasks: BackgroundTasks):
    """Trigger all available market analysis services"""
    try:
        # Initialize market agents
        sentiment_agent = MarketSentimentAgent()
        news_agent = NewsAgent()
        
        # Trigger analysis in background
        background_tasks.add_task(sentiment_agent.run_cycle)
        background_tasks.add_task(news_agent.run_cycle)
        
        return {
            "status": "success",
            "message": "All market analysis services triggered",
            "services_started": ["market_sentiment", "market_news"]
        }
        
    except Exception as e:
        logger.error(f"Error triggering agents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 🎯 STOCK-LEVEL AGENT ENDPOINTS (RESTORED)

@app.get("/api/stock/{ticker}/analysis")
async def get_stock_analysis(ticker: str):
    """Get comprehensive stock analysis with agent intelligence (V2) - from batch database"""
    try:
        ticker = ticker.upper()
        
        # Check if ticker is in S&P 500
        db = SessionLocal()
        try:
            from .models import SP500Stock
            sp_stock = db.query(SP500Stock).filter(SP500Stock.ticker == ticker).first()
            
            if not sp_stock:
                return {
                    'ticker': ticker,
                    'error': f'{ticker} is not in the S&P 500. Only S&P 500 stocks are supported.',
                    'has_analysis': False
                }
        finally:
            db.close()
        
        # Initialize V2 stock master agent for this ticker
        master_agent = StockMasterAgentV2(ticker)
        analysis = await master_agent.get_latest_analysis()
        
        if 'error' in analysis:
            return {
                'ticker': ticker,
                'error': analysis['error'],
                'has_analysis': False
            }
        
        return {
            'ticker': ticker,
            'has_analysis': True,
            **analysis
        }
        
    except Exception as e:
        logger.error(f"Error getting stock analysis for {ticker}: {e}")
        return {'error': str(e), 'ticker': ticker, 'has_analysis': False}


@app.post("/api/stock/{ticker}/analyze")
async def trigger_stock_analysis(ticker: str, background_tasks: BackgroundTasks):
    """Trigger comprehensive stock analysis for a ticker (V2)"""
    try:
        ticker = ticker.upper()
        
        # Validate ticker exists first
        import yfinance as yf
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            
            # Check if ticker is valid (yfinance returns empty dict or minimal data for invalid tickers)
            if not info or 'symbol' not in info or info.get('regularMarketPrice') is None:
                return {
                    'status': 'error',
                    'error': f'Invalid ticker symbol: {ticker}. Please check the symbol and try again.',
                    'ticker': ticker
                }
        except Exception as validation_error:
            logger.warning(f"Ticker validation failed for {ticker}: {validation_error}")
            return {
                'status': 'error',
                'error': f'Invalid ticker symbol: {ticker}. Please check the symbol and try again.',
                'ticker': ticker
            }
        
        # Add to tracked stocks first
        from .services.stock_data_collector import StockDataCollector
        stock_collector = StockDataCollector()
        await stock_collector.add_tracked_stock(ticker)
        
        # Initialize V2 stock master agent for this ticker
        master_agent = StockMasterAgentV2(ticker)
        
        # Trigger analysis in background
        background_tasks.add_task(master_agent.run_cycle)
        
        return {
            'status': 'success',
            'message': f'Stock analysis triggered for {ticker}. Data collection and AI analysis started.',
            'ticker': ticker,
            'agent_id': master_agent.agent_id
        }
        
    except Exception as e:
        logger.error(f"Error triggering stock analysis for {ticker}: {e}")
        return {'status': 'error', 'error': str(e)}


@app.get("/api/stock/{ticker}/price-explanation")
async def explain_stock_price(ticker: str, timeframe: str = "1d"):
    """Get AI explanation of recent price movements"""
    try:
        ticker = ticker.upper()
        
        # Initialize stock master agent for this ticker
        master_agent = StockMasterAgent(ticker)
        explanation = await master_agent.explain_price_movement(timeframe)
        
        return {
            'ticker': ticker,
            'timeframe': timeframe,
            'explanation': explanation
        }
        
    except Exception as e:
        logger.error(f"Error explaining price for {ticker}: {e}")
        return {'error': str(e)}


@app.get("/api/stock/{ticker}/peer-comparison")
async def compare_stock_to_peers(ticker: str):
    """Get AI comparison of stock to sector peers"""
    try:
        ticker = ticker.upper()
        
        # Initialize stock master agent for this ticker
        master_agent = StockMasterAgent(ticker)
        comparison = await master_agent.compare_to_peers()
        
        return {
            'ticker': ticker,
            'comparison': comparison
        }
        
    except Exception as e:
        logger.error(f"Error comparing {ticker} to peers: {e}")
        return {'error': str(e)}


@app.get("/api/stock/{ticker}/watchlist/add")
async def add_to_watchlist(ticker: str, user_id: str = "default_user"):
    """Add stock to user's watchlist"""
    try:
        from .models import StockWatchlist
        
        ticker = ticker.upper()
        db = SessionLocal()
        
        # Check if already in watchlist
        existing = db.query(StockWatchlist).filter(
            and_(
                StockWatchlist.ticker == ticker,
                StockWatchlist.user_id == user_id,
                StockWatchlist.is_active == True
            )
        ).first()
        
        if existing:
            return {
                'status': 'already_exists',
                'message': f'{ticker} is already in your watchlist'
            }
        
        # Add to watchlist
        watchlist_entry = StockWatchlist(
            user_id=user_id,
            ticker=ticker,
            is_active=True
        )
        
        db.add(watchlist_entry)
        db.commit()
        
        return {
            'status': 'success',
            'message': f'{ticker} added to watchlist',
            'ticker': ticker
        }
        
    except Exception as e:
        logger.error(f"Error adding {ticker} to watchlist: {e}")
        return {'error': str(e)}
    finally:
        db.close()


@app.get("/api/watchlist")
async def get_user_watchlist(user_id: str = "default_user"):
    """Get user's watchlist with latest analysis"""
    try:
        from .models import StockWatchlist, StockAnalysis
        
        db = SessionLocal()
        
        # Get active watchlist entries
        watchlist_entries = db.query(StockWatchlist).filter(
            and_(
                StockWatchlist.user_id == user_id,
                StockWatchlist.is_active == True
            )
        ).all()
        
        watchlist_data = []
        
        for entry in watchlist_entries:
            # Get latest analysis for this ticker
            latest_analysis = db.query(StockAnalysis).filter(
                StockAnalysis.ticker == entry.ticker
            ).order_by(StockAnalysis.analysis_date.desc()).first()
            
            entry_data = {
                'ticker': entry.ticker,
                'added_at': entry.added_at.isoformat(),
                'alert_threshold': entry.alert_threshold,
                'has_analysis': latest_analysis is not None
            }
            
            if latest_analysis:
                entry_data.update({
                    'current_price': latest_analysis.current_price,
                    'overall_rating': latest_analysis.overall_rating,
                    'confidence_score': latest_analysis.confidence_score,
                    'target_price': latest_analysis.target_price,
                    'upside_potential': latest_analysis.upside_potential,
                    'last_analysis': latest_analysis.analysis_date.isoformat()
                })
            
            watchlist_data.append(entry_data)
        
        return {
            'user_id': user_id,
            'watchlist': watchlist_data,
            'total_stocks': len(watchlist_data)
        }
        
    except Exception as e:
        logger.error(f"Error getting watchlist: {e}")
        return {'error': str(e)}
    finally:
        db.close()

# Error handlers
@app.exception_handler(404)
async def not_found_handler(request, exc):
    return JSONResponse(
        status_code=404,
        content={"message": "Endpoint not found"}
    )

@app.exception_handler(500)
async def internal_error_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"message": "Internal server error"}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"message": f"Unexpected error: {str(exc)}"}
    )

app.include_router(debug_router)

# 📊 MARKET-LEVEL AGENT ENDPOINTS

@app.get("/api/market-sentiment/enhanced")
async def get_enhanced_market_sentiment():
    """Get comprehensive market sentiment data with agent analysis"""
    try:
        db = SessionLocal()
        
        # Get current market indicators (frontend display - exclude treasury/dollar/dow)
        frontend_indicators = ['sp500', 'nasdaq', 'vix']  # Removed dow
        current_indicators = {}
        
        for indicator_type in frontend_indicators:
            latest_indicator = db.query(MarketIndicator).filter(
                MarketIndicator.indicator_type == indicator_type
            ).order_by(MarketIndicator.timestamp.desc()).first()
            
            if latest_indicator:
                current_indicators[indicator_type] = {
                    'value': latest_indicator.value,
                    'change_pct': latest_indicator.change_pct,
                    'timestamp': latest_indicator.timestamp.isoformat(),
                    'data_source': latest_indicator.data_source
                }
        
        # Get Fear & Greed Index
        market_sentiment_collector = MarketSentimentCollector()
        fear_greed = await market_sentiment_collector.collect_fear_greed_index()
        
        # Get agent analysis
        agent = MarketSentimentAgent()
        agent_analysis = await agent.get_latest_analysis()
        
        db.close()
        
        return {
            "current_indicators": current_indicators,
            "fear_greed_index": fear_greed,
            "agent_analysis": agent_analysis,
            "timestamp": datetime.utcnow().isoformat(),
            "data_sources": {
                "market_indicators": "yahoo_finance_live",
                "fear_greed": "cnn_fear_greed_api",
                "agent_analysis": "market_sentiment_agent"
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting enhanced market sentiment: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/market-sentiment/agent/run")
async def run_market_sentiment_agent():
    """Run the MarketSentimentAgent analysis cycle"""
    try:
        agent = MarketSentimentAgent()
        result = await agent.run_cycle()
        
        # Check if agent returned an error
        if isinstance(result, dict) and not result.get('success', True):
            return {
                "success": False,
                "error": result.get('error', 'Unknown agent error'),
                "error_type": result.get('error_type', 'UnknownError'),
                "agent_id": result.get('agent_id', 'market_sentiment_001'),
                "timestamp": result.get('timestamp', datetime.utcnow().isoformat()),
                "message": "Market sentiment agent failed to complete analysis"
            }
        
        # Get latest analysis after successful run
        latest_analysis = await agent.get_latest_analysis()
        
        return {
            "success": True,
            "message": "Market sentiment agent analysis completed successfully",
            "agent_id": agent.agent_id,
            "latest_analysis": latest_analysis,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error running market sentiment agent: {e}")
        return {
            "success": False,
            "error": f"Endpoint error: {str(e)}",
            "error_type": type(e).__name__,
            "message": "Failed to run market sentiment agent",
            "timestamp": datetime.utcnow().isoformat()
        }

@app.post("/api/market-sentiment/force-refresh", dependencies=[Depends(verify_admin_key)])
async def force_refresh_market_sentiment():
    """Force refresh market sentiment analysis (bypass duplicate prevention)"""
    try:
        from .services.historical_market_collector import HistoricalMarketCollector
        
        # First collect fresh market data
        market_collector = HistoricalMarketCollector()
        
        # Collect key market indicators
        indicators_config = {
            'sp500': '^GSPC',
            'nasdaq': '^IXIC',
            'vix': '^VIX'
        }
        
        collection_results = []
        collection_details = {}
        
        for indicator_type, symbol in indicators_config.items():
            try:
                result = await market_collector.collect_indicator_data(indicator_type, symbol)
                if result:
                    collection_results.append(f"{indicator_type}: {result['value']:.2f}")
                    collection_details[indicator_type] = result
            except Exception as e:
                logger.warning(f"Failed to collect {indicator_type}: {e}")
                collection_details[indicator_type] = {'error': str(e)}
        
        # Collect Fear & Greed Index
        market_sentiment_collector = MarketSentimentCollector()
        fear_greed = await market_sentiment_collector.collect_fear_greed_index()
        if fear_greed:
            collection_results.append(f"Fear&Greed: {fear_greed['value']}")
            collection_details['fear_greed'] = fear_greed
        
        # Run market sentiment agent with force=True
        agent = MarketSentimentAgent()
        agent_result = await agent.run_cycle(force=True)
        
        # Check if agent returned an error
        if isinstance(agent_result, dict) and not agent_result.get('success', True):
            return {
                "success": False,
                "error": agent_result.get('error', 'Unknown agent error'),
                "error_type": agent_result.get('error_type', 'UnknownError'),
                "agent_id": agent_result.get('agent_id', 'market_sentiment_001'),
                "timestamp": agent_result.get('timestamp', datetime.utcnow().isoformat()),
                "message": "Market sentiment agent failed during force refresh",
                "data_collection": {
                    "collection_type": "market_indicators_and_sentiment",
                    "indicators_collected": len(collection_details),
                    "collection_summary": collection_results,
                    "detailed_results": collection_details
                }
            }
        
        # Get the new analysis
        new_analysis = await agent.get_latest_analysis()
        
        return {
            "success": True,
            "message": "Force refresh completed successfully",
            "action": "force_refresh",
            "data_collection": {
                "collection_type": "market_indicators_and_sentiment",
                "indicators_collected": len(collection_details),
                "collection_summary": collection_results,
                "detailed_results": collection_details
            },
            "analysis_regenerated": True,
            "new_analysis": new_analysis,
            "timestamp": datetime.utcnow().isoformat(),
            "debug_info": {
                "duplicate_prevention_bypassed": True,
                "fresh_data_collected": True,
                "agent_analysis_forced": True
            }
        }
        
    except Exception as e:
        logger.error(f"Error in market sentiment force refresh: {e}")
        return {
            "success": False,
            "error": f"Force refresh endpoint error: {str(e)}",
            "error_type": type(e).__name__,
            "message": "Failed to complete force refresh",
            "timestamp": datetime.utcnow().isoformat()
        }

@app.get("/api/market-sentiment/agent/status")
async def get_market_sentiment_agent_status():
    """Get status of the MarketSentimentAgent with inter-agent communication info"""
    try:
        db = SessionLocal()
        try:
            # Check latest sentiment analysis
            latest_sentiment_analysis = db.query(MarketSentimentAnalysis).order_by(
                MarketSentimentAnalysis.analysis_date.desc()
            ).first()
            
            # Check economic fundamentals data
            latest_economic = db.query(EconomicIndicator).order_by(
                EconomicIndicator.reference_date.desc()
            ).first()
            
            # Check news data
            latest_news = db.query(MarketNewsSummary).order_by(
                MarketNewsSummary.created_at.desc()
            ).first()
            
            # Check today's analysis (duplicate prevention status)
            today = datetime.utcnow().date()
            today_analysis = db.query(MarketSentimentAnalysis).filter(
                MarketSentimentAnalysis.analysis_date >= datetime.combine(today, datetime.min.time())
            ).first()
            
            # Check market indicators
            market_data_freshness = {}
            frontend_indicators = ['sp500', 'nasdaq', 'dow', 'vix']
            for indicator_type in frontend_indicators:
                latest = db.query(MarketIndicator).filter(
                    MarketIndicator.indicator_type == indicator_type
                ).order_by(MarketIndicator.timestamp.desc()).first()
                if latest:
                    age = datetime.utcnow() - latest.timestamp
                    market_data_freshness[indicator_type] = {
                        'last_updated': latest.timestamp.isoformat(),
                        'age_minutes': int(age.total_seconds() / 60)
                    }
            
            return {
                "agent_status": "active",
                "agent_architecture_integration": {
                    "has_economic_data": latest_economic is not None,
                    "economic_last_updated": latest_economic.reference_date.isoformat() if latest_economic else None,
                    "has_news_data": latest_news is not None,
                    "news_last_updated": latest_news.created_at.isoformat() if latest_news else None,
                    "inter_agent_communication": "enabled"
                },
                "analysis_status": {
                    "has_latest_analysis": latest_sentiment_analysis is not None,
                    "latest_analysis_date": latest_sentiment_analysis.analysis_date.isoformat() if latest_sentiment_analysis else None,
                    "has_today_analysis": today_analysis is not None,
                    "duplicate_prevention": "active" if today_analysis else "ready_for_new_analysis"
                },
                "market_data_status": market_data_freshness,
                "sentiment_integration": "enabled",
                "fear_greed_tracking": "enabled",
                "timestamp": datetime.utcnow().isoformat()
            }
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error getting market sentiment agent status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stocks/batch-analyze", dependencies=[Depends(verify_admin_key)])
async def start_batch_analysis(background_tasks: BackgroundTasks, tickers: List[str] = None):
    """Start batch analysis of multiple stocks"""
    try:
        from .services.batch_analysis_service import BatchAnalysisService
        
        batch_service = BatchAnalysisService()
        
        # If no tickers provided, use all S&P 500
        if not tickers:
            tickers = await batch_service.load_sp500_tickers()
        
        job_id = await batch_service.start_batch_analysis(tickers, initiated_by="user")
        
        return {
            'status': 'success',
            'message': f'Batch analysis started for {len(tickers)} stocks',
            'job_id': job_id,
            'total_stocks': len(tickers)
        }
        
    except Exception as e:
        logger.error(f"Error starting batch analysis: {e}")
        return {'status': 'error', 'error': str(e)}


@app.post("/api/stocks/batch-analyze-failed", dependencies=[Depends(verify_admin_key)])
async def batch_analyze_failed_only(background_tasks: BackgroundTasks):
    """Re-analyze only stocks with incomplete/failed analyses"""
    try:
        from .services.batch_analysis_service import BatchAnalysisService
        from .services.analysis_validator import AnalysisValidator
        
        # Get all failed analyses
        validator = AnalysisValidator()
        failed = validator.get_all_failed_analyses()
        
        if not failed:
            return {
                'status': 'success',
                'message': 'No failed analyses to re-analyze',
                'total_stocks': 0
            }
        
        # Extract tickers
        tickers = [stock['ticker'] for stock in failed]
        
        # Start batch analysis for only these stocks
        batch_service = BatchAnalysisService()
        job_id = await batch_service.start_batch_analysis(tickers, initiated_by="user_failed_only")
        
        return {
            'status': 'success',
            'message': f'Re-analyzing {len(tickers)} failed stocks',
            'job_id': job_id,
            'total_stocks': len(tickers),
            'tickers': tickers[:10]  # Show first 10 for reference
        }
        
    except Exception as e:
        logger.error(f"Error starting failed-only batch analysis: {e}")
        return {'status': 'error', 'error': str(e)}


@app.post("/api/stocks/populate-sectors", dependencies=[Depends(verify_admin_key)])
async def populate_stock_sectors():
    """Populate sector data for all S&P 500 stocks"""
    try:
        from .services.batch_analysis_service import BatchAnalysisService
        
        batch_service = BatchAnalysisService()
        await batch_service.populate_stock_sectors()
        
        return {'status': 'success', 'message': 'Sector data populated'}
        
    except Exception as e:
        logger.error(f"Error populating sectors: {e}")
        return {'status': 'error', 'error': str(e)}


@app.get("/api/stocks/batch-status/{job_id}", dependencies=[Depends(verify_admin_key)])
async def get_batch_status(job_id: str):
    """Get status of a batch analysis job"""
    try:
        from .services.batch_analysis_service import BatchAnalysisService
        
        batch_service = BatchAnalysisService()
        status = batch_service.get_job_status(job_id)
        
        return status
        
    except Exception as e:
        logger.error(f"Error getting batch status: {e}")
        return {'error': str(e)}


@app.get("/api/stocks/opportunities/best-buys")
async def get_best_buys(limit: int = 10):
    """Get top best buy opportunities"""
    try:
        from .services.opportunity_scanner import OpportunityScanner
        
        scanner = OpportunityScanner()
        best_buys = scanner.get_best_buys(limit=limit)
        
        return {
            'best_buys': best_buys,
            'count': len(best_buys),
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting best buys: {e}")
        return {'error': str(e)}


@app.get("/api/stocks/opportunities/urgent-sells")
async def get_urgent_sells(limit: int = 10):
    """Get top urgent sell signals"""
    try:
        from .services.opportunity_scanner import OpportunityScanner
        
        scanner = OpportunityScanner()
        urgent_sells = scanner.get_urgent_sells(limit=limit)
        
        return {
            'urgent_sells': urgent_sells,
            'count': len(urgent_sells),
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting urgent sells: {e}")
        return {'error': str(e)}


@app.get("/api/stocks/opportunities/big-movers")
async def get_big_movers(limit: int = 10):
    """Get biggest movers"""
    try:
        from .services.opportunity_scanner import OpportunityScanner
        
        scanner = OpportunityScanner()
        big_movers = scanner.get_big_movers(limit=limit)
        
        return {
            'big_movers': big_movers,
            'count': len(big_movers),
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting big movers: {e}")
        return {'error': str(e)}


@app.get("/api/stocks/opportunities/sectors")
async def get_sectors():
    """Get list of sectors with stock counts"""
    try:
        from .models import SP500Stock
        from sqlalchemy import func
        
        db = SessionLocal()
        try:
            sectors = db.query(
                SP500Stock.sector,
                func.count(SP500Stock.ticker).label('stock_count')
            ).filter(
                SP500Stock.sector != None
            ).group_by(
                SP500Stock.sector
            ).order_by(
                func.count(SP500Stock.ticker).desc()
            ).all()
            
            return {
                'sectors': [{'name': s.sector, 'count': s.stock_count} for s in sectors],
                'total_sectors': len(sectors)
            }
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error getting sectors: {e}")
        return {'error': str(e)}


@app.get("/api/stocks/opportunities/best-buys-by-sector")
async def get_best_buys_by_sector(sector: str, limit: int = 5):
    """Get top best buy opportunities for a specific sector"""
    try:
        from .services.opportunity_scanner import OpportunityScanner
        
        scanner = OpportunityScanner()
        best_buys = scanner.get_best_buys_by_sector(sector=sector, limit=limit)
        
        return {
            'sector': sector,
            'best_buys': best_buys,
            'count': len(best_buys),
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting best buys by sector: {e}")
        return {'error': str(e)}


@app.get("/api/stocks/opportunities/urgent-sells-by-sector")
async def get_urgent_sells_by_sector(sector: str, limit: int = 5):
    """Get top urgent sell signals for a specific sector"""
    try:
        from .services.opportunity_scanner import OpportunityScanner
        
        scanner = OpportunityScanner()
        urgent_sells = scanner.get_urgent_sells_by_sector(sector=sector, limit=limit)
        
        return {
            'sector': sector,
            'urgent_sells': urgent_sells,
            'count': len(urgent_sells),
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting urgent sells by sector: {e}")
        return {'error': str(e)}


@app.post("/api/stocks/scan-opportunities", dependencies=[Depends(verify_admin_key)])
async def trigger_opportunity_scan(background_tasks: BackgroundTasks):
    """Manually trigger opportunity scan"""
    try:
        from .services.opportunity_scanner import OpportunityScanner
        
        scanner = OpportunityScanner()
        background_tasks.add_task(scanner.scan_all_opportunities)
        
        return {
            'status': 'success',
            'message': 'Opportunity scan started in background'
        }
        
    except Exception as e:
        logger.error(f"Error triggering opportunity scan: {e}")
        return {'status': 'error', 'error': str(e)}


@app.get("/api/stocks/recent-completions", dependencies=[Depends(verify_admin_key)])
async def get_recent_completions(limit: int = 10):
    """Get recently completed stock analyses"""
    try:
        from .models import SP500Stock
        
        db = SessionLocal()
        try:
            recent = db.query(SP500Stock).filter(
                SP500Stock.analysis_status == 'completed'
            ).order_by(SP500Stock.last_analyzed_at.desc()).limit(limit).all()
            
            return {
                'tickers': [stock.ticker for stock in recent],
                'count': len(recent)
            }
        finally:
            db.close()
        
    except Exception as e:
        logger.error(f"Error getting recent completions: {e}")
        return {'status': 'error', 'error': str(e)}


@app.get("/api/stocks/failed-analyses", dependencies=[Depends(verify_admin_key)])
async def get_failed_analyses():
    """Get all stocks with incomplete or failed analyses"""
    try:
        from .services.analysis_validator import AnalysisValidator
        
        validator = AnalysisValidator()
        failed = validator.get_all_failed_analyses()
        
        return {
            'failed_analyses': failed,
            'count': len(failed),
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting failed analyses: {e}")
        return {'status': 'error', 'error': str(e)}


@app.get("/api/stocks/current-batch", dependencies=[Depends(verify_admin_key)])
async def get_current_batch():
    """Get the currently running batch (or most recent batch)"""
    try:
        from .models import BatchAnalysisJob
        
        db = SessionLocal()
        try:
            # First check for running batch
            running_batch = db.query(BatchAnalysisJob).filter(
                BatchAnalysisJob.status == 'running'
            ).order_by(BatchAnalysisJob.started_at.desc()).first()
            
            if running_batch:
                return {
                    'job_id': running_batch.job_id,
                    'status': running_batch.status,
                    'total_stocks': running_batch.total_stocks,
                    'completed_stocks': running_batch.completed_stocks,
                    'failed_stocks': running_batch.failed_stocks,
                    'progress_pct': round((running_batch.completed_stocks / running_batch.total_stocks * 100), 1),
                    'started_at': running_batch.started_at.isoformat() if running_batch.started_at else None,
                    'completed_at': running_batch.completed_at.isoformat() if running_batch.completed_at else None
                }
            
            # If no running batch, return most recent batch
            recent_batch = db.query(BatchAnalysisJob).order_by(
                BatchAnalysisJob.started_at.desc()
            ).first()
            
            if recent_batch:
                return {
                    'job_id': recent_batch.job_id,
                    'status': recent_batch.status,
                    'total_stocks': recent_batch.total_stocks,
                    'completed_stocks': recent_batch.completed_stocks,
                    'failed_stocks': recent_batch.failed_stocks,
                    'progress_pct': round((recent_batch.completed_stocks / recent_batch.total_stocks * 100), 1),
                    'started_at': recent_batch.started_at.isoformat() if recent_batch.started_at else None,
                    'completed_at': recent_batch.completed_at.isoformat() if recent_batch.completed_at else None
                }
            
            # No batches at all
            return {
                'job_id': None,
                'status': 'none',
                'message': 'No batch analysis has been run yet'
            }
        finally:
            db.close()
        
    except Exception as e:
        logger.error(f"Error getting current batch: {e}")
        return {'status': 'error', 'error': str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 