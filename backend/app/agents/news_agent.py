"""
Market News Agent

Analyzes market-wide news impact, identifies significant events,
and generates market intelligence from news sources.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger

from .base_agent import BaseAgent
from ..database import SessionLocal
from ..models import MarketArticle, MarketNewsSummary


class NewsAgent(BaseAgent):
    """Agent specialized in analyzing market news impact"""
    
    def __init__(self, agent_id: str = None):
        if not agent_id:
            agent_id = "market_news_001"
        
        specialized_prompt = """
You are a Market News Analyst providing clear, actionable insights for long-term investors.

Your job: Summarize today's key market news and explain what it means for the broader investment landscape over the next 6-12 months.

Focus on:
- What happened today (key events, earnings, policy changes, major announcements)
- What this means for long-term trends and themes
- Which sectors or industries are affected
- What investors should watch going forward

DO NOT:
- Predict short-term price movements or rallies
- Mention specific index levels or percentage moves
- Reference technical indicators or market timing
- Quote article counts, sentiment scores, or system details
- Focus on day-to-day volatility

Output Format (JSON):
{
    "overall_news_impact": "Very Positive|Positive|Neutral|Negative|Very Negative",
    "major_events": ["event1", "event2", "event3"],
    "key_themes": ["theme1", "theme2"],
    "sector_impacts": {"Technology": "positive", "Healthcare": "neutral"},
    "market_implications": "2-3 paragraph summary written for investors: What happened today? What does it mean for long-term investors? What should they watch? Write in clear, accessible language.",
    "confidence": float (0-1),
    "finding_type": "market_news_analysis"
}

Example market_implications (good):
"Major tech companies reported strong earnings this quarter, highlighting resilient consumer demand for AI-enabled products. This reinforces the long-term growth narrative for the sector. Federal Reserve commentary suggested patience on rate cuts, which favors quality companies with strong balance sheets. Investors should monitor upcoming inflation data and corporate guidance for Q4, as these will shape the investment landscape heading into 2026."

Example market_implications (bad):
"Across 15 articles with an average sentiment of 0.68, markets may see a short-term rally. The S&P 500 is up 1.2% today. RSI indicates oversold conditions."
"""
        
        super().__init__(agent_id, "market_news", specialized_prompt)
        
    async def run_cycle(self):
        """Main cycle for market news analysis"""
        try:
            logger.info(f"[{self.agent_id}] Starting market news analysis")
            
            # Get historical context from past summaries (for narrative continuity)
            historical_context = await self._get_historical_context()
            
            # Collect news data
            news_data = await self._collect_market_news_data()
            
            if not news_data:
                logger.warning(f"[{self.agent_id}] Insufficient news data")
                return
            
            # Add historical context to news data
            news_data['historical_context'] = historical_context
            
            # Analyze news with context
            task_description = (
                "Summarize today's key market news for long-term investors:\n\n"
                "1. What are the major events? (Specific companies, sectors, policy changes)\n"
                "2. What does this mean for the 6-12 month outlook? (Not short-term rallies)\n"
                "3. Which long-term themes or trends does this reinforce or challenge?\n"
                "4. What should investors watch going forward?\n\n"
                "Write in clear, accessible language. Focus on substance, not sentiment scores or technical details."
            )
            
            # Add historical context as brief background (if available)
            if historical_context and historical_context.get('historical_context'):
                task_description += (
                    f"\n\n[Recent context for reference]: {historical_context['historical_context']}\n"
                    f"Use this only to identify if today represents a continuation, reversal, or new development."
                )
            
            news_analysis = await self.analyze_with_context(news_data, task_description)
            
            # Store news analysis findings
            await self._store_news_analysis(news_data, news_analysis)
            
            logger.info(f"[{self.agent_id}] Market news analysis completed: {news_analysis.get('overall_news_impact', 'Unknown')}")
            
        except Exception as e:
            logger.error(f"[{self.agent_id}] Error in news analysis cycle: {e}")
    
    async def _get_historical_context(self, days_back: int = 5) -> Dict:
        """Get historical context from past news summaries"""
        try:
            from .news_history_agent import NewsHistoryAgent
            
            logger.info(f"[{self.agent_id}] Fetching historical context from past {days_back} days")
            
            # Create history agent instance
            history_agent = NewsHistoryAgent()
            
            # Generate historical context
            context = await history_agent.generate_historical_context(days_back)
            
            if context and 'error' not in context:
                logger.info(f"[{self.agent_id}] Historical context: {context.get('historical_context', '')[:80]}...")
                return context
            else:
                logger.warning(f"[{self.agent_id}] Could not generate historical context")
                return {}
                
        except Exception as e:
            logger.error(f"[{self.agent_id}] Error getting historical context: {e}")
            return {}
    
    async def _collect_market_news_data(self) -> Dict:
        """Collect and process market news data"""
        try:
            # Get recent market articles from database
            db = SessionLocal()
            
            # Get articles from last 24 hours
            recent_articles = db.query(MarketArticle).filter(
                MarketArticle.published_at >= datetime.utcnow() - timedelta(hours=24)
            ).order_by(MarketArticle.published_at.desc()).limit(20).all()
            
            # Get latest news summary
            latest_summary = db.query(MarketNewsSummary).order_by(
                MarketNewsSummary.created_at.desc()
            ).first()
            
            # Get historical news context
            historical_articles = db.query(MarketArticle).filter(
                MarketArticle.published_at >= datetime.utcnow() - timedelta(days=7),
                MarketArticle.published_at < datetime.utcnow() - timedelta(hours=24)
            ).order_by(MarketArticle.published_at.desc()).limit(30).all()
            
            db.close()
            
            # Process recent articles
            processed_articles = []
            for article in recent_articles:
                processed_articles.append({
                    'title': article.title,
                    'summary': getattr(article, 'ai_summary', '') or article.summary or '',
                    'source': article.source,
                    'published_at': article.published_at.isoformat(),
                    'sentiment': getattr(article, 'sentiment', 'neutral'),
                    'market_impact': getattr(article, 'market_impact', 0.5),
                    'key_points': getattr(article, 'key_points', []),
                    'affected_sectors': getattr(article, 'affected_sectors', [])
                })
            
            # Analyze article themes and sentiment
            sentiment_scores = [a.get('market_impact', 0.5) for a in processed_articles if a.get('market_impact') is not None]
            avg_sentiment = sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0.5
            
            # Identify major themes
            all_key_points = []
            for article in processed_articles:
                if article.get('key_points'):
                    all_key_points.extend(article['key_points'])
            
            news_data = {
                'timestamp': datetime.utcnow().isoformat(),
                
                # Recent News Analysis
                'recent_articles': processed_articles,
                'total_articles': len(processed_articles),
                'avg_sentiment_score': avg_sentiment,
                'sentiment_distribution': self._analyze_sentiment_distribution(processed_articles),
                
                # Latest Summary
                'latest_summary': latest_summary.summary if latest_summary else None,
                'summary_created_at': latest_summary.created_at.isoformat() if latest_summary else None,
                
                # Key Themes
                'key_themes': self._extract_key_themes(all_key_points),
                'affected_sectors': self._analyze_sector_mentions(processed_articles),
                
                # Historical Context
                'historical_article_count': len(historical_articles),
                'news_volume_trend': 'increasing' if len(recent_articles) > len(historical_articles) / 7 else 'stable',
                
                # Data Quality
                'data_sources': ['market_articles', 'news_summaries'],
                'data_quality': 'high' if len(processed_articles) >= 5 else 'medium'
            }
            
            return news_data
            
        except Exception as e:
            logger.error(f"Error collecting market news data: {e}")
            return {}
    
    def _analyze_sentiment_distribution(self, articles: List[Dict]) -> Dict:
        """Analyze sentiment distribution across articles"""
        try:
            positive_count = len([a for a in articles if a.get('market_impact', 0.5) > 0.6])
            negative_count = len([a for a in articles if a.get('market_impact', 0.5) < 0.4])
            neutral_count = len(articles) - positive_count - negative_count
            
            total = len(articles) if articles else 1
            
            return {
                'positive': positive_count / total,
                'neutral': neutral_count / total,
                'negative': negative_count / total,
                'total_articles': total
            }
        except Exception:
            return {'positive': 0.33, 'neutral': 0.34, 'negative': 0.33, 'total_articles': 0}
    
    def _extract_key_themes(self, key_points: List[str]) -> List[str]:
        """Extract key themes from article key points"""
        try:
            # Simple theme extraction based on common keywords
            themes = []
            theme_keywords = {
                'earnings': ['earnings', 'revenue', 'profit', 'guidance'],
                'fed_policy': ['fed', 'interest rate', 'monetary policy', 'powell'],
                'geopolitical': ['china', 'trade', 'tariff', 'war', 'conflict'],
                'tech': ['ai', 'technology', 'artificial intelligence', 'chip'],
                'energy': ['oil', 'energy', 'crude', 'natural gas'],
                'inflation': ['inflation', 'cpi', 'prices', 'cost']
            }
            
            text_content = ' '.join(key_points).lower()
            
            for theme, keywords in theme_keywords.items():
                if any(keyword in text_content for keyword in keywords):
                    themes.append(theme)
            
            return themes[:5]  # Limit to top 5 themes
        except Exception:
            return []
    
    def _analyze_sector_mentions(self, articles: List[Dict]) -> Dict:
        """Analyze which sectors are mentioned most in news"""
        try:
            sector_mentions = {}
            
            for article in articles:
                affected_sectors = article.get('affected_sectors', [])
                for sector in affected_sectors:
                    sector_mentions[sector] = sector_mentions.get(sector, 0) + 1
            
            return sector_mentions
        except Exception:
            return {}
    
    async def _store_news_analysis(self, news_data: Dict, analysis: Dict):
        """Store news analysis as MarketNewsSummary (single source of truth for all consumers)"""
        try:
            db = SessionLocal()
            
            # Build a readable summary from the LLM analysis
            summary_text = f"{analysis.get('market_implications', '')}".strip()
            if not summary_text:
                summary_text = f"Market news shows {analysis.get('overall_news_impact', 'neutral')} impact. "
                if analysis.get('major_events'):
                    summary_text += f"Major events: {', '.join(analysis.get('major_events', [])[:3])}."
            
            # Create MarketNewsSummary (consumed by frontend AND other agents via request_market_context)
            news_summary = MarketNewsSummary(
                summary=summary_text,
                article_ids=None  # Optional field
            )
            db.add(news_summary)
            db.commit()
            db.close()
            
            logger.info(f"✅ Stored MarketNewsSummary: {analysis.get('overall_news_impact', 'Unknown')}")
            
        except Exception as e:
            logger.error(f"Error storing news summary: {e}")
            if 'db' in locals():
                db.rollback()
                db.close() 