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
            
            # Calculate growth from quarterly financials (yfinance)
            calculated_revenue_growth = None
            calculated_earnings_growth = None
            latest_eps = None
            latest_quarter_date = None
            latest_quarter_label = None
            
            try:
                # Get quarterly income statement - has actual fiscal quarter end dates AND latest EPS
                quarterly = stock.quarterly_income_stmt
                
                # Get earnings_dates for extended historical data (8+ quarters)
                earnings_dates = stock.earnings_dates
                
                # Start with quarterly_income_stmt for the most recent data
                if not quarterly.empty and len(quarterly.columns) >= 5:
                    # Get the actual fiscal quarter end date
                    fiscal_quarter_end = quarterly.columns[0]
                    latest_quarter_date = fiscal_quarter_end.strftime('%Y-%m-%d')
                    quarter_month = fiscal_quarter_end.month
                    quarter_year = fiscal_quarter_end.year
                    
                    # Determine quarter label (Q1, Q2, Q3, Q4) with YEAR
                    if quarter_month in [1, 2, 3]:
                        quarter_num = 'Q1'
                    elif quarter_month in [4, 5, 6]:
                        quarter_num = 'Q2'
                    elif quarter_month in [7, 8, 9]:
                        quarter_num = 'Q3'
                    else:
                        quarter_num = 'Q4'
                    
                    # Full quarter label with year (e.g., "Q3 2025")
                    latest_quarter_label = f"{quarter_num} {quarter_year}"
                    
                    # Get latest EPS from quarterly income statement (Diluted EPS)
                    latest_eps = None
                    yoy_eps = None
                    latest_ttm_eps = None
                    prior_ttm_eps = None
                    
                    if 'Diluted EPS' in quarterly.index:
                        eps_data_quarterly = quarterly.loc['Diluted EPS']
                        latest_eps = eps_data_quarterly.iloc[0]
                        
                        # Now combine with earnings_dates for extended history (for TTM calculation)
                        # earnings_dates provides 8+ quarters but may lag; quarterly_income_stmt is more current
                        quarters_available_quarterly = len(eps_data_quarterly)
                        
                        # Try to use earnings_dates for historical data if available
                        if earnings_dates is not None and not earnings_dates.empty:
                            earnings = earnings_dates[
                                (earnings_dates['Event Type'] == 'Earnings') & 
                                (earnings_dates['Reported EPS'].notna())
                            ].copy().sort_index(ascending=False)
                            
                            quarters_available_earnings = len(earnings)
                            logger.info(f"[{self.ticker}] Available EPS data: {quarters_available_quarterly} quarters (quarterly_income_stmt), {quarters_available_earnings} quarters (earnings_dates)")
                        else:
                            quarters_available_earnings = 0
                            logger.info(f"[{self.ticker}] Available EPS data: {quarters_available_quarterly} quarters (quarterly_income_stmt only)")
                        
                        # Strategy: Use quarterly_income_stmt (most current) + earnings_dates (extended history)
                        # This handles cases where quarterly_income_stmt has latest quarter but earnings_dates lags
                        
                        if quarters_available_quarterly >= 5 and quarters_available_earnings >= 8:
                            # Hybrid approach: Use quarterly_income_stmt for recent quarters, fill in with earnings_dates for older data
                            # This gives us 8+ quarters for TTM even when earnings_dates hasn't updated yet
                            
                            # Build a combined EPS series: latest from quarterly, older from earnings_dates
                            combined_eps = list(eps_data_quarterly.iloc[0:min(4, quarters_available_quarterly)])
                            
                            # Fill in remaining quarters from earnings_dates (skipping any that overlap)
                            if quarters_available_earnings >= 8 - len(combined_eps):
                                for i in range(len(combined_eps), 8):
                                    # Map to earnings_dates index (may be offset if quarterly has newer data)
                                    earnings_idx = i - 1  # Adjust for potential lag
                                    if earnings_idx >= 0 and earnings_idx < len(earnings):
                                        combined_eps.append(earnings['Reported EPS'].iloc[earnings_idx])
                            
                            if len(combined_eps) >= 8:
                                # Calculate TTM
                                latest_ttm_eps = sum(combined_eps[0:4])
                                prior_ttm_eps = sum(combined_eps[4:8])
                                
                                if quarters_available_quarterly >= 5:
                                    yoy_eps = eps_data_quarterly.iloc[4]
                                
                                if prior_ttm_eps != 0 and not (latest_ttm_eps == 0 and prior_ttm_eps == 0):
                                    if prior_ttm_eps > 0:
                                        calculated_earnings_growth = ((latest_ttm_eps - prior_ttm_eps) / prior_ttm_eps) * 100
                                        logger.info(f"[{self.ticker}] TTM EPS Growth: {calculated_earnings_growth:.1f}% (Latest TTM: ${latest_ttm_eps:.2f}, Prior: ${prior_ttm_eps:.2f})")
                                    else:
                                        calculated_earnings_growth = None
                                        logger.info(f"[{self.ticker}] Recovering from loss (TTM): ${prior_ttm_eps:.2f} → ${latest_ttm_eps:.2f}")
                        elif quarters_available_quarterly >= 5:
                            # Fallback: Use quarterly_income_stmt for YoY comparison (single quarter)
                            yoy_eps = eps_data_quarterly.iloc[4]
                            if yoy_eps and yoy_eps != 0 and not (latest_eps == 0 and yoy_eps == 0):
                                if yoy_eps > 0:
                                    calculated_earnings_growth = ((latest_eps - yoy_eps) / yoy_eps) * 100
                                    logger.info(f"[{self.ticker}] Single quarter YoY EPS Growth: {calculated_earnings_growth:.1f}% (Latest: ${latest_eps:.2f}, YoY: ${yoy_eps:.2f})")
                                else:
                                    calculated_earnings_growth = None
                                    logger.info(f"[{self.ticker}] Recovering from loss (quarterly): ${yoy_eps:.2f} → ${latest_eps:.2f}")
                        else:
                            logger.warning(f"[{self.ticker}] Insufficient EPS data: only {quarters_available_quarterly} quarters from quarterly_income_stmt (need 5+ for growth calc)")
                    
                else:
                    logger.warning(f"[{self.ticker}] No earnings dates data available or insufficient quarterly data")
                
                # Calculate revenue growth using TTM (from quarterly income statement)
                # Note: We still use quarterly_income_stmt for revenue as earnings_dates doesn't have revenue
                latest_ttm_revenue = None
                prior_ttm_revenue = None
                
                # quarterly was already loaded above
                if not quarterly.empty and 'Total Revenue' in quarterly.index:
                    revenue_data = quarterly.loc['Total Revenue']
                    revenue_quarters_available = len(revenue_data)
                    logger.info(f"[{self.ticker}] Available quarters of revenue data: {revenue_quarters_available}")
                    
                    if revenue_quarters_available >= 8:
                        # TTM revenue (sum of last 4 quarters)
                        latest_ttm_revenue = revenue_data.iloc[0:4].sum()
                        # Prior TTM revenue (sum of quarters 4-7)
                        prior_ttm_revenue = revenue_data.iloc[4:8].sum()
                        if prior_ttm_revenue != 0:
                            calculated_revenue_growth = ((latest_ttm_revenue - prior_ttm_revenue) / prior_ttm_revenue) * 100
                            logger.info(f"[{self.ticker}] TTM Revenue: Latest ${latest_ttm_revenue/1e9:.2f}B, Prior ${prior_ttm_revenue/1e9:.2f}B, Growth {calculated_revenue_growth:.1f}%")
                    elif revenue_quarters_available >= 5:
                        # Fallback: Single quarter YoY revenue growth
                        latest_revenue = revenue_data.iloc[0]
                        yoy_revenue = revenue_data.iloc[4]
                        if yoy_revenue != 0:
                            calculated_revenue_growth = ((latest_revenue - yoy_revenue) / yoy_revenue) * 100
                            logger.info(f"[{self.ticker}] Single quarter YoY Revenue Growth: {calculated_revenue_growth:.1f}%")
                    else:
                        logger.warning(f"[{self.ticker}] Insufficient revenue data: only {revenue_quarters_available} quarters available (need 5+)")
                
                # Log summary of calculations
                earnings_str = f"{calculated_earnings_growth:.1f}%" if calculated_earnings_growth is not None else "N/A (Recovering from Loss)"
                revenue_str = f"{calculated_revenue_growth:.1f}%" if calculated_revenue_growth is not None else "N/A"
                if latest_quarter_label and latest_eps is not None:
                    logger.info(f"[{self.ticker}] {latest_quarter_label} {latest_quarter_date} - Rev Growth: {revenue_str}, Earnings Growth: {earnings_str}, EPS: ${latest_eps}")
                    logger.info(f"[{self.ticker}] DEBUG CALC: latest_eps=${latest_eps}, yoy_eps={yoy_eps}, calculated_earnings_growth={calculated_earnings_growth}")
            except Exception as e:
                logger.warning(f"Could not calculate quarterly growth: {e}")
                import traceback
                logger.debug(traceback.format_exc())
            
            # Calculate Forward PE using our own methodology (more reliable than yfinance)
            calculated_forward_pe = None
            try:
                trailing_eps = info.get('trailingEps')
                current_price = info.get('currentPrice') or info.get('regularMarketPrice')
                
                if trailing_eps and current_price and calculated_earnings_growth is not None:
                    # Forward EPS = Trailing EPS × (1 + Earnings Growth Rate)
                    earnings_growth_decimal = calculated_earnings_growth / 100.0
                    forward_eps = trailing_eps * (1 + earnings_growth_decimal)
                    calculated_forward_pe = current_price / forward_eps
                    logger.info(f"[{self.ticker}] Calculated Forward PE: {calculated_forward_pe:.2f} (from Forward EPS: ${forward_eps:.2f})")
            except Exception as e:
                logger.warning(f"Could not calculate forward PE: {e}")
            
            # Calculate PEG Ratio (PE / Earnings Growth Rate)
            calculated_peg_ratio = None
            try:
                trailing_pe = info.get('trailingPE')
                if trailing_pe and calculated_earnings_growth and calculated_earnings_growth > 0:
                    # PEG = PE / Earnings Growth (as percentage)
                    calculated_peg_ratio = trailing_pe / calculated_earnings_growth
                    logger.info(f"[{self.ticker}] Calculated PEG Ratio: {calculated_peg_ratio:.2f} (PE {trailing_pe:.1f} / Growth {calculated_earnings_growth:.1f}%)")
            except Exception as e:
                logger.warning(f"Could not calculate PEG ratio: {e}")
            
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
                
                # Valuation metrics
                'pe_ratio': info.get('trailingPE'),
                'forward_pe': calculated_forward_pe,  # Use our calculated Forward PE (more reliable than yfinance)
                'peg_ratio': calculated_peg_ratio,  # Use our calculated PEG (yfinance doesn't provide it)
                'price_to_book': info.get('priceToBook'),
                'price_to_sales': info.get('priceToSalesTrailing12Months'),
                'ev_to_ebitda': info.get('enterpriseToEbitda'),
                
                # Profitability metrics (convert decimals to percentages for consistency)
                'profit_margins': (info.get('profitMargins') * 100) if info.get('profitMargins') else None,
                'operating_margins': (info.get('operatingMargins') * 100) if info.get('operatingMargins') else None,
                'return_on_assets': (info.get('returnOnAssets') * 100) if info.get('returnOnAssets') else None,
                'return_on_equity': (info.get('returnOnEquity') * 100) if info.get('returnOnEquity') else None,
                
                # Growth metrics - CALCULATED using TTM (Trailing 12-Month) to smooth volatility
                'revenue_growth': calculated_revenue_growth,  # TTM revenue growth
                'earnings_growth': calculated_earnings_growth,  # TTM earnings growth, None if recovering from loss
                'latest_eps': latest_eps,  # Most recent quarter EPS (for display)
                'yoy_eps': yoy_eps,  # Single quarter YoY comparison (for context)
                'latest_ttm_eps': latest_ttm_eps,  # TTM EPS (sum of last 4 quarters)
                'prior_ttm_eps': prior_ttm_eps,  # Prior TTM EPS
                'latest_quarter_date': latest_quarter_date,
                'latest_quarter_label': latest_quarter_label,
                'earnings_quarterly_growth': info.get('earningsQuarterlyGrowth'),
                'recovering_from_loss': (prior_ttm_eps is not None and prior_ttm_eps < 0 and calculated_earnings_growth is None),
                
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