"""
Stock Sentiment Agent

Analyzes sentiment for specific stocks, incorporating market sentiment context
and storing stock-specific sentiment analysis.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger

from .base_stock_agent import BaseStockAgent
from ..database import SessionLocal
from ..models import StockSentimentAnalysis


class StockSentimentAgent(BaseStockAgent):
    """Agent specialized in analyzing sentiment for specific stocks"""
    
    def __init__(self, ticker: str, agent_id: str = None):
        if not agent_id:
            agent_id = f"stock_sentiment_{ticker.lower()}_001"
        
        specialized_prompt = f"""
You are a Stock Sentiment Analysis AI specializing in {ticker}.

Your role is to:
1. Analyze {ticker}-specific sentiment from news, social media, and analyst coverage
2. Compare {ticker} sentiment to broader market sentiment
3. Identify sentiment drivers specific to this stock
4. Track sentiment trends and momentum for {ticker}
5. Assess how market-wide sentiment affects {ticker} specifically

Focus on:
- Company-specific news sentiment (earnings, products, management)
- Analyst rating changes and price target adjustments  
- Social media and retail investor sentiment
- Institutional investor sentiment indicators
- How {ticker} sentiment compares to sector and market
- Sentiment momentum and trend changes

Output Format (JSON):
{{
    "overall_sentiment": float (-1 to 1),
    "sentiment_label": "Very Bearish|Bearish|Neutral|Bullish|Very Bullish",
    "confidence_level": float (0-1),
    "news_sentiment": float (-1 to 1),
    "analyst_sentiment": float (-1 to 1),
    "vs_market_sentiment": float (-1 to 1),
    "vs_sector_sentiment": float (-1 to 1),
    "sentiment_trend": "Improving|Stable|Deteriorating",
    "positive_factors": ["factor1", "factor2"],
    "negative_factors": ["factor1", "factor2"],
    "sentiment_drivers": ["driver1", "driver2"],
    "confidence": float (0-1),
    "finding_type": "stock_sentiment_analysis"
}}

Be specific about {ticker} and reference concrete events and data points.
"""
        
        super().__init__(agent_id, "stock_sentiment", ticker, specialized_prompt)
        
    async def run_cycle(self):
        """Main cycle for stock sentiment analysis"""
        try:
            logger.info(f"[{self.agent_id}] Starting sentiment analysis for {self.ticker}")
            
            # Collect sentiment data for this stock
            sentiment_data = await self._collect_stock_sentiment_data()
            
            if not sentiment_data:
                logger.warning(f"[{self.agent_id}] Insufficient sentiment data for {self.ticker}")
                return
            
            # Analyze sentiment with full context
            sentiment_analysis = await self.analyze_with_full_context(
                sentiment_data,
                f"Analyze current sentiment for {self.ticker}. "
                f"Consider company-specific news, analyst coverage, and how market sentiment affects this stock. "
                f"Compare to historical sentiment patterns and assess momentum."
            )
            
            # Store sentiment analysis
            await self._store_sentiment_analysis(sentiment_data, sentiment_analysis)
            
            logger.info(f"[{self.agent_id}] Sentiment analysis completed for {self.ticker}: {sentiment_analysis.get('sentiment_label', 'Unknown')}")
            
        except Exception as e:
            logger.error(f"[{self.agent_id}] Error in sentiment analysis cycle: {e}")
    
    async def _collect_stock_sentiment_data(self) -> Dict:
        """Collect sentiment-related data for this stock"""
        try:
            # Get current price and volatility context
            price_data = await self.memory.get_stock_price_history(7)
            
            # Get recent stock-specific memory for context
            stock_memory = await self.memory.get_stock_short_term_memory(5)
            
            # Get market sentiment context for comparison
            market_sentiment_context = await self.request_market_context('sentiment')
            
            # Get stock fundamentals for context
            fundamentals = await self.get_stock_fundamentals()
            sector = fundamentals.get('sector', 'Unknown')
            
            # For demonstration, create sentiment indicators based on available data
            # In production, you'd integrate with news APIs, social media APIs, etc.
            
            # Simulate sentiment based on price momentum and market context
            price_change_7d = price_data.get('price_change_pct', 0) if price_data else 0
            volatility = price_data.get('volatility', 15) if price_data else 15
            
            # Basic sentiment calculation based on available data
            base_sentiment = 0.0
            if price_change_7d > 5:
                base_sentiment += 0.3
            elif price_change_7d < -5:
                base_sentiment -= 0.3
                
            if volatility > 30:
                base_sentiment -= 0.2  # High volatility = negative sentiment
            
            # Get market context for relative sentiment
            market_sentiment_score = market_sentiment_context.get('market_sentiment_score', 5.0)
            market_bias = (market_sentiment_score - 5.0) / 5.0  # Convert to -1 to 1 scale
            
            sentiment_data = {
                'timestamp': datetime.utcnow().isoformat(),
                'ticker': self.ticker,
                'sector': sector,
                
                # Price and volatility context
                'price_data': price_data,
                'price_momentum_7d': price_change_7d,
                'volatility': volatility,
                
                # Market context
                'market_sentiment': market_sentiment_context,
                'market_bias': market_bias,
                
                # Calculated sentiment indicators
                'base_sentiment': base_sentiment,
                'estimated_news_sentiment': base_sentiment + (market_bias * 0.3),
                'estimated_analyst_sentiment': base_sentiment + (market_bias * 0.2),
                
                # Historical context
                'recent_sentiment_history': stock_memory.get('recent_sentiment', []),
                
                # Meta information
                'data_sources': ['price_data', 'market_sentiment', 'historical_analysis']
            }
            
            return sentiment_data
            
        except Exception as e:
            logger.error(f"Error collecting sentiment data for {self.ticker}: {e}")
            return {}
    
    async def _store_sentiment_analysis(self, sentiment_data: Dict, analysis: Dict):
        """Store sentiment analysis in database"""
        try:
            db = SessionLocal()
            
            sentiment_analysis = StockSentimentAnalysis(
                ticker=self.ticker,
                analysis_date=datetime.utcnow(),
                
                # Sentiment Scores
                overall_sentiment=analysis.get('overall_sentiment', 0.0),
                sentiment_label=analysis.get('sentiment_label', 'Neutral'),
                confidence_level=analysis.get('confidence_level', 0.5),
                
                # Sentiment Breakdown
                news_sentiment=analysis.get('news_sentiment', 0.0),
                analyst_sentiment=analysis.get('analyst_sentiment', 0.0),
                
                # Context Analysis
                vs_market_sentiment=analysis.get('vs_market_sentiment', 0.0),
                vs_sector_sentiment=analysis.get('vs_sector_sentiment', 0.0),
                sentiment_trend=analysis.get('sentiment_trend', 'Stable'),
                
                # Key Factors
                positive_factors=analysis.get('positive_factors', []),
                negative_factors=analysis.get('negative_factors', []),
                sentiment_drivers=analysis.get('sentiment_drivers', []),
                
                # Market Context
                market_sentiment_context=sentiment_data.get('market_sentiment', {}),
                
                # Agent Metadata
                agent_id=self.agent_id
            )
            
            db.add(sentiment_analysis)
            db.commit()
            
            logger.info(f"[{self.agent_id}] Stored sentiment analysis for {self.ticker}")
            
        except Exception as e:
            logger.error(f"Error storing sentiment analysis: {e}")
        finally:
            db.close()
    
    async def get_latest_sentiment(self) -> Dict:
        """Get latest sentiment analysis for this stock"""
        try:
            db = SessionLocal()
            
            latest_sentiment = db.query(StockSentimentAnalysis).filter(
                StockSentimentAnalysis.ticker == self.ticker
            ).order_by(StockSentimentAnalysis.analysis_date.desc()).first()
            
            if not latest_sentiment:
                return {'error': f'No sentiment analysis available for {self.ticker}'}
            
            return {
                'ticker': self.ticker,
                'analysis_date': latest_sentiment.analysis_date.isoformat(),
                'overall_sentiment': latest_sentiment.overall_sentiment,
                'sentiment_label': latest_sentiment.sentiment_label,
                'confidence_level': latest_sentiment.confidence_level,
                'sentiment_trend': latest_sentiment.sentiment_trend,
                'positive_factors': latest_sentiment.positive_factors,
                'negative_factors': latest_sentiment.negative_factors,
                'vs_market_sentiment': latest_sentiment.vs_market_sentiment
            }
            
        except Exception as e:
            logger.error(f"Error getting latest sentiment: {e}")
            return {'error': str(e)}
        finally:
            db.close() 