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
        
    async def get_stock_fundamentals(self) -> Dict:
        """Get fundamental data for this stock (with 24h caching)"""
        # Check cache first
        if self.ticker in self._fundamentals_cache:
            cached = self._fundamentals_cache[self.ticker]
            age_hours = (datetime.utcnow() - cached['timestamp']).total_seconds() / 3600
            if age_hours < self._cache_ttl_hours:
                logger.debug(f"[{self.ticker}] Using cached fundamentals ({age_hours:.1f}h old)")
                return cached['data']
        
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
                # Get quarterly income statement (has Normalized Income for non-GAAP earnings)
                quarterly = stock.quarterly_income_stmt
                if not quarterly.empty and len(quarterly.columns) >= 5:
                    # Get quarter date and extract year/quarter
                    latest_quarter_date = quarterly.columns[0].strftime('%Y-%m-%d')
                    quarter_month = quarterly.columns[0].month
                    quarter_year = quarterly.columns[0].year
                    
                    # Determine quarter label (Q1, Q2, Q3, Q4) with YEAR
                    if quarter_month in [1, 2, 3]:
                        quarter_num = 'Q1'
                    elif quarter_month in [4, 5, 6]:
                        quarter_num = 'Q2'
                    elif quarter_month in [7, 8, 9]:
                        quarter_num = 'Q3'
                    else:
                        quarter_num = 'Q4'
                    
                    # Full quarter label with year (e.g., "Q3 2024")
                    latest_quarter_label = f"{quarter_num} {quarter_year}"
                    
                    # Compare latest quarter (Q0) to same quarter last year (Q4, i.e., 4 quarters ago)
                    
                    # Calculate earnings growth from Diluted EPS (GAAP)
                    yoy_eps = None  # Track for LLM context
                    
                    if 'Diluted EPS' in quarterly.index:
                        latest_eps = quarterly.loc['Diluted EPS'].iloc[0]
                        yoy_eps = quarterly.loc['Diluted EPS'].iloc[4]  # 4 quarters ago
                        
                        if yoy_eps != 0 and not (latest_eps == 0 and yoy_eps == 0):
                            if yoy_eps > 0:
                                # Normal case: both profitable
                                calculated_earnings_growth = ((latest_eps - yoy_eps) / yoy_eps) * 100
                            else:
                                # Previous quarter was a LOSS - show as "Recovering from Loss"
                                # Don't calculate misleading growth %, but LLM gets actual numbers
                                calculated_earnings_growth = None
                                logger.info(f"[{self.ticker}] Recovering from loss: YoY EPS ${yoy_eps:.2f} → ${latest_eps:.2f}")
                    
                    # Calculate revenue growth from Total Revenue
                    if 'Total Revenue' in quarterly.index:
                        latest_revenue = quarterly.loc['Total Revenue'].iloc[0]
                        yoy_revenue = quarterly.loc['Total Revenue'].iloc[4]  # 4 quarters ago
                        if yoy_revenue != 0:
                            calculated_revenue_growth = ((latest_revenue - yoy_revenue) / yoy_revenue) * 100
                    
                    earnings_str = f"{calculated_earnings_growth:.1f}%" if calculated_earnings_growth is not None else "N/A (Recovering from Loss)"
                    logger.info(f"[{self.ticker}] {latest_quarter_label} {latest_quarter_date} - Rev Growth: {calculated_revenue_growth:.1f}%, Earnings Growth: {earnings_str}, EPS: ${latest_eps}")
            except Exception as e:
                logger.warning(f"Could not calculate quarterly growth: {e}")
            
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
                
                # Growth metrics - CALCULATED from quarterly financials (already as percentages like 9.6, 9.3)
                'revenue_growth': calculated_revenue_growth,
                'earnings_growth': calculated_earnings_growth,  # None if recovering from loss
                'latest_eps': latest_eps,
                'yoy_eps': yoy_eps,  # For LLM context when recovering from loss
                'latest_quarter_date': latest_quarter_date,
                'latest_quarter_label': latest_quarter_label,
                'earnings_quarterly_growth': info.get('earningsQuarterlyGrowth'),
                'recovering_from_loss': (yoy_eps is not None and yoy_eps < 0 and calculated_earnings_growth is None),
                
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