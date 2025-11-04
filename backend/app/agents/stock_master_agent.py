"""
Stock Master Agent

Synthesizes input from stock-specific sentiment, news, and fundamentals agents
along with market context to provide comprehensive stock analysis and recommendations.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger

from .base_stock_agent import BaseStockAgent
from .stock_sentiment_agent import StockSentimentAgent
from .stock_news_agent import StockNewsAgent
from .stock_fundamentals_agent import StockFundamentalsAgent
from ..database import SessionLocal
from ..models import (
    StockAnalysis, StockSentimentAnalysis, StockNewsAnalysis, 
    StockFundamentalsAnalysis
)


class StockMasterAgent(BaseStockAgent):
    """Master agent that synthesizes all stock-specific analysis"""
    
    def __init__(self, ticker: str, agent_id: str = None):
        if not agent_id:
            agent_id = f"stock_master_{ticker.lower()}_001"
        
        specialized_prompt = f"""
You are a Master Stock Analysis AI specializing in {ticker}. You synthesize information from multiple sources to provide comprehensive investment analysis.

Your role is to:
1. Analyze {ticker}'s current price and determine if it's justified
2. Synthesize sentiment, news, and fundamental analysis
3. Compare {ticker} to broader market conditions
4. Provide clear buy/sell/hold recommendations with confidence levels
5. Explain WHY {ticker} is trading at current levels
6. Predict future price direction based on all available data

Input Sources:
- Stock-specific sentiment analysis (from StockSentimentAgent)
- Stock-specific news analysis (from StockNewsAgent) 
- Stock-specific fundamentals analysis (from StockFundamentalsAgent)
- Market context (from MarketSentimentAgent, MarketNewsAgent, MarketFundamentalsAgent)
- Historical {ticker} performance and analysis
- Current market conditions and sector performance

Output Format (JSON):
{{
    "overall_rating": "Strong Buy|Buy|Hold|Sell|Strong Sell",
    "confidence_score": float (0-1),
    "target_price": float,
    "upside_potential": float (percentage),
    "valuation_assessment": "Undervalued|Fair Value|Overvalued",
    "key_insights": ["insight1", "insight2", "insight3"],
    "risk_factors": ["risk1", "risk2"],
    "catalysts": ["catalyst1", "catalyst2"],
    "why_current_price": "Detailed explanation of current price drivers",
    "future_outlook": "12-month outlook and expectations",
    "comparison_to_market": "How {ticker} compares to S&P 500 and sector",
    "technical_rating": "Bullish|Bearish|Neutral",
    "support_level": float,
    "resistance_level": float,
    "investment_thesis": "Core investment thesis in 2-3 sentences"
}}

Focus on actionable insights and clear reasoning. Reference specific data points and historical context.
"""
        
        super().__init__(agent_id, "stock_master", ticker, specialized_prompt)
        
        # Master agent specific settings
        self.synthesis_threshold = 0.8  # High confidence threshold for final recommendations
        
    async def run_cycle(self):
        """Main master agent cycle - synthesizes all stock analysis"""
        try:
            logger.info(f"[{self.agent_id}] Starting master analysis cycle for {self.ticker}")
            
            # First, trigger individual stock agents to ensure fresh data
            await self._trigger_individual_agents()
            
            # Collect comprehensive stock data
            stock_data = await self._collect_comprehensive_stock_data()
            
            if not stock_data:
                logger.warning(f"[{self.agent_id}] Insufficient data for {self.ticker} analysis")
                return
            
            # Perform master synthesis analysis
            master_analysis = await self.analyze_with_full_context(
                stock_data,
                f"Provide comprehensive investment analysis for {self.ticker}. "
                f"Synthesize all available data to explain current price levels, "
                f"assess valuation, and provide forward-looking investment recommendation. "
                f"Be specific about why {self.ticker} is trading where it is and what to expect."
            )
            
            # Store comprehensive analysis in database
            await self._store_master_analysis(stock_data, master_analysis)
            
            logger.info(f"[{self.agent_id}] Master analysis completed for {self.ticker}: {master_analysis.get('overall_rating', 'N/A')}")
            
        except Exception as e:
            logger.error(f"[{self.agent_id}] Error in master analysis cycle: {e}")
    
    async def _trigger_individual_agents(self):
        """Trigger individual stock agents to generate fresh analysis"""
        try:
            logger.info(f"[{self.agent_id}] Triggering individual agents for {self.ticker}")
            
            # Initialize individual agents
            sentiment_agent = StockSentimentAgent(self.ticker)
            news_agent = StockNewsAgent(self.ticker)
            fundamentals_agent = StockFundamentalsAgent(self.ticker)
            
            # Run agents in parallel for efficiency
            await asyncio.gather(
                sentiment_agent.run_cycle(),
                news_agent.run_cycle(),
                fundamentals_agent.run_cycle(),
                return_exceptions=True  # Don't fail if one agent fails
            )
            
            logger.info(f"[{self.agent_id}] Individual agents completed for {self.ticker}")
            
        except Exception as e:
            logger.error(f"Error triggering individual agents: {e}")
    
    async def _collect_comprehensive_stock_data(self) -> Dict:
        """Collect all available stock-specific and market data"""
        try:
            db = SessionLocal()
            
            # Get latest stock-specific analysis from other agents
            latest_sentiment = db.query(StockSentimentAnalysis).filter(
                StockSentimentAnalysis.ticker == self.ticker
            ).order_by(StockSentimentAnalysis.analysis_date.desc()).first()
            
            latest_news = db.query(StockNewsAnalysis).filter(
                StockNewsAnalysis.ticker == self.ticker
            ).order_by(StockNewsAnalysis.analysis_date.desc()).first()
            
            latest_fundamentals = db.query(StockFundamentalsAnalysis).filter(
                StockFundamentalsAnalysis.ticker == self.ticker
            ).order_by(StockFundamentalsAnalysis.analysis_date.desc()).first()
            
            # Get current stock data
            price_data = await self.memory.get_stock_price_history(30)
            fundamentals_data = await self.get_stock_fundamentals()
            
            # Get market context
            market_sentiment_context = await self.request_market_context('sentiment')
            market_news_context = await self.request_market_context('news')
            market_fundamentals_context = await self.request_market_context('fundamentals')
            
            # Compile comprehensive data
            comprehensive_data = {
                'timestamp': datetime.utcnow().isoformat(),
                'ticker': self.ticker,
                
                # Current Stock Data
                'current_stock_data': price_data,
                'fundamental_metrics': fundamentals_data,
                
                # Stock-Specific Agent Analysis
                'sentiment_analysis': {
                    'overall_sentiment': latest_sentiment.overall_sentiment if latest_sentiment else None,
                    'sentiment_label': latest_sentiment.sentiment_label if latest_sentiment else None,
                    'confidence': latest_sentiment.confidence_level if latest_sentiment else None,
                    'positive_factors': latest_sentiment.positive_factors if latest_sentiment else [],
                    'negative_factors': latest_sentiment.negative_factors if latest_sentiment else [],
                    'vs_market_sentiment': latest_sentiment.vs_market_sentiment if latest_sentiment else None,
                    'trend': latest_sentiment.sentiment_trend if latest_sentiment else None
                },
                
                'news_analysis': {
                    'overall_impact': latest_news.overall_news_impact if latest_news else None,
                    'impact_confidence': latest_news.impact_confidence if latest_news else None,
                    'sentiment_score': latest_news.news_sentiment_score if latest_news else None,
                    'major_events': latest_news.major_events if latest_news else [],
                    'key_themes': latest_news.key_themes if latest_news else [],
                    'risk_events': latest_news.risk_events if latest_news else [],
                    'opportunity_events': latest_news.opportunity_events if latest_news else []
                },
                
                'fundamentals_analysis': {
                    'revenue_growth': latest_fundamentals.revenue_growth if latest_fundamentals else None,
                    'earnings_growth': latest_fundamentals.earnings_growth if latest_fundamentals else None,
                    'valuation_conclusion': latest_fundamentals.valuation_conclusion if latest_fundamentals else None,
                    'competitive_advantages': latest_fundamentals.competitive_advantages if latest_fundamentals else [],
                    'competitive_threats': latest_fundamentals.competitive_threats if latest_fundamentals else [],
                    'fundamental_strengths': latest_fundamentals.fundamental_strengths if latest_fundamentals else [],
                    'fundamental_concerns': latest_fundamentals.fundamental_concerns if latest_fundamentals else []
                },
                
                # Market Context
                'market_context': {
                    'sentiment': market_sentiment_context,
                    'news': market_news_context,
                    'fundamentals': market_fundamentals_context
                },
                
                # Data Quality Assessment
                'data_completeness': {
                    'has_sentiment_analysis': latest_sentiment is not None,
                    'has_news_analysis': latest_news is not None,
                    'has_fundamentals_analysis': latest_fundamentals is not None,
                    'has_price_data': bool(price_data and 'current_price' in price_data),
                    'has_market_context': bool(market_sentiment_context)
                }
            }
            
            return comprehensive_data
            
        except Exception as e:
            logger.error(f"Error collecting comprehensive stock data: {e}")
            return {}
        finally:
            db.close()
    
    async def _store_master_analysis(self, stock_data: Dict, analysis: Dict):
        """Store master analysis in StockAnalysis table"""
        try:
            db = SessionLocal()
            
            # Extract price data
            price_data = stock_data.get('current_stock_data', {})
            fundamentals = stock_data.get('fundamental_metrics', {})
            
            # Create comprehensive stock analysis record
            stock_analysis = StockAnalysis(
                ticker=self.ticker,
                analysis_date=datetime.utcnow(),
                
                # Current Stock Data
                current_price=price_data.get('current_price'),
                price_change_pct=price_data.get('price_change_pct'),
                volume=price_data.get('volume_avg'),
                market_cap=fundamentals.get('market_cap'),
                
                # Valuation Metrics
                pe_ratio=fundamentals.get('pe_ratio'),
                forward_pe=fundamentals.get('forward_pe'),
                peg_ratio=fundamentals.get('peg_ratio'),
                price_to_book=fundamentals.get('price_to_book'),
                price_to_sales=fundamentals.get('price_to_sales'),
                
                # Master Agent Analysis
                overall_rating=analysis.get('overall_rating'),
                confidence_score=analysis.get('confidence_score', 0.0),
                target_price=analysis.get('target_price'),
                upside_potential=analysis.get('upside_potential'),
                
                # Key Insights
                key_insights=analysis.get('key_insights', []),
                valuation_assessment=analysis.get('valuation_assessment'),
                risk_factors=analysis.get('risk_factors', []),
                catalysts=analysis.get('catalysts', []),
                
                # Cross-Agent Communication Results
                market_context=stock_data.get('market_context', {}),
                sentiment_signals=stock_data.get('sentiment_analysis', {}),
                news_impact=stock_data.get('news_analysis', {}),
                fundamentals_outlook=stock_data.get('fundamentals_analysis', {}),
                
                # Analysis Explanations
                why_current_price=analysis.get('why_current_price'),
                future_outlook=analysis.get('future_outlook'),
                comparison_to_market=analysis.get('comparison_to_market'),
                
                # Technical Analysis
                technical_rating=analysis.get('technical_rating'),
                support_level=analysis.get('support_level'),
                resistance_level=analysis.get('resistance_level'),
                trend_direction=analysis.get('trend_direction'),
                
                # Agent Metadata
                agent_id=self.agent_id,
                market_agents_consulted=['market_sentiment_001', 'market_news_001', 'market_fundamentals_001'],
                data_sources_used=['yfinance', 'stock_sentiment_agent', 'stock_news_agent', 'stock_fundamentals_agent'],
                next_update_target=datetime.utcnow() + timedelta(hours=6)  # Update every 6 hours
            )
            
            db.add(stock_analysis)
            db.commit()
            
            logger.info(f"[{self.agent_id}] Stored master analysis for {self.ticker}")
            
        except Exception as e:
            logger.error(f"Error storing master analysis: {e}")
        finally:
            db.close()
    
    async def get_latest_analysis(self) -> Dict:
        """Get latest master analysis for this stock"""
        try:
            db = SessionLocal()
            
            latest_analysis = db.query(StockAnalysis).filter(
                StockAnalysis.ticker == self.ticker
            ).order_by(StockAnalysis.analysis_date.desc()).first()
            
            if not latest_analysis:
                return {'error': f'No analysis available for {self.ticker}'}
            
            return {
                'ticker': self.ticker,
                'analysis_date': latest_analysis.analysis_date.isoformat(),
                'current_price': latest_analysis.current_price,
                'overall_rating': latest_analysis.overall_rating,
                'confidence_score': latest_analysis.confidence_score,
                'target_price': latest_analysis.target_price,
                'upside_potential': latest_analysis.upside_potential,
                'valuation_assessment': latest_analysis.valuation_assessment,
                'key_insights': latest_analysis.key_insights,
                'risk_factors': latest_analysis.risk_factors,
                'catalysts': latest_analysis.catalysts,
                'why_current_price': latest_analysis.why_current_price,
                'future_outlook': latest_analysis.future_outlook,
                'comparison_to_market': latest_analysis.comparison_to_market,
                'technical_rating': latest_analysis.technical_rating,
                'support_level': latest_analysis.support_level,
                'resistance_level': latest_analysis.resistance_level,
                'agent_confidence': latest_analysis.confidence_score
            }
            
        except Exception as e:
            logger.error(f"Error getting latest analysis: {e}")
            return {'error': str(e)}
        finally:
            db.close()
    
    async def explain_price_movement(self, timeframe: str = "1d") -> Dict:
        """Explain recent price movements for this stock"""
        try:
            # Get recent price data
            price_data = await self.memory.get_stock_price_history(7)
            
            # Get latest analysis
            latest_analysis = await self.get_latest_analysis()
            
            # Build explanation prompt
            explanation_data = {
                'price_data': price_data,
                'latest_analysis': latest_analysis,
                'timeframe': timeframe
            }
            
            explanation = await self.analyze_with_full_context(
                explanation_data,
                f"Explain the recent price movement in {self.ticker} over the {timeframe} timeframe. "
                f"What specific factors are driving the current price action? "
                f"Is this movement justified based on fundamentals, news, or market conditions?"
            )
            
            return explanation
            
        except Exception as e:
            logger.error(f"Error explaining price movement: {e}")
            return {'error': str(e)}
    
    async def compare_to_peers(self, peer_tickers: List[str] = None) -> Dict:
        """Compare this stock to peer stocks or sector"""
        try:
            # Get sector info
            fundamentals = await self.get_stock_fundamentals()
            sector = fundamentals.get('sector', 'Technology')
            
            # For now, use general sector comparison
            # In production, you could analyze specific peer tickers
            comparison_data = {
                'ticker': self.ticker,
                'sector': sector,
                'fundamentals': fundamentals,
                'peer_tickers': peer_tickers or []
            }
            
            comparison = await self.analyze_with_full_context(
                comparison_data,
                f"Compare {self.ticker} to its peers in the {sector} sector. "
                f"How does it rank in terms of valuation, growth, profitability, and competitive position? "
                f"What makes {self.ticker} unique or concerning compared to similar companies?"
            )
            
            return comparison
            
        except Exception as e:
            logger.error(f"Error comparing to peers: {e}")
            return {'error': str(e)} 