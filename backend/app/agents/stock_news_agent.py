"""
Stock News Agent

Analyzes news impact for specific stocks, filtering and processing 
company-specific news events and their market implications.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger

from .base_stock_agent import BaseStockAgent
from ..database import SessionLocal
from ..models import StockNewsAnalysis, MarketArticle


class StockNewsAgent(BaseStockAgent):
    """Agent specialized in analyzing news impact for specific stocks"""
    
    def __init__(self, ticker: str, agent_id: str = None):
        if not agent_id:
            agent_id = f"stock_news_{ticker.lower()}_001"
        
        specialized_prompt = f"""
You are a Stock News Analysis AI specializing in {ticker}.

Your role is to:
1. Identify and analyze {ticker}-specific news events
2. Assess the impact of news on {ticker}'s stock price and outlook
3. Categorize news by type (earnings, products, management, regulatory, etc.)
4. Determine time horizon of news impact (short/medium/long-term)
5. Compare {ticker} news context to broader market news

Focus on:
- Earnings announcements and guidance updates
- Product launches, partnerships, acquisitions
- Management changes and strategic announcements
- Regulatory developments affecting {ticker}
- Analyst upgrades/downgrades and price target changes
- Industry trends and competitive developments

Output Format (JSON):
{{
    "overall_news_impact": "Very Positive|Positive|Neutral|Negative|Very Negative",
    "impact_confidence": float (0-1),
    "time_horizon": "Short-term|Medium-term|Long-term",
    "major_events": [
        {{"event": "earnings beat", "impact": "positive", "date": "2024-01-15", "significance": 0.8}}
    ],
    "breaking_news": ["Recent breaking news items"],
    "earnings_updates": ["Earnings-related news"],
    "management_updates": ["Management and strategy news"],
    "news_sentiment_score": float (-1 to 1),
    "sentiment_trend": "Improving|Stable|Deteriorating",
    "key_themes": ["growth concerns", "margin expansion"],
    "risk_events": ["regulatory review", "competition threat"],
    "opportunity_events": ["new product launch", "market expansion"],
    "confidence": float (0-1),
    "finding_type": "stock_news_analysis"
}}

Be specific about {ticker} and focus on actionable news insights.
"""
        
        super().__init__(agent_id, "stock_news", ticker, specialized_prompt)
        
    async def run_cycle(self):
        """Main cycle for stock news analysis"""
        try:
            logger.info(f"[{self.agent_id}] Starting news analysis for {self.ticker}")
            
            # Collect news data for this stock
            news_data = await self._collect_stock_news_data()
            
            if not news_data:
                logger.warning(f"[{self.agent_id}] Insufficient news data for {self.ticker}")
                return
            
            # Analyze news with full context
            news_analysis = await self.analyze_with_full_context(
                news_data,
                f"Analyze recent news impact for {self.ticker}. "
                f"Identify significant events, assess their impact on stock price and business outlook. "
                f"Categorize news by type and determine market implications."
            )
            
            # Store news analysis
            await self._store_news_analysis(news_data, news_analysis)
            
            logger.info(f"[{self.agent_id}] News analysis completed for {self.ticker}: {news_analysis.get('overall_news_impact', 'Unknown')}")
            
        except Exception as e:
            logger.error(f"[{self.agent_id}] Error in news analysis cycle: {e}")
    
    async def _collect_stock_news_data(self) -> Dict:
        """Collect news-related data for this stock"""
        try:
            # Get recent stock-specific memory for context
            stock_memory = await self.memory.get_stock_short_term_memory(7)
            
            # Get market news context for comparison
            market_news_context = await self.request_market_context('news')
            
            # Get recent price data to correlate with news
            price_data = await self.memory.get_stock_price_history(14)
            
            # Get stock fundamentals for context
            fundamentals = await self.get_stock_fundamentals()
            sector = fundamentals.get('sector', 'Unknown')
            
            # Search for ticker-specific news in database
            db = SessionLocal()
            try:
                cutoff_date = datetime.utcnow() - timedelta(days=7)
                
                # Look for articles mentioning the ticker
                ticker_articles = db.query(MarketArticle).filter(
                    MarketArticle.published_at >= cutoff_date
                ).filter(
                    MarketArticle.title.contains(self.ticker.upper())
                ).order_by(MarketArticle.published_at.desc()).limit(10).all()
                
                # Format articles
                recent_articles = []
                for article in ticker_articles:
                    recent_articles.append({
                        'title': article.title,
                        'summary': article.summary,
                        'published_at': article.published_at.isoformat(),
                        'market_signal': article.market_signal,
                        'significance_score': article.significance_score,
                        'key_points': article.key_points
                    })
                
            finally:
                db.close()
            
            # Create simulated news events for demonstration
            # In production, this would integrate with real news APIs
            simulated_events = []
            
            # Generate events based on price movements
            price_change_7d = price_data.get('price_change_pct', 0) if price_data else 0
            
            if abs(price_change_7d) > 5:
                event_type = "positive earnings surprise" if price_change_7d > 0 else "earnings miss"
                impact = "positive" if price_change_7d > 0 else "negative"
                
                simulated_events.append({
                    'event': event_type,
                    'impact': impact,
                    'date': (datetime.utcnow() - timedelta(days=2)).isoformat(),
                    'significance': min(abs(price_change_7d) / 10, 1.0)
                })
            
            # Add industry news if available
            if sector != 'Unknown':
                simulated_events.append({
                    'event': f"{sector} sector developments",
                    'impact': "neutral",
                    'date': (datetime.utcnow() - timedelta(days=3)).isoformat(),
                    'significance': 0.4
                })
            
            news_data = {
                'timestamp': datetime.utcnow().isoformat(),
                'ticker': self.ticker,
                'sector': sector,
                
                # News articles
                'recent_articles': recent_articles,
                'articles_count': len(recent_articles),
                
                # Simulated events
                'simulated_events': simulated_events,
                
                # Price context for news correlation
                'price_data': price_data,
                'price_change_7d': price_change_7d,
                
                # Market context
                'market_news_context': market_news_context,
                'sector_news_context': market_news_context.get('sector_implications', {}).get(sector.lower(), 'neutral'),
                
                # Historical context
                'recent_news_history': stock_memory.get('recent_news', []),
                
                # Meta information
                'data_sources': ['market_articles', 'price_correlation', 'market_context']
            }
            
            return news_data
            
        except Exception as e:
            logger.error(f"Error collecting news data for {self.ticker}: {e}")
            return {}
    
    async def _store_news_analysis(self, news_data: Dict, analysis: Dict):
        """Store news analysis in database"""
        try:
            db = SessionLocal()
            
            news_analysis = StockNewsAnalysis(
                ticker=self.ticker,
                analysis_date=datetime.utcnow(),
                
                # News Impact Assessment
                overall_news_impact=analysis.get('overall_news_impact', 'Neutral'),
                impact_confidence=analysis.get('impact_confidence', 0.5),
                time_horizon=analysis.get('time_horizon', 'Medium-term'),
                
                # Key News Events
                major_events=analysis.get('major_events', []),
                breaking_news=analysis.get('breaking_news', []),
                earnings_updates=analysis.get('earnings_updates', []),
                management_updates=analysis.get('management_updates', []),
                
                # News Categorization
                positive_news_count=len([e for e in analysis.get('major_events', []) if e.get('impact') == 'positive']),
                negative_news_count=len([e for e in analysis.get('major_events', []) if e.get('impact') == 'negative']),
                neutral_news_count=len([e for e in analysis.get('major_events', []) if e.get('impact') == 'neutral']),
                
                # Sentiment Analysis
                news_sentiment_score=analysis.get('news_sentiment_score', 0.0),
                sentiment_trend=analysis.get('sentiment_trend', 'Stable'),
                
                # Market Context
                sector_news_context=news_data.get('sector_news_context', {}),
                broader_market_news_impact=news_data.get('market_news_context', {}),
                
                # Key Insights
                key_themes=analysis.get('key_themes', []),
                risk_events=analysis.get('risk_events', []),
                opportunity_events=analysis.get('opportunity_events', []),
                
                # Agent Metadata
                agent_id=self.agent_id,
                articles_analyzed=news_data.get('articles_count', 0),
                market_news_context=news_data.get('market_news_context', {})
            )
            
            db.add(news_analysis)
            db.commit()
            
            logger.info(f"[{self.agent_id}] Stored news analysis for {self.ticker}")
            
        except Exception as e:
            logger.error(f"Error storing news analysis: {e}")
        finally:
            db.close()
    
    async def get_latest_news_analysis(self) -> Dict:
        """Get latest news analysis for this stock"""
        try:
            db = SessionLocal()
            
            latest_news = db.query(StockNewsAnalysis).filter(
                StockNewsAnalysis.ticker == self.ticker
            ).order_by(StockNewsAnalysis.analysis_date.desc()).first()
            
            if not latest_news:
                return {'error': f'No news analysis available for {self.ticker}'}
            
            return {
                'ticker': self.ticker,
                'analysis_date': latest_news.analysis_date.isoformat(),
                'overall_news_impact': latest_news.overall_news_impact,
                'impact_confidence': latest_news.impact_confidence,
                'news_sentiment_score': latest_news.news_sentiment_score,
                'major_events': latest_news.major_events,
                'key_themes': latest_news.key_themes,
                'risk_events': latest_news.risk_events,
                'opportunity_events': latest_news.opportunity_events,
                'sentiment_trend': latest_news.sentiment_trend
            }
            
        except Exception as e:
            logger.error(f"Error getting latest news analysis: {e}")
            return {'error': str(e)}
        finally:
            db.close() 