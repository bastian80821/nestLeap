"""
Stock Fundamentals Agent

Analyzes fundamental metrics for specific stocks, including valuation,
growth, profitability, and competitive position within market context.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger

from .base_stock_agent import BaseStockAgent
from ..database import SessionLocal
from ..models import StockFundamentalsAnalysis


class StockFundamentalsAgent(BaseStockAgent):
    """Agent specialized in analyzing stock fundamentals"""
    
    def __init__(self, ticker: str, agent_id: str = None):
        if not agent_id:
            agent_id = f"stock_fundamentals_{ticker.lower()}_001"
        
        specialized_prompt = f"""
You are a Stock Fundamentals Analysis AI specializing in {ticker}.

Your role is to:
1. Analyze {ticker}'s financial health and valuation metrics
2. Assess growth prospects and profitability trends
3. Compare {ticker} to industry peers and market averages
4. Evaluate competitive position and business model strength
5. Consider macroeconomic impact on {ticker}'s fundamentals

Focus on:
- Valuation metrics (P/E, P/B, P/S, PEG ratio, EV/EBITDA)
- Growth metrics (revenue, earnings, free cash flow growth)
- Profitability (margins, ROE, ROA, ROIC)
- Financial health (debt levels, liquidity, cash flow)
- Competitive position and market share trends
- Economic sensitivity and cycle positioning

Output Format (JSON):
{{
    "revenue_growth": float (YoY percentage),
    "earnings_growth": float (YoY percentage),
    "profit_margins": float (net margin percentage),
    "debt_to_equity": float,
    "return_on_equity": float,
    "free_cash_flow": float,
    "current_pe": float,
    "forward_pe": float,
    "historical_pe_avg": float,
    "pe_vs_industry": float,
    "pe_vs_market": float,
    "revenue_growth_trend": "Accelerating|Stable|Decelerating",
    "earnings_consistency": float (0-1),
    "guidance_outlook": "Positive|Neutral|Negative",
    "market_share_trend": "Gaining|Stable|Losing",
    "competitive_advantages": ["moat1", "moat2"],
    "competitive_threats": ["threat1", "threat2"],
    "interest_rate_sensitivity": "High|Medium|Low",
    "fundamental_strengths": ["strength1", "strength2"],
    "fundamental_concerns": ["concern1", "concern2"],
    "valuation_conclusion": "Undervalued|Fair Value|Overvalued",
    "confidence": float (0-1),
    "finding_type": "stock_fundamentals_analysis"
}}

Be specific about {ticker} and provide actionable fundamental insights.
"""
        
        super().__init__(agent_id, "stock_fundamentals", ticker, specialized_prompt)
        
    async def run_cycle(self):
        """Main cycle for stock fundamentals analysis"""
        try:
            logger.info(f"[{self.agent_id}] Starting fundamentals analysis for {self.ticker}")
            
            # Collect fundamentals data for this stock
            fundamentals_data = await self._collect_stock_fundamentals_data()
            
            if not fundamentals_data:
                logger.warning(f"[{self.agent_id}] Insufficient fundamentals data for {self.ticker}")
                return
            
            # Analyze fundamentals with full context
            fundamentals_analysis = await self.analyze_with_full_context(
                fundamentals_data,
                f"Analyze {self.ticker}'s fundamental metrics and financial health. "
                f"Compare valuation to historical levels, industry peers, and market averages. "
                f"Assess growth prospects and competitive position within current economic context."
            )
            
            # Store fundamentals analysis
            await self._store_fundamentals_analysis(fundamentals_data, fundamentals_analysis)
            
            logger.info(f"[{self.agent_id}] Fundamentals analysis completed for {self.ticker}: {fundamentals_analysis.get('valuation_conclusion', 'Unknown')}")
            
        except Exception as e:
            logger.error(f"[{self.agent_id}] Error in fundamentals analysis cycle: {e}")
    
    async def _collect_stock_fundamentals_data(self) -> Dict:
        """Collect fundamentals-related data for this stock"""
        try:
            # Get stock fundamentals from yfinance
            fundamentals = await self.get_stock_fundamentals()
            
            # Get recent stock-specific memory for context
            stock_memory = await self.memory.get_stock_short_term_memory(30)
            
            # Get market fundamentals context for comparison
            market_fundamentals_context = await self.request_market_context('fundamentals')
            
            # Get recent price data for valuation context
            price_data = await self.memory.get_stock_price_history(90)
            
            # Calculate derived metrics
            current_price = price_data.get('current_price') if price_data else None
            market_cap = fundamentals.get('market_cap')
            
            # Calculate some basic derived metrics
            derived_metrics = {}
            
            if fundamentals.get('pe_ratio') and fundamentals.get('earnings_growth'):
                # PEG ratio calculation
                derived_metrics['calculated_peg'] = fundamentals['pe_ratio'] / max(fundamentals['earnings_growth'] * 100, 1)
            
            # Historical valuation context (simplified)
            pe_current = fundamentals.get('pe_ratio', 20)
            pe_historical_avg = pe_current * 0.9  # Simplified historical average
            
            # Industry comparison (simplified for demonstration)
            sector = fundamentals.get('sector', 'Technology')
            industry_pe_avg = {
                'Technology': 25,
                'Healthcare': 22,
                'Financial Services': 15,
                'Consumer Cyclical': 18,
                'Industrial': 20
            }.get(sector, 20)
            
            fundamentals_data = {
                'timestamp': datetime.utcnow().isoformat(),
                'ticker': self.ticker,
                'sector': sector,
                'industry': fundamentals.get('industry', 'Unknown'),
                
                # Current fundamentals
                'current_fundamentals': fundamentals,
                'derived_metrics': derived_metrics,
                
                # Valuation context
                'current_price': current_price,
                'pe_current': pe_current,
                'pe_historical_avg': pe_historical_avg,
                'industry_pe_avg': industry_pe_avg,
                'market_pe_avg': 20,  # Simplified market average
                
                # Growth context
                'price_performance_90d': price_data.get('price_change_pct', 0) if price_data else 0,
                'volatility_90d': price_data.get('volatility', 20) if price_data else 20,
                
                # Economic context
                'market_fundamentals_context': market_fundamentals_context,
                'economic_cycle': market_fundamentals_context.get('economic_cycle_stage', 'mid_cycle'),
                'interest_rate_environment': market_fundamentals_context.get('interest_rate_environment', 'neutral'),
                
                # Historical context
                'recent_fundamentals_history': stock_memory.get('recent_analysis', []),
                
                # Meta information
                'data_sources': ['yfinance', 'market_context', 'historical_analysis'],
                'data_quality': 'high' if fundamentals.get('pe_ratio') else 'medium'
            }
            
            return fundamentals_data
            
        except Exception as e:
            logger.error(f"Error collecting fundamentals data for {self.ticker}: {e}")
            return {}
    
    async def _store_fundamentals_analysis(self, fundamentals_data: Dict, analysis: Dict):
        """Store fundamentals analysis in database"""
        try:
            db = SessionLocal()
            
            fundamentals = fundamentals_data.get('current_fundamentals', {})
            
            fundamentals_analysis = StockFundamentalsAnalysis(
                ticker=self.ticker,
                analysis_date=datetime.utcnow(),
                
                # Financial Health
                revenue_growth=analysis.get('revenue_growth', fundamentals.get('revenue_growth')),
                earnings_growth=analysis.get('earnings_growth', fundamentals.get('earnings_growth')),
                profit_margins=analysis.get('profit_margins', fundamentals.get('profit_margins')),
                debt_to_equity=analysis.get('debt_to_equity', fundamentals.get('debt_to_equity')),
                return_on_equity=analysis.get('return_on_equity', fundamentals.get('return_on_equity')),
                free_cash_flow=fundamentals.get('free_cash_flow'),  # Total FCF from yfinance
                
                # Quarter Information
                latest_quarter_date=fundamentals.get('latest_quarter_date'),
                latest_quarter_label=fundamentals.get('latest_quarter_label'),
                latest_eps=fundamentals.get('latest_eps'),
                
                # Valuation Metrics
                current_pe=analysis.get('current_pe', fundamentals.get('pe_ratio')),
                forward_pe=analysis.get('forward_pe', fundamentals.get('forward_pe')),
                historical_pe_avg=analysis.get('historical_pe_avg', fundamentals_data.get('pe_historical_avg')),
                pe_vs_industry=analysis.get('pe_vs_industry'),
                pe_vs_market=analysis.get('pe_vs_market'),
                
                # Growth Analysis
                revenue_growth_trend=analysis.get('revenue_growth_trend', 'Stable'),
                earnings_consistency=analysis.get('earnings_consistency', 0.7),
                guidance_outlook=analysis.get('guidance_outlook', 'Neutral'),
                
                # Competitive Position
                market_share_trend=analysis.get('market_share_trend', 'Stable'),
                competitive_advantages=analysis.get('competitive_advantages', []),
                competitive_threats=analysis.get('competitive_threats', []),
                
                # Economic Context
                economic_impact_assessment=f"Analysis considering {fundamentals_data.get('economic_cycle')} economic environment",
                sector_fundamentals_context=fundamentals_data.get('market_fundamentals_context', {}),
                interest_rate_sensitivity=analysis.get('interest_rate_sensitivity', 'Medium'),
                
                # Key Insights
                fundamental_strengths=analysis.get('fundamental_strengths', []),
                fundamental_concerns=analysis.get('fundamental_concerns', []),
                valuation_conclusion=analysis.get('valuation_conclusion', 'Fair Value'),
                
                # Agent Metadata
                agent_id=self.agent_id,
                market_fundamentals_context=fundamentals_data.get('market_fundamentals_context', {}),
                data_quality_score=1.0 if fundamentals_data.get('data_quality') == 'high' else 0.8
            )
            
            db.add(fundamentals_analysis)
            db.commit()
            
            logger.info(f"[{self.agent_id}] Stored fundamentals analysis for {self.ticker}")
            
        except Exception as e:
            logger.error(f"Error storing fundamentals analysis: {e}")
        finally:
            db.close()
    
    async def get_latest_fundamentals_analysis(self) -> Dict:
        """Get latest fundamentals analysis for this stock"""
        try:
            db = SessionLocal()
            
            latest_fundamentals = db.query(StockFundamentalsAnalysis).filter(
                StockFundamentalsAnalysis.ticker == self.ticker
            ).order_by(StockFundamentalsAnalysis.analysis_date.desc()).first()
            
            if not latest_fundamentals:
                return {'error': f'No fundamentals analysis available for {self.ticker}'}
            
            return {
                'ticker': self.ticker,
                'analysis_date': latest_fundamentals.analysis_date.isoformat(),
                'revenue_growth': latest_fundamentals.revenue_growth,
                'earnings_growth': latest_fundamentals.earnings_growth,
                'valuation_conclusion': latest_fundamentals.valuation_conclusion,
                'current_pe': latest_fundamentals.current_pe,
                'pe_vs_industry': latest_fundamentals.pe_vs_industry,
                'competitive_advantages': latest_fundamentals.competitive_advantages,
                'competitive_threats': latest_fundamentals.competitive_threats,
                'fundamental_strengths': latest_fundamentals.fundamental_strengths,
                'fundamental_concerns': latest_fundamentals.fundamental_concerns,
                'interest_rate_sensitivity': latest_fundamentals.interest_rate_sensitivity
            }
            
        except Exception as e:
            logger.error(f"Error getting latest fundamentals analysis: {e}")
            return {'error': str(e)}
        finally:
            db.close() 