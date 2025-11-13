"""
Base Stock Agent

Extends BaseAgent with stock-specific functionality for price data,
fundamentals, and stock memory management.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger
import yfinance as yf

from .base_agent import BaseAgent
from ..services.fmp_fundamentals import FMPFundamentalsService
from ..database import SessionLocal
from ..models import (
    MarketSentiment, MarketSentimentAnalysis, FundamentalsAnalysis,
    MarketNewsSummary, EconomicIndicator
)


class StockMemorySystem:
    """Stock-specific memory system extending agent memory"""
    
    def __init__(self, agent_id: str, ticker: str):
        self.agent_id = agent_id
        self.ticker = ticker
    
    async def get_stock_price_history(self, days_back: int = 30) -> Dict:
        """Get stock price history and calculate metrics"""
        try:
            # Get stock data using yfinance
            stock = yf.Ticker(self.ticker)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            
            hist = stock.history(start=start_date, end=end_date)
            
            if hist.empty:
                return {}
            
            # Calculate metrics
            current_price = float(hist['Close'].iloc[-1])
            start_price = float(hist['Close'].iloc[0])
            price_change_pct = ((current_price - start_price) / start_price) * 100
            
            # Volatility (std of daily returns)
            daily_returns = hist['Close'].pct_change().dropna()
            volatility = float(daily_returns.std() * 100)
            
            # Volume metrics
            volume_avg = float(hist['Volume'].mean())
            
            return {
                'ticker': self.ticker,
                'current_price': current_price,
                'start_price': start_price,
                'price_change_pct': price_change_pct,
                'volatility': volatility,
                'volume_avg': volume_avg,
                'high_52w': float(hist['High'].max()),
                'low_52w': float(hist['Low'].min()),
                'days_analyzed': len(hist)
            }
            
        except Exception as e:
            logger.error(f"Error getting price history for {self.ticker}: {e}")
            return {}
    
    async def get_stock_short_term_memory(self, days_back: int = 5) -> Dict:
        """Get recent stock-specific findings and context"""
        try:
            from ..models import AgentFinding
            
            db = SessionLocal()
            
            # Get recent findings for this stock
            recent_findings = db.query(AgentFinding).filter(
                AgentFinding.agent_id.like(f"%{self.ticker.lower()}%"),
                AgentFinding.created_at >= datetime.utcnow() - timedelta(days=days_back)
            ).order_by(AgentFinding.created_at.desc()).limit(10).all()
            
            findings_data = []
            for finding in recent_findings:
                findings_data.append({
                    'agent_id': finding.agent_id,
                    'finding_type': finding.finding_type,
                    'confidence': finding.confidence_score,
                    'data': finding.finding_data,
                    'created_at': finding.created_at.isoformat()
                })
            
            return {
                'recent_findings': findings_data,
                'recent_sentiment': [],  # Could be expanded
                'recent_analysis': []    # Could be expanded
            }
            
        except Exception as e:
            logger.error(f"Error getting stock memory for {self.ticker}: {e}")
            return {'recent_findings': [], 'recent_sentiment': [], 'recent_analysis': []}
        finally:
            db.close()


class BaseStockAgent(BaseAgent):
    """Base class for stock-specific agents"""
    
    # Class-level cache for fundamental data (shared across all agents)
    _fundamentals_cache = {}  # {ticker: {'data': {...}, 'timestamp': datetime}}
    _cache_ttl_hours = 24  # Cache fundamentals for 24 hours
    
    def __init__(self, agent_id: str, agent_type: str, ticker: str, specialized_prompt: str):
        super().__init__(agent_id, agent_type, specialized_prompt)
        self.ticker = ticker.upper()
        
        # Initialize stock-specific memory system (override base memory)
        self.memory = StockMemorySystem(agent_id, self.ticker)
    
    async def get_contextual_prompt(self, task_data: Dict) -> str:
        """Build contextual prompt with stock-specific memory"""
        
        # Get stock-specific memory
        short_term = await self.memory.get_stock_short_term_memory(3)
        
        # Get market context for comparison
        market_sentiment = await self.request_market_context('sentiment')
        market_news = await self.request_market_context('news')
        
        # Build context sections
        context_sections = []
        
        # Stock-specific context
        if short_term.get('recent_findings'):
            context_sections.append(f"Recent {self.ticker} Analysis:\n{json.dumps(short_term['recent_findings'][:2], indent=2)}")
        
        # Market context
        if market_sentiment:
            context_sections.append(f"Market Context: Sentiment {market_sentiment.get('market_sentiment_score', 5.0)}/10")
        
        # Build full prompt
        full_prompt = f"""
{self.specialized_prompt}

CURRENT TASK:
{json.dumps(task_data, indent=2)}

CONTEXT:
{chr(10).join(context_sections) if context_sections else 'No recent context available'}

Provide your analysis as a JSON object matching the specified format.
"""
        
        return full_prompt
        
    async def get_stock_fundamentals(self, force_refresh: bool = False) -> Dict:
        """Get fundamental data for this stock (with 24h caching)"""
        # Check cache first (unless force_refresh)
        if not force_refresh and self.ticker in self._fundamentals_cache:
            cached = self._fundamentals_cache[self.ticker]
            age_hours = (datetime.utcnow() - cached['timestamp']).total_seconds() / 3600
            if age_hours < self._cache_ttl_hours:
                logger.debug(f"[{self.ticker}] Using cached fundamentals ({age_hours:.1f}h old)")
                return cached['data']
        
        if force_refresh:
            logger.info(f"[{self.ticker}] Force refreshing fundamentals (bypassing cache)")
        
        try:
            logger.debug(f"[{self.ticker}] Fetching fresh fundamentals from yfinance")
            stock = yf.Ticker(self.ticker)
            info = stock.info
            
            # Initialize all variables (in case of exceptions)
            calculated_revenue_growth = None
            calculated_earnings_growth = None
            latest_eps = None
            latest_ttm_eps = None
            latest_quarter_date = None
            latest_quarter_label = None
            calculated_trailing_pe = None
            calculated_forward_pe = None
            calculated_peg_ratio = None
            
            try:
                # ============================================================
                # GET EPS DATA FROM YFINANCE (TTM + Latest Quarter)
                # ============================================================
                # Get Latest TTM EPS from yfinance (already split-adjusted and up to date)
                latest_ttm_eps = info.get('trailingEps')
                if latest_ttm_eps:
                    logger.info(f"[{self.ticker}] Latest TTM EPS (yfinance): ${latest_ttm_eps:.2f}")
                else:
                    logger.warning(f"[{self.ticker}] No trailingEps available from yfinance")
                
                # Get quarterly income statement - for latest quarter EPS and date
                quarterly = stock.quarterly_income_stmt
                
                # Get latest quarter date and single quarter EPS (for context on seasonality)
                if not quarterly.empty and len(quarterly.columns) >= 1:
                    # Get the actual fiscal quarter end date
                    fiscal_quarter_end = quarterly.columns[0]
                    latest_quarter_date = fiscal_quarter_end.strftime('%Y-%m-%d')
                    
                    # We store quarter label for internal logging
                    quarter_month = fiscal_quarter_end.month
                    quarter_year = fiscal_quarter_end.year
                    if quarter_month in [1, 2, 3]:
                        quarter_num = 'Q1'
                    elif quarter_month in [4, 5, 6]:
                        quarter_num = 'Q2'
                    elif quarter_month in [7, 8, 9]:
                        quarter_num = 'Q3'
                    else:
                        quarter_num = 'Q4'
                    latest_quarter_label = f"{quarter_num} {quarter_year}"
                    
                    # Get latest single quarter EPS (to show seasonality vs TTM)
                    if 'Diluted EPS' in quarterly.index:
                        eps_data_quarterly = quarterly.loc['Diluted EPS']
                        latest_eps = eps_data_quarterly.iloc[0]  # Most recent quarter
                        logger.info(f"[{self.ticker}] Latest quarter: {latest_quarter_date} - Single Quarter EPS: ${latest_eps:.2f}, TTM EPS: ${latest_ttm_eps:.2f if latest_ttm_eps else 'N/A'}")
                    else:
                        logger.warning(f"[{self.ticker}] No Diluted EPS data in quarterly_income_stmt")
                else:
                    logger.warning(f"[{self.ticker}] No quarterly income statement data available")
                
                # ============================================================
                # USE YAHOO FINANCE'S GROWTH METRICS DIRECTLY
                # ============================================================
                # Debug: Log what we're getting from yfinance
                logger.info(f"[{self.ticker}] DEBUG: earningsGrowth raw value: {info.get('earningsGrowth')} (type: {type(info.get('earningsGrowth'))})")
                logger.info(f"[{self.ticker}] DEBUG: revenueGrowth raw value: {info.get('revenueGrowth')} (type: {type(info.get('revenueGrowth'))})")
                logger.info(f"[{self.ticker}] DEBUG: Total info keys: {len(info.keys())}")
                logger.info(f"[{self.ticker}] DEBUG: Has earningsGrowth key: {'earningsGrowth' in info}")
                logger.info(f"[{self.ticker}] DEBUG: Has revenueGrowth key: {'revenueGrowth' in info}")
                
                # Yahoo provides earnings growth - use it directly
                calculated_earnings_growth = info.get('earningsGrowth')
                if calculated_earnings_growth is not None:
                    calculated_earnings_growth = calculated_earnings_growth * 100  # Convert to percentage
                    logger.info(f"[{self.ticker}] Earnings Growth (from yfinance): {calculated_earnings_growth:.1f}%")
                else:
                    logger.warning(f"[{self.ticker}] No earnings growth data available from yfinance")
                
                # Yahoo provides revenue growth - use it directly
                calculated_revenue_growth = info.get('revenueGrowth')
                if calculated_revenue_growth is not None:
                    calculated_revenue_growth = calculated_revenue_growth * 100  # Convert to percentage
                    logger.info(f"[{self.ticker}] Revenue Growth (from yfinance): {calculated_revenue_growth:.1f}%")
                else:
                    logger.warning(f"[{self.ticker}] No revenue growth data available from yfinance")
                
                # Log summary
                earnings_str = f"{calculated_earnings_growth:.1f}%" if calculated_earnings_growth is not None else "N/A"
                revenue_str = f"{calculated_revenue_growth:.1f}%" if calculated_revenue_growth is not None else "N/A"
                if latest_quarter_date and latest_eps is not None:
                    logger.info(f"[{self.ticker}] Quarter ended {latest_quarter_date} - Latest Quarter EPS: ${latest_eps:.2f}, TTM EPS: ${latest_ttm_eps:.2f if latest_ttm_eps else 'N/A'}")
                    logger.info(f"[{self.ticker}] Growth Metrics - Revenue: {revenue_str}, Earnings: {earnings_str}")
            except Exception as e:
                logger.warning(f"Could not calculate quarterly growth: {e}")
                import traceback
                logger.debug(traceback.format_exc())
            
            # ============================================================
            # USE YAHOO FINANCE'S PE RATIOS DIRECTLY
            # ============================================================
            try:
                # Use yfinance's PE ratios directly
                calculated_trailing_pe = info.get('trailingPE')
                if calculated_trailing_pe:
                    logger.info(f"[{self.ticker}] Trailing PE (from yfinance): {calculated_trailing_pe:.1f}")
                
                calculated_forward_pe = info.get('forwardPE')
                if calculated_forward_pe:
                    logger.info(f"[{self.ticker}] Forward PE (from yfinance): {calculated_forward_pe:.1f}")
                else:
                    logger.warning(f"[{self.ticker}] No forward PE available from yfinance")
            except Exception as e:
                logger.warning(f"Could not get PE ratios: {e}")
            
            # ============================================================
            # USE YAHOO FINANCE'S PEG RATIO DIRECTLY
            # ============================================================
            try:
                calculated_peg_ratio = info.get('pegRatio')
                if calculated_peg_ratio:
                    logger.info(f"[{self.ticker}] PEG Ratio (from yfinance): {calculated_peg_ratio:.2f}")
                else:
                    logger.warning(f"[{self.ticker}] No PEG ratio available from yfinance")
            except Exception as e:
                logger.warning(f"Could not get PEG ratio: {e}")
            
            # Calculate current quarter for context
            now = datetime.now()
            current_month = now.month
            if current_month in [1, 2, 3]:
                current_quarter = f"Q1 {now.year}"
            elif current_month in [4, 5, 6]:
                current_quarter = f"Q2 {now.year}"
            elif current_month in [7, 8, 9]:
                current_quarter = f"Q3 {now.year}"
            else:
                current_quarter = f"Q4 {now.year}"
            
            # Extract key fundamental metrics
            fundamentals = {
                'symbol': self.ticker,
                'company_name': info.get('longName', 'Unknown'),
                'sector': info.get('sector', 'Unknown'),
                'industry': info.get('industry', 'Unknown'),
                'market_cap': info.get('marketCap'),
                'enterprise_value': info.get('enterpriseValue'),
                
                # TEMPORAL CONTEXT (for LLM awareness)
                'analysis_date': now.strftime('%Y-%m-%d'),
                'current_quarter': current_quarter,
                
                # Valuation metrics (using our TTM-based calculations)
                'pe_ratio': calculated_trailing_pe if calculated_trailing_pe is not None else info.get('trailingPE'),  # Use our TTM-based PE
                'forward_pe': calculated_forward_pe,  # Calculated from TTM EPS × (1 + TTM Growth)
                'peg_ratio': calculated_peg_ratio,  # Calculated from our TTM-based PE / TTM Growth
                'price_to_book': info.get('priceToBook'),
                'price_to_sales': info.get('priceToSalesTrailing12Months'),
                'ev_to_ebitda': info.get('enterpriseToEbitda'),
                
                # Profitability metrics (convert decimals to percentages for consistency)
                'profit_margins': (info.get('profitMargins') * 100) if info.get('profitMargins') else None,
                'operating_margins': (info.get('operatingMargins') * 100) if info.get('operatingMargins') else None,
                'return_on_assets': (info.get('returnOnAssets') * 100) if info.get('returnOnAssets') else None,
                'return_on_equity': (info.get('returnOnEquity') * 100) if info.get('returnOnEquity') else None,
                
                # Growth metrics - FROM YAHOO FINANCE
                'revenue_growth': calculated_revenue_growth,  # Revenue growth (from yfinance)
                'earnings_growth': calculated_earnings_growth,  # Earnings growth (from yfinance)
                'latest_eps': latest_eps,  # Most recent quarter EPS (for seasonality context)
                'latest_ttm_eps': latest_ttm_eps,  # TTM EPS (for smoothed view vs quarterly)
                'latest_quarter_date': latest_quarter_date,
                'latest_quarter_label': latest_quarter_label,
                
                # Financial health
                'total_cash': info.get('totalCash'),
                'total_debt': info.get('totalDebt'),
                'debt_to_equity': info.get('debtToEquity'),
                'current_ratio': info.get('currentRatio'),
                'quick_ratio': info.get('quickRatio'),
                'free_cash_flow': info.get('freeCashflow'),  # Total FCF
                'operating_cash_flow': info.get('operatingCashflow'),
                
                # Dividend info
                'dividend_yield': info.get('dividendYield'),
                'payout_ratio': info.get('payoutRatio'),
                
                # Trading metrics
                'beta': info.get('beta'),
                'short_ratio': info.get('shortRatio'),
                'shares_outstanding': info.get('sharesOutstanding'),
                'float_shares': info.get('floatShares')
            }
            
            # Cache the fundamentals data
            self._fundamentals_cache[self.ticker] = {
                'data': fundamentals,
                'timestamp': datetime.utcnow()
            }
            logger.debug(f"[{self.ticker}] Cached fundamentals for 24 hours")
            
            return fundamentals
            
        except Exception as e:
            logger.error(f"Error getting fundamentals for {self.ticker}: {e}")
            return {'symbol': self.ticker, 'error': str(e)}
    
    async def request_market_context(self, context_type: str) -> Dict:
        """Request market context for comparative analysis"""
        try:
            db = SessionLocal()
            
            if context_type == 'sentiment':
                # Get latest market sentiment
                latest_sentiment = db.query(MarketSentiment).order_by(
                    MarketSentiment.recorded_at.desc()
                ).first()
                
                if latest_sentiment:
                    return {
                        'market_sentiment_score': latest_sentiment.overall_sentiment_score,
                        'sentiment_label': latest_sentiment.sentiment_label,
                        'sp500_change': latest_sentiment.sp500_change_pct,
                        'vix_value': latest_sentiment.vix_value,
                        'recorded_at': latest_sentiment.recorded_at.isoformat()
                    }
            
            elif context_type == 'fundamentals':
                # Get latest economic analysis
                latest_analysis = db.query(FundamentalsAnalysis).order_by(
                    FundamentalsAnalysis.analysis_date.desc()
                ).first()
                
                if latest_analysis:
                    return {
                        'economic_cycle_stage': latest_analysis.economic_cycle_stage,
                        'monetary_policy_stance': latest_analysis.monetary_policy_stance,
                        'inflation_outlook': latest_analysis.inflation_outlook,
                        'interest_rate_environment': 'restrictive' if latest_analysis.monetary_policy_stance == 'restrictive' else 'accommodative',
                        'analysis_date': latest_analysis.analysis_date.isoformat()
                    }
            
            elif context_type == 'news':
                # Get latest news summary
                latest_summary = db.query(MarketNewsSummary).order_by(
                    MarketNewsSummary.created_at.desc()
                ).first()
                
                if latest_summary:
                    return {
                        'market_news_summary': latest_summary.summary,
                        'news_sentiment': 'neutral',  # Could be enhanced
                        'created_at': latest_summary.created_at.isoformat()
                    }
            
            return {'context_type': context_type, 'status': 'no_data'}
            
        except Exception as e:
            logger.error(f"Error getting market context ({context_type}): {e}")
            return {'error': str(e)}
        finally:
            db.close()
    
    async def analyze_with_full_context(self, stock_data: Dict, task_description: str) -> Dict:
        """Perform analysis with stock and market context"""
        try:
            # Get market context for all relevant areas
            sentiment_context = await self.request_market_context('sentiment')
            fundamentals_context = await self.request_market_context('fundamentals')
            news_context = await self.request_market_context('news')
            
            # Build comprehensive context
            full_context = {
                'stock_data': stock_data,
                'market_context': {
                    'sentiment': sentiment_context,
                    'fundamentals': fundamentals_context,
                    'news': news_context
                },
                'ticker': self.ticker,
                'timestamp': datetime.utcnow().isoformat()
            }
            
            # Use the parent's analyze_with_context method
            return await self.analyze_with_context(full_context, task_description)
            
        except Exception as e:
            logger.error(f"Error in full context analysis for {self.ticker}: {e}")
            return {'error': str(e)}
    
    async def run_cycle(self):
        """Main agent cycle - to be implemented by subclasses"""
        raise NotImplementedError(f"Subclasses must implement run_cycle method") 