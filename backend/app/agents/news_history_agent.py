"""
News History Agent

Analyzes past news summaries to generate historical context and identify 
continuing themes, trends, and narrative continuity for current news analysis.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from loguru import logger

from .base_agent import BaseAgent
from ..database import SessionLocal
from ..models import MarketNewsSummary


class NewsHistoryAgent(BaseAgent):
    """Agent specialized in analyzing news history and providing context"""
    
    def __init__(self, agent_id: str = None):
        if not agent_id:
            agent_id = "news_history_001"
        
        specialized_prompt = """
You are a News History Analysis AI specializing in market narrative continuity.

Your role is to:
1. Analyze recent news summaries to identify continuing themes and trends
2. Track sentiment evolution over time (improving/deteriorating/stable)
3. Identify multi-day developing stories and persistent market concerns
4. Generate concise historical context for current news analysis
5. Provide narrative continuity between news cycles

Focus on:
- Persistent themes (Fed policy, inflation, earnings trends, geopolitical events)
- Sentiment trajectory (bearish trend strengthening, optimism fading, etc.)
- Developing stories that span multiple days
- Market regime changes and turning points
- Sector rotation patterns and thematic shifts

Output Format (JSON):
{
    "historical_context": "2-3 sentence summary of key themes and trends from recent summaries",
    "persistent_themes": ["theme1", "theme2", "theme3"],
    "sentiment_trend": "improving|deteriorating|stable|mixed",
    "developing_stories": ["story1", "story2"],
    "key_continuity_points": ["point1", "point2"],
    "context_timeframe": "timeframe covered (e.g., 'past 5 days')",
    "confidence": float (0-1),
    "finding_type": "news_history_analysis"
}

Generate context that helps current news analysis build narrative continuity and avoid repetitive themes.
"""
        
        super().__init__(agent_id, "news_history", specialized_prompt)
        
    async def generate_historical_context(self, days_back: int = 7) -> Dict:
        """Generate historical context from recent news summaries"""
        try:
            logger.info(f"[{self.agent_id}] Generating historical context from past {days_back} days")
            
            # Collect recent summaries
            historical_data = await self._collect_recent_summaries(days_back)
            
            if not historical_data or not historical_data.get('summaries'):
                logger.warning(f"[{self.agent_id}] Insufficient historical data")
                return {
                    "historical_context": "No recent market news history available for context.",
                    "persistent_themes": [],
                    "sentiment_trend": "unknown",
                    "developing_stories": [],
                    "key_continuity_points": [],
                    "context_timeframe": f"past {days_back} days",
                    "confidence": 0.0,
                    "status": "insufficient_data"
                }
            
            # Analyze with LLM
            analysis = await self.analyze_with_context(
                historical_data,
                f"Analyze the historical context from {len(historical_data['summaries'])} recent news summaries. "
                f"Identify continuing themes, sentiment trends, and developing stories. "
                f"Generate a concise 2-3 sentence historical context that will help current news analysis "
                f"build narrative continuity and avoid repetition."
            )
            
            if analysis and 'error' not in analysis:
                logger.info(f"[{self.agent_id}] Generated historical context: {analysis.get('historical_context', '')[:100]}...")
                return analysis
            else:
                logger.error(f"[{self.agent_id}] LLM analysis failed: {analysis}")
                return self._fallback_context(historical_data)
                
        except Exception as e:
            logger.error(f"[{self.agent_id}] Error generating historical context: {e}")
            return {
                "historical_context": "Historical context analysis temporarily unavailable.",
                "persistent_themes": [],
                "sentiment_trend": "unknown",
                "developing_stories": [],
                "key_continuity_points": [],
                "context_timeframe": f"past {days_back} days",
                "confidence": 0.0,
                "error": str(e)
            }
    
    async def _collect_recent_summaries(self, days_back: int) -> Dict:
        """Collect recent news summaries for analysis"""
        try:
            db = SessionLocal()
            
            # Get summaries from the specified time period
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
            recent_summaries = db.query(MarketNewsSummary).filter(
                MarketNewsSummary.created_at >= cutoff_date
            ).order_by(MarketNewsSummary.created_at.desc()).limit(10).all()
            
            logger.info(f"Found {len(recent_summaries)} summaries since {cutoff_date}")
            
            if not recent_summaries:
                logger.warning(f"No summaries found since {cutoff_date}")
                return {'summaries': [], 'count': 0}
            
            # Format summaries with timestamps
            formatted_summaries = []
            for summary in recent_summaries:
                formatted_summaries.append({
                    'summary': summary.summary,
                    'created_at': summary.created_at.isoformat(),
                    'days_ago': (datetime.now(timezone.utc) - summary.created_at).days,
                    'article_count': len(summary.article_ids) if summary.article_ids else 0
                })
            
            return {
                'summaries': formatted_summaries,
                'count': len(formatted_summaries),
                'timeframe': f"past {days_back} days",
                'oldest_summary': recent_summaries[-1].created_at.isoformat(),
                'newest_summary': recent_summaries[0].created_at.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error collecting recent summaries: {e}")
            return {'summaries': [], 'count': 0, 'error': str(e)}
        finally:
            db.close()
    
    def _fallback_context(self, historical_data: Dict) -> Dict:
        """Generate basic context when LLM analysis fails"""
        summaries = historical_data.get('summaries', [])
        if not summaries:
            return {
                "historical_context": "No recent market news context available.",
                "persistent_themes": [],
                "sentiment_trend": "unknown",
                "developing_stories": [],
                "key_continuity_points": [],
                "context_timeframe": historical_data.get('timeframe', 'recent days'),
                "confidence": 0.0,
                "status": "fallback"
            }
        
        # Basic analysis without LLM
        recent_summary = summaries[0]['summary'] if summaries else ""
        context = f"Based on {len(summaries)} recent summaries over {historical_data.get('timeframe', 'recent days')}, market themes continue to evolve."
        
        return {
            "historical_context": context,
            "persistent_themes": ["market_volatility", "policy_uncertainty"],
            "sentiment_trend": "mixed",
            "developing_stories": [],
            "key_continuity_points": [],
            "context_timeframe": historical_data.get('timeframe', 'recent days'),
            "confidence": 0.3,
            "status": "fallback"
        } 