"""
Stock News Agent V2 - Redesigned for deep article analysis
Uses CompanyNewsCollector to read and analyze full articles
Maintains persistent company summary like market news system
"""
from typing import Dict, Optional
from datetime import datetime
from loguru import logger

from .base_stock_agent import BaseStockAgent
from ..services.company_news_collector import CompanyNewsCollector
from ..database import SessionLocal
from ..models import StockNewsAnalysis


class StockNewsAgentV2(BaseStockAgent):
    """
    Analyzes company-specific news with deep article reading
    - Actually reads full article content (like market news does)
    - Maintains persistent company summary
    - Only updates when significant new information emerges
    - Provides earnings, risks, opportunities, and recent developments
    """
    
    def __init__(self, ticker: str, agent_id: str = None):
        if not agent_id:
            agent_id = f"stock_news_{ticker.lower()}_001"
        
        specialized_prompt = f"""
You are a Stock News Analysis AI specializing in {ticker}.
You read and analyze full news articles to maintain a comprehensive company profile.

Your role is to:
1. Read full article content (not just headlines)
2. Maintain a persistent company summary with earnings, risks, opportunities
3. Track product developments, management changes, regulatory issues
4. Update the summary only when materially new information emerges
5. Synthesize key worries and opportunities for investors
"""
        
        super().__init__(agent_id, "stock_news", ticker, specialized_prompt)
        self.news_collector = CompanyNewsCollector(ticker)
    
    async def run_cycle(self):
        """Main news analysis cycle - collects and analyzes news"""
        try:
            logger.info(f"[{self.agent_id}] Starting comprehensive news analysis for {self.ticker}")
            
            # Collect and analyze with deep article reading
            company_summary = await self.news_collector.collect_and_analyze(days_back=30)
            
            if not company_summary or not company_summary.get('company_summary'):
                logger.warning(f"[{self.agent_id}] No news data available for {self.ticker}")
                await self._store_empty_analysis()
                return
            
            # Store the comprehensive analysis
            await self._store_news_analysis(company_summary)
            
            logger.info(f"[{self.agent_id}] News analysis completed for {self.ticker}: {company_summary.get('articles_processed', 0)} articles processed")
            
        except Exception as e:
            logger.error(f"[{self.agent_id}] Error in news analysis cycle: {e}")
    
    async def get_latest_news_analysis(self) -> Dict:
        """Get latest comprehensive news analysis"""
        try:
            # Get latest analysis from database
            db = SessionLocal()
            try:
                latest = db.query(StockNewsAnalysis).filter(
                    StockNewsAnalysis.ticker == self.ticker
                ).order_by(StockNewsAnalysis.analysis_date.desc()).first()
                
                if not latest:
                    logger.warning(f"No stored analysis found for {self.ticker} - triggering new analysis")
                    # Trigger new analysis if none exists
                    await self.run_cycle()
                    
                    # Try again
                    latest = db.query(StockNewsAnalysis).filter(
                        StockNewsAnalysis.ticker == self.ticker
                    ).order_by(StockNewsAnalysis.analysis_date.desc()).first()
                    
                    if not latest:
                        return self._get_empty_response()
                
                # Format response
                return {
                    'ticker': self.ticker,
                    'analysis_date': latest.analysis_date.isoformat(),
                    
                    # Company Overview
                    'company_summary': latest.company_summary,
                    'recent_developments': latest.recent_developments_summary,
                    'outlook': latest.outlook,
                    
                    # Earnings
                    'latest_earnings': {
                        'date': latest.latest_earnings_date.isoformat() if latest.latest_earnings_date else None,
                        'result': latest.latest_earnings_result,
                        'summary': latest.latest_earnings_summary,
                        'eps_actual': latest.eps_actual,
                        'eps_expected': latest.eps_expected
                    },
                    
                    # Key Factors
                    'key_risks': latest.key_risks or [],
                    'key_opportunities': latest.key_opportunities or [],
                    'recent_products': latest.recent_product_developments or [],
                    'management_changes': latest.management_changes or [],
                    'regulatory_issues': latest.regulatory_issues or [],
                    'competitive_position': latest.competitive_position,
                    
                    # Sentiment
                    'news_sentiment_score': latest.news_sentiment_score,
                    'sentiment_trend': latest.sentiment_trend,
                    
                    # Metadata
                    'articles_analyzed': latest.articles_analyzed,
                    'last_updated': latest.last_significant_update.isoformat() if latest.last_significant_update else None
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error getting news analysis for {self.ticker}: {e}")
            return self._get_empty_response()
    
    async def _store_news_analysis(self, company_summary: Dict):
        """Store comprehensive news analysis in database"""
        try:
            db = SessionLocal()
            try:
                # Calculate sentiment from summary
                news_sentiment = await self._calculate_sentiment(company_summary)
                sentiment_trend = self._determine_sentiment_trend(company_summary)
                
                # Parse earnings date if available
                earnings_date = None
                if company_summary.get('latest_earnings', {}).get('date'):
                    try:
                        earnings_date = datetime.fromisoformat(company_summary['latest_earnings']['date'].replace('Z', ''))
                    except:
                        pass
                
                news_analysis = StockNewsAnalysis(
                    ticker=self.ticker,
                    analysis_date=datetime.utcnow(),
                    
                    # Company Overview (new fields)
                    company_summary=company_summary.get('company_summary'),
                    recent_developments_summary=company_summary.get('recent_developments'),
                    outlook=company_summary.get('outlook'),
                    
                    # Earnings Information
                    latest_earnings_date=earnings_date,
                    latest_earnings_result=company_summary.get('latest_earnings', {}).get('result'),
                    latest_earnings_summary=company_summary.get('latest_earnings', {}).get('summary'),
                    eps_actual=company_summary.get('latest_earnings', {}).get('eps_actual'),
                    eps_expected=company_summary.get('latest_earnings', {}).get('eps_expected'),
                    
                    # Key Factors
                    key_risks=company_summary.get('key_risks', []),
                    key_opportunities=company_summary.get('key_opportunities', []),
                    recent_product_developments=company_summary.get('recent_products', []),
                    management_changes=company_summary.get('management_changes', []),
                    regulatory_issues=company_summary.get('regulatory_issues', []),
                    competitive_position=company_summary.get('competitive_position'),
                    
                    # Sentiment
                    news_sentiment_score=news_sentiment,
                    sentiment_trend=sentiment_trend,
                    overall_news_impact=self._sentiment_to_label(news_sentiment),
                    
                    # Counts
                    positive_news_count=len([o for o in company_summary.get('key_opportunities', [])]),
                    negative_news_count=len([r for r in company_summary.get('key_risks', [])]),
                    
                    # Metadata
                    agent_id=self.agent_id,
                    articles_analyzed=company_summary.get('articles_processed', 0),
                    last_significant_update=datetime.fromisoformat(company_summary['last_updated']) if company_summary.get('last_updated') else datetime.utcnow(),
                    
                    # Legacy fields for compatibility
                    major_events=[],
                    breaking_news=[],
                    earnings_updates=[company_summary.get('latest_earnings', {}).get('summary', '')],
                    management_updates=company_summary.get('management_changes', []),
                    key_themes=company_summary.get('key_risks', []) + company_summary.get('key_opportunities', []),
                    risk_events=company_summary.get('key_risks', []),
                    opportunity_events=company_summary.get('key_opportunities', [])
                )
                
                db.add(news_analysis)
                db.commit()
                
                logger.info(f"[{self.agent_id}] Stored comprehensive news analysis for {self.ticker}")
                
            except Exception as e:
                db.rollback()
                logger.error(f"Error storing news analysis: {e}")
                raise
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error in _store_news_analysis: {e}")
    
    async def _store_empty_analysis(self):
        """Store empty analysis when no data available"""
        try:
            db = SessionLocal()
            try:
                news_analysis = StockNewsAnalysis(
                    ticker=self.ticker,
                    analysis_date=datetime.utcnow(),
                    company_summary=f'No news analysis available yet for {self.ticker}',
                    overall_news_impact='Neutral',
                    news_sentiment_score=0.0,
                    sentiment_trend='Stable',
                    articles_analyzed=0,
                    agent_id=self.agent_id,
                    major_events=[],
                    breaking_news=[],
                    earnings_updates=[],
                    management_updates=[],
                    key_themes=[],
                    risk_events=[],
                    opportunity_events=[]
                )
                
                db.add(news_analysis)
                db.commit()
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error storing empty analysis: {e}")
    
    async def _calculate_sentiment(self, company_summary: Dict) -> float:
        """
        Calculate overall sentiment from company summary
        Combines risks (negative) and opportunities (positive)
        """
        try:
            # Simple heuristic: more opportunities than risks = positive
            num_opportunities = len(company_summary.get('key_opportunities', []))
            num_risks = len(company_summary.get('key_risks', []))
            
            if num_opportunities == 0 and num_risks == 0:
                return 0.0
            
            # Range from -1 to 1
            total = num_opportunities + num_risks
            balance = (num_opportunities - num_risks) / total if total > 0 else 0.0
            
            # Adjust for earnings result if available
            earnings = company_summary.get('latest_earnings', {})
            if earnings.get('result') == 'Beat':
                balance += 0.2
            elif earnings.get('result') == 'Miss':
                balance -= 0.2
            
            return max(-1.0, min(1.0, balance))
            
        except Exception as e:
            logger.error(f"[{self.ticker}] Error calculating sentiment: {str(e)}")
            return 0.0
    
    def _determine_sentiment_trend(self, company_summary: Dict) -> str:
        """Determine if sentiment is improving, stable, or deteriorating"""
        # Check outlook for keywords
        outlook = company_summary.get('outlook', '').lower()
        
        if any(word in outlook for word in ['positive', 'growing', 'improving', 'strong', 'bullish']):
            return 'Improving'
        elif any(word in outlook for word in ['negative', 'declining', 'concerning', 'weak', 'bearish']):
            return 'Deteriorating'
        else:
            return 'Stable'
    
    def _sentiment_to_label(self, sentiment: float) -> str:
        """Convert sentiment score to label"""
        if sentiment >= 0.5:
            return 'Very Positive'
        elif sentiment >= 0.2:
            return 'Positive'
        elif sentiment <= -0.5:
            return 'Very Negative'
        elif sentiment <= -0.2:
            return 'Negative'
        else:
            return 'Neutral'
    
    def _get_empty_response(self) -> Dict:
        """Return empty response structure"""
        return {
            'ticker': self.ticker,
            'company_summary': 'No news analysis available yet',
            'recent_developments': None,
            'outlook': None,
            'latest_earnings': {},
            'key_risks': [],
            'key_opportunities': [],
            'recent_products': [],
            'management_changes': [],
            'regulatory_issues': [],
            'competitive_position': None,
            'news_sentiment_score': 0.0,
            'sentiment_trend': 'Stable',
            'articles_analyzed': 0,
            'last_updated': None
        }
