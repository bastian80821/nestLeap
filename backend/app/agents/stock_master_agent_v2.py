"""
Stock Master Agent (Redesigned)

Synthesizes technical analysis, news analysis, and market context
to provide comprehensive stock recommendations.
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger

from .base_stock_agent import BaseStockAgent
from .stock_technical_agent import StockTechnicalAgent
from .stock_news_agent_v2 import StockNewsAgentV2
from .stock_fundamentals_agent import StockFundamentalsAgent
from ..database import SessionLocal
from ..models import (
    StockAnalysis, StockTechnicalAnalysis, StockNewsAnalysis,
    StockFundamentalsAnalysis, StockTimeSeries
)
from ..services.stock_data_collector import StockDataCollector


class StockMasterAgentV2(BaseStockAgent):
    """Master agent that synthesizes all stock analysis"""
    
    def __init__(self, ticker: str, agent_id: str = None):
        if not agent_id:
            agent_id = f"stock_master_{ticker.lower()}_001"
        
        specialized_prompt = f"""
You are a Master Stock Analysis AI specializing in {ticker}. You synthesize FUNDAMENTALS, news analysis, technical patterns, and market context to provide comprehensive investment recommendations.

CRITICAL: You are the MASTER ANALYST. You determine valuation by ANALYZING fundamentals yourself.

IMPORTANT TEMPORAL CONTEXT:
- You will receive 'analysis_date' and 'current_quarter' (e.g., "2025-11-13", "Q4 2025")
- You will receive 'latest_quarter_label' for most recent reported earnings (e.g., "Q3 2024")
- ONLY reference quarters/earnings that have already been reported (are in the PAST)
- DO NOT mention future quarters or upcoming earnings unless explicitly discussing guidance/expectations
- When stating "recent" or "latest" earnings, use the 'latest_quarter_label' provided

Analysis Priority (Most to Least Important):
1. FUNDAMENTALS (PE vs peers, growth rates, margins, ROE, debt, cash flow) → YOU determine valuation from this
2. MARKET CONTEXT (economic cycle, sector trends) → Contextualizes fundamentals
3. NEWS (earnings, products, risks, opportunities) → Recent catalysts and risks
4. TECHNICALS (RSI, support/resistance) → Entry/exit timing ONLY

Your Methodology:
1. ANALYZE fundamentals with CONTEXT:
   - Current PE vs Historical PE Average for THIS stock
   - PE vs Industry - does this stock historically trade at premium/discount?
   - WHY premium exists (brand, CEO, innovation, market position)
   - Growth rate (PEG ratio) - does growth justify the premium?
   - Margins, ROE, debt levels

2. CALCULATE fair value and thresholds (ALL THREE NUMBERS ARE MANDATORY):
   - Start with historical_pe_avg (what THIS stock normally trades at)
   - Adjust based on current growth vs historical growth
   - Adjust for margin trends (improving = higher multiple, declining = lower)
   - Adjust for sector multiples IF stock changed categories (e.g., auto → tech)
   - Consider forward PE vs current PE (compression = concerns, expansion = optimism)
   - SET fair_value_price: YOUR calculated fair value (e.g., if current $350, fair might be $340)
   
   LONG-TERM INVESTOR THRESHOLDS (for infrequent trading):
   - SET buy_below: Fair value - 15-20% (significant discount for entry)
   - SET sell_above: Fair value + 30-40% (significant premium to lock in gains)
   - This creates a 50-60% range where you HOLD (between buy and sell thresholds)
   - Example: Fair=$340 → buy_below=$272-289 (20% off), sell_above=$442-476 (30-40% premium)
   
3. EXAMPLE - Stock with premium multiple:
   - Historical PE: 80x, Current: 90x, Industry: 20x
   - Stock historically trades 4x above industry (brand/innovation premium)
   - If growth 30%+ → premium justified, fair value near current
   - If growth <10% → premium eroding, fair value toward 60-70x (historical avg minus discount)

4. NEVER use technical resistance/support as fair value
5. USE technicals only for entry/exit timing, not valuation

Output Format (JSON) - Generate these specific sections:
{{
    "valuation_assessment": "Undervalued|Fair Value|Overvalued" 
        STRICT THRESHOLDS based on (current_price - fair_value) / fair_value:
        - Undervalued: current price < fair_value * 0.90 (more than 10% below)
        - Fair Value: fair_value * 0.90 <= current price <= fair_value * 1.10 (within ±10%)
        - Overvalued: current price > fair_value * 1.10 (more than 10% above)
        Example: Fair value $324, current $340 → +4.9% → "Fair Value" (NOT Overvalued),
    
    "fair_value_price": float (MANDATORY NUMBER - calculate from fundamentals, e.g., 340.50),
    "buy_below": float (MANDATORY NUMBER - fair_value_price minus 15-20% for long-term entry, e.g., 272-289),
    "sell_above": float (MANDATORY NUMBER - fair_value_price plus 30-40% for significant gains, e.g., 442-476),
    
    "company_description": "2-3 sentences describing what the company does, its market position, and business model",
    
    "analysis": "Comprehensive 3-4 sentence analysis combining: 1) Why current valuation (overvalued/undervalued) in plain language - focus on if growth justifies premium, margin trends, competitive position vs peers, 2) Recent developments from news (earnings, products, management changes), 3) Why stock is at current price level. CRITICAL: DO NOT mention your calculated fair value number, PE multiples, or calculation methodology - these are shown separately. Write in accessible language for investors, not technical analysis jargon.",
    
    "forward_outlook": "2-3 sentences on future prospects based on: 1) Earnings growth trajectory, 2) Industry trends, 3) Competitive position, 4) Upcoming catalysts",
    
    "risk_factors": [
        "Clear description of fundamental/business risk (e.g., High debt levels could limit growth flexibility)",
        "Clear description of market/regulatory risk (e.g., New regulations may impact profitability)",
        "Clear description of operational risk (e.g., Supply chain disruptions pose near-term challenges)"
    ],
    
    "catalysts": [
        "Clear description of fundamental catalyst (e.g., Accelerating earnings growth driven by margin expansion)",
        "Clear description of business catalyst (e.g., New product launch expected to capture 15% market share)",
        "Clear description of market catalyst (e.g., Industry tailwinds from increased AI adoption)"
    ],
    
    "market_comparison": "2-3 sentences on: 1) How the stock has performed vs S&P 500 over the last month (e.g., outperformed by 5% or underperformed by 3%), 2) Competitive positioning within its industry (market leader, challenger, niche player), 3) Key competitors worth comparing (e.g., 'Main competitors include X and Y, which offer similar exposure' OR 'Best-in-class in this space').",
    
    "technical_rating": "Bullish|Bearish|Neutral (for timing only)",
    "support_level": float (timing reference),
    "resistance_level": float (timing reference),
    
    "confidence": float (0-1),
    "finding_type": "stock_master_analysis"
}}

Be specific and reference actual data points. Provide actionable recommendations.

IMPORTANT: Write risk_factors and catalysts as clean, readable sentences. DO NOT use field prefixes like "valuation_sustainability:", "market_sentiment:", "aip_expansion:", etc. Just write clear descriptive sentences.
"""
        
        super().__init__(agent_id, "stock_master", ticker, specialized_prompt)
        self.data_collector = StockDataCollector()
        
    async def run_cycle(self):
        """Main master analysis cycle"""
        try:
            logger.info(f"[{self.agent_id}] Starting master analysis for {self.ticker}")
            
            # Clear cached fundamentals to force fresh calculation
            if self.ticker in BaseStockAgent._fundamentals_cache:
                del BaseStockAgent._fundamentals_cache[self.ticker]
                logger.info(f"[{self.agent_id}] Cleared cached fundamentals for {self.ticker}")
            
            # Trigger sub-agents to generate fresh analysis
            await self._trigger_sub_agents()
            
            # Collect comprehensive data
            comprehensive_data = await self._collect_comprehensive_data()
            
            if not comprehensive_data or not comprehensive_data.get('has_sufficient_data'):
                logger.warning(f"[{self.agent_id}] Insufficient data for {self.ticker}")
                return
            
            # Perform master synthesis
            current_price = comprehensive_data.get('current_price', 0)
            fundamentals_basic = comprehensive_data.get('fundamentals_basic', {})
            fundamentals_analysis = comprehensive_data.get('fundamentals_analysis', {})
            
            pe_ratio = fundamentals_basic.get('pe_ratio', 'N/A')
            forward_pe = fundamentals_basic.get('forward_pe', 'N/A')
            historical_pe = fundamentals_analysis.get('historical_pe_avg', 'N/A')
            pe_vs_industry = fundamentals_analysis.get('pe_vs_industry', 'N/A')
            profit_margin = fundamentals_basic.get('profit_margins', 'N/A')
            revenue_growth = fundamentals_basic.get('revenue_growth', 'N/A')
            sector = fundamentals_basic.get('sector', 'N/A')
            industry = fundamentals_basic.get('industry', 'N/A')
            
            master_analysis = await self.analyze_with_full_context(
                comprehensive_data,
                f"Perform comprehensive analysis for {self.ticker}.\n\n"
                f"Current Market Data:\n"
                f"- Price: ${current_price:.2f}\n"
                f"- Current PE: {pe_ratio}\n"
                f"- Forward PE: {forward_pe}\n"
                f"- Historical PE Avg: {historical_pe} (what THIS stock normally trades at)\n"
                f"- PE vs Industry: {pe_vs_industry} (premium/discount to industry)\n"
                f"- Sector/Industry: {sector} / {industry}\n"
                f"- Profit Margin: {profit_margin}\n"
                f"- Revenue Growth: {revenue_growth}\n\n"
                f"YOUR TASK - SMART VALUATION:\n"
                f"1. UNDERSTAND the stock's historical valuation:\n"
                f"   - Does it trade at premium to industry? WHY? (brand, CEO, innovation, market position)\n"
                f"   - Is current PE above/below historical average?\n"
                f"   - Has the business changed (e.g., auto → tech/AI)?\n\n"
                f"2. DETERMINE fair value intelligently:\n"
                f"   - Start with historical_pe_avg (baseline for THIS stock)\n"
                f"   - Adjust UP if: growth accelerating, margins improving, new business lines\n"
                f"   - Adjust DOWN if: growth decelerating, margins compressing, competitive threats\n"
                f"   - Forward PE vs Current PE shows market expectations (compression = concern)\n"
                f"   - PEG ratio: Is growth rate justifying the PE multiple?\n\n"
                f"3. EXAMPLE:\n"
                f"   - Historical PE: 80x, Current: 312x, Industry: 18x\n"
                f"   - Stock always traded at premium (let's say historical 4-5x industry)\n"
                f"   - But 312x / 18x = 17x industry (way above historical premium!)\n"
                f"   - Growth: -37% (declining!) → premium NOT justified\n"
                f"   - Fair value: Maybe 50-60x PE (higher than industry due to brand, but way below current)\n\n"
                f"4. SET buy/sell thresholds (MANDATORY - YOU MUST PROVIDE ALL THREE NUMBERS):\n"
                f"   LONG-TERM INVESTOR PERSPECTIVE (hold for significant moves):\n"
                f"   - fair_value_price: Your calculated fair value price (e.g., $277.00)\n"
                f"   - buy_below: Fair value - 15-20% for attractive entry (e.g., if fair=$277, buy_below=$222-235)\n"
                f"   - sell_above: Fair value + 30-40% to lock in gains (e.g., if fair=$277, sell_above=$360-388)\n"
                f"   - Hold zone: Between buy_below and sell_above (e.g., $222-388 = 75% range)\n"
                f"   Example: Fair=$277 → buy_below=$235 (15% off), sell_above=$360 (30% premium)\n\n"
                f"5. WRITE analysis sections:\n"
                f"   - Explain WHY stock is over/undervalued in plain language (growth vs premium, margins, competitive position)\n"
                f"   - Mention recent developments (earnings, products, management)\n"
                f"   - Explain current price level\n"
                f"   - DO NOT mention calculated fair value numbers or PE calculation methodology in the text\n\n"
                f"Use the actual data provided. Be realistic about growth vs valuation.\n\n"
                f"REQUIRED JSON OUTPUT (ALL FIELDS MANDATORY - only generate fields that are displayed):\n"
                f"{{\n"
                f'  "valuation_assessment": "Undervalued" | "Fair Value" | "Overvalued",\n'
                f'  "fair_value_price": 123.45,\n'
                f'  "buy_below": 100.00,\n'
                f'  "sell_above": 150.00,\n'
                f'  "company_description": "2-3 sentence overview of what the company does",\n'
                f'  "analysis": "3-4 paragraphs explaining investment thesis, recent developments, and why current price",\n'
                f'  "forward_outlook": "2-3 paragraphs on future prospects and growth drivers",\n'
                f'  "market_comparison": "2 paragraphs on performance vs S&P 500 last month, competitive position, key competitors",\n'
                f'  "risk_factors": ["Risk 1 description", "Risk 2 description", "Risk 3 description"],\n'
                f'  "catalysts": ["Catalyst 1 description", "Catalyst 2 description", "Catalyst 3 description"]\n'
                f"}}\n\n"
                f"DO NOT include: overall_rating, confidence_score, upside_potential, or key_insights (these are not displayed)"
            )
            
            # Store comprehensive analysis
            await self._store_master_analysis(comprehensive_data, master_analysis)
            
            logger.info(f"[{self.agent_id}] Master analysis completed: {master_analysis.get('valuation_assessment', 'N/A')}")
            
        except Exception as e:
            logger.error(f"[{self.agent_id}] Error in master analysis: {e}")
    
    async def _trigger_sub_agents(self):
        """Trigger fundamentals, news, and technical agents (in priority order)"""
        try:
            logger.info(f"[{self.agent_id}] Triggering sub-agents for {self.ticker}")
            
            # Initialize agents
            fundamentals_agent = StockFundamentalsAgent(self.ticker)
            news_agent = StockNewsAgentV2(self.ticker)
            technical_agent = StockTechnicalAgent(self.ticker)
            
            # Run in sequence (priority order: fundamentals -> news -> technical)
            await fundamentals_agent.run_cycle()
            await news_agent.run_cycle()
            await technical_agent.run_cycle()
            
            logger.info(f"[{self.agent_id}] Sub-agents completed")
            
        except Exception as e:
            logger.error(f"Error triggering sub-agents: {e}")
    
    async def _collect_comprehensive_data(self) -> Dict:
        """Collect all analysis data"""
        try:
            db = SessionLocal()
            try:
                # Get latest technical analysis
                latest_technical = db.query(StockTechnicalAnalysis).filter(
                    StockTechnicalAnalysis.ticker == self.ticker
                ).order_by(StockTechnicalAnalysis.analysis_date.desc()).first()
                
                # Get latest news analysis
                latest_news = db.query(StockNewsAnalysis).filter(
                    StockNewsAnalysis.ticker == self.ticker
                ).order_by(StockNewsAnalysis.analysis_date.desc()).first()
                
                # Get latest fundamentals analysis
                latest_fundamentals = db.query(StockFundamentalsAnalysis).filter(
                    StockFundamentalsAnalysis.ticker == self.ticker
                ).order_by(StockFundamentalsAnalysis.analysis_date.desc()).first()
                
                # Get latest price data
                latest_price = db.query(StockTimeSeries).filter(
                    StockTimeSeries.ticker == self.ticker
                ).order_by(StockTimeSeries.date.desc()).first()
                
                if not latest_price:
                    logger.warning(f"No price data found for {self.ticker}")
                    return {'has_sufficient_data': False}
                
                # Get fundamentals
                fundamentals = await self.get_stock_fundamentals()
                
                # Get market context
                market_sentiment = await self.request_market_context('sentiment')
                market_news = await self.request_market_context('news')
                market_fundamentals = await self.request_market_context('fundamentals')
                
                comprehensive_data = {
                    'timestamp': datetime.utcnow().isoformat(),
                    'ticker': self.ticker,
                    'has_sufficient_data': True,
                    
                    # Current Price Data
                    'current_price': latest_price.close_price,
                    'latest_date': latest_price.date.isoformat(),
                    
                    # Technical Analysis
                    'technical_analysis': {
                        'available': latest_technical is not None,
                        'trend_direction': latest_technical.trend_direction if latest_technical else None,
                        'trend_strength': latest_technical.trend_strength if latest_technical else None,
                        'support_level': latest_technical.support_level_1 if latest_technical else None,
                        'resistance_level': latest_technical.resistance_level_1 if latest_technical else None,
                        'momentum_score': latest_technical.momentum_score if latest_technical else None,
                        'rsi_assessment': latest_technical.rsi_assessment if latest_technical else None,
                        'volatility_level': latest_technical.volatility_level if latest_technical else None,
                        'technical_summary': latest_technical.technical_summary if latest_technical else None,
                        'short_term_outlook': latest_technical.short_term_outlook if latest_technical else None,
                        'vs_market_performance': latest_technical.vs_market_performance if latest_technical else None,
                    },
                    
                    # News Analysis
                    'news_analysis': {
                        'available': latest_news is not None,
                        'overall_impact': latest_news.overall_news_impact if latest_news else None,
                        'sentiment_score': latest_news.news_sentiment_score if latest_news else 0.0,
                        'sentiment_trend': latest_news.sentiment_trend if latest_news else None,
                        'major_events': latest_news.major_events if latest_news else [],
                        'risk_events': latest_news.risk_events if latest_news else [],
                        'opportunity_events': latest_news.opportunity_events if latest_news else [],
                        'articles_analyzed': latest_news.articles_analyzed if latest_news else 0,
                        'company_summary': latest_news.company_summary if latest_news else None,
                        'recent_developments': latest_news.recent_developments_summary if latest_news else None,
                        'latest_earnings_summary': latest_news.latest_earnings_summary if latest_news else None,
                    },
                    
                    # Fundamentals (basic from yfinance)
                    'fundamentals_basic': {
                        'pe_ratio': fundamentals.get('pe_ratio'),
                        'forward_pe': fundamentals.get('forward_pe'),
                        'peg_ratio': fundamentals.get('peg_ratio'),
                        'market_cap': fundamentals.get('market_cap'),
                        'revenue_growth': fundamentals.get('revenue_growth'),
                        'earnings_growth': fundamentals.get('earnings_growth'),
                        'profit_margins': fundamentals.get('profit_margins'),
                        'debt_to_equity': fundamentals.get('debt_to_equity'),
                        'return_on_equity': fundamentals.get('return_on_equity'),
                        'sector': fundamentals.get('sector'),
                        'industry': fundamentals.get('industry'),
                        'latest_quarter_date': fundamentals.get('latest_quarter_date'),
                        'latest_quarter_label': fundamentals.get('latest_quarter_label'),
                        'latest_eps': fundamentals.get('latest_eps'),
                    },
                    
                    # Fundamentals Analysis (AI-analyzed)
                    'fundamentals_analysis': {
                        'available': latest_fundamentals is not None,
                        'current_pe': latest_fundamentals.current_pe if latest_fundamentals else None,
                        'historical_pe_avg': latest_fundamentals.historical_pe_avg if latest_fundamentals else None,
                        'pe_vs_industry': latest_fundamentals.pe_vs_industry if latest_fundamentals else None,
                        'revenue_growth': latest_fundamentals.revenue_growth if latest_fundamentals else None,
                        'earnings_growth': latest_fundamentals.earnings_growth if latest_fundamentals else None,
                        'profit_margins': latest_fundamentals.profit_margins if latest_fundamentals else None,
                        'debt_to_equity': latest_fundamentals.debt_to_equity if latest_fundamentals else None,
                        'valuation_conclusion': latest_fundamentals.valuation_conclusion if latest_fundamentals else None,
                        'fundamental_strengths': latest_fundamentals.fundamental_strengths if latest_fundamentals else [],
                        'fundamental_concerns': latest_fundamentals.fundamental_concerns if latest_fundamentals else [],
                        'revenue_growth_trend': latest_fundamentals.revenue_growth_trend if latest_fundamentals else None,
                        'guidance_outlook': latest_fundamentals.guidance_outlook if latest_fundamentals else None,
                    },
                    
                    # Market Context
                    'market_context': {
                        'sentiment': market_sentiment,
                        'news': market_news,
                        'fundamentals': market_fundamentals,
                        'market_sentiment_score': market_sentiment.get('market_sentiment_score', 5.0),
                        'market_outlook': market_sentiment.get('market_outlook', 'neutral'),
                    },
                    
                    # Data Quality
                    'data_quality': {
                        'has_technical': latest_technical is not None,
                        'has_news': latest_news is not None,
                        'has_fundamentals': bool(fundamentals.get('trailingPE')),
                        'has_market_context': bool(market_sentiment),
                        'technical_age_hours': (datetime.utcnow() - latest_technical.analysis_date).total_seconds() / 3600 if latest_technical else 999,
                        'news_age_hours': (datetime.utcnow() - latest_news.analysis_date).total_seconds() / 3600 if latest_news else 999,
                    }
                }
                
                return comprehensive_data
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error collecting comprehensive data: {e}")
            return {'has_sufficient_data': False}
    
    async def _store_master_analysis(self, data: Dict, analysis: Dict):
        """Store master analysis"""
        try:
            db = SessionLocal()
            try:
                fundamentals = data.get('fundamentals', {})
                technical = data.get('technical_analysis', {})
                news = data.get('news_analysis', {})
                
                # Use master agent's own valuation determination
                valuation = analysis.get('valuation_assessment', 'Fair Value')
                
                # Get fundamentals from both sources
                fund_basic = data.get('fundamentals_basic', {})
                
                stock_analysis = StockAnalysis(
                    ticker=self.ticker,
                    analysis_date=datetime.utcnow(),
                    
                    # Current Data
                    current_price=data.get('current_price'),
                    market_cap=fund_basic.get('market_cap'),
                    
                    # Valuation - prioritize fundamentals_basic
                    pe_ratio=fund_basic.get('pe_ratio'),
                    forward_pe=fund_basic.get('forward_pe'),
                    peg_ratio=fund_basic.get('peg_ratio'),
                    
                    # Master Analysis - Use consistent valuation
                    # NOTE: overall_rating, confidence_score, key_insights, upside_potential removed (not displayed on frontend)
                    valuation_assessment=valuation,  # Use fundamentals agent's conclusion
                    
                    # Insights (only risk_factors and catalysts are displayed)
                    risk_factors=analysis.get('risk_factors', []),
                    catalysts=analysis.get('catalysts', []),
                    
                    # Context
                    market_context=data.get('market_context', {}),
                    sentiment_signals={'news_sentiment': news.get('sentiment_score')},
                    news_impact={'articles_analyzed': news.get('articles_analyzed')},
                    fundamentals_outlook={
                        # Store new structured fields here
                        'buy_below': analysis.get('buy_below'),
                        'sell_above': analysis.get('sell_above'),
                        'fair_value_price': analysis.get('fair_value_price'),
                        'company_description': analysis.get('company_description'),
                        'analysis': analysis.get('analysis'),
                        'market_comparison': analysis.get('market_comparison'),
                        'forward_outlook': analysis.get('forward_outlook')
                    },
                    
                    # Explanations (legacy fields)
                    why_current_price=analysis.get('why_current_price') or analysis.get('analysis'),
                    future_outlook=analysis.get('forward_outlook'),
                    comparison_to_market=analysis.get('market_comparison') or analysis.get('comparison_to_market'),
                    
                    # Technical
                    technical_rating=analysis.get('technical_rating'),
                    support_level=analysis.get('support_level'),
                    resistance_level=analysis.get('resistance_level'),
                    
                    # Metadata
                    agent_id=self.agent_id,
                    market_agents_consulted=['market_sentiment_001'],
                    data_sources_used=['yfinance', 'stock_technical_agent', 'stock_news_agent'],
                    next_update_target=datetime.utcnow() + timedelta(hours=24)
                )
                
                db.add(stock_analysis)
                db.commit()
                
                logger.info(f"[{self.agent_id}] Stored master analysis")
                
            except Exception as e:
                db.rollback()
                logger.error(f"Error storing master analysis: {e}")
                raise
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error in _store_master_analysis: {e}")
    
    async def get_latest_analysis(self) -> Dict:
        """Get latest master analysis with comprehensive news, averaging last 3 price targets"""
        try:
            db = SessionLocal()
            try:
                # Get latest analysis (for all text fields)
                latest = db.query(StockAnalysis).filter(
                    StockAnalysis.ticker == self.ticker
                ).order_by(StockAnalysis.analysis_date.desc()).first()
                
                if not latest:
                    return {'error': f'No analysis available for {self.ticker}'}
                
                # Get last 3 analyses to average the price values
                last_3_analyses = db.query(StockAnalysis).filter(
                    StockAnalysis.ticker == self.ticker
                ).order_by(StockAnalysis.analysis_date.desc()).limit(3).all()
                
                # Calculate averaged values from last 3 analyses
                fair_values = []
                buy_belows = []
                sell_aboves = []
                
                for analysis in last_3_analyses:
                    findings = analysis.fundamentals_outlook or {}
                    if findings.get('fair_value_price'):
                        fair_values.append(findings.get('fair_value_price'))
                    if findings.get('buy_below'):
                        buy_belows.append(findings.get('buy_below'))
                    if findings.get('sell_above'):
                        sell_aboves.append(findings.get('sell_above'))
                
                # Use average if we have values, otherwise use latest
                agent_findings = latest.fundamentals_outlook or {}
                fair_value = sum(fair_values) / len(fair_values) if fair_values else agent_findings.get('fair_value_price')
                buy_below = sum(buy_belows) / len(buy_belows) if buy_belows else agent_findings.get('buy_below')
                sell_above = sum(sell_aboves) / len(sell_aboves) if sell_aboves else agent_findings.get('sell_above')
                
                # Get comprehensive news analysis
                from ..models import StockNewsAnalysis
                latest_news = db.query(StockNewsAnalysis).filter(
                    StockNewsAnalysis.ticker == self.ticker
                ).order_by(StockNewsAnalysis.analysis_date.desc()).first()
                
                # Get fundamentals analysis for display
                from ..models import StockFundamentalsAnalysis
                latest_fund = db.query(StockFundamentalsAnalysis).filter(
                    StockFundamentalsAnalysis.ticker == self.ticker
                ).order_by(StockFundamentalsAnalysis.analysis_date.desc()).first()
                
                response = {
                    'ticker': self.ticker,
                    'analysis_date': latest.analysis_date.isoformat(),
                    'current_price': latest.current_price,
                    'valuation_assessment': latest.valuation_assessment,
                    # NOTE: overall_rating, confidence_score, target_price, upside_potential removed (not displayed)
                    
                    # Buy/Sell Thresholds - NEW
                    'fair_value_price': fair_value or latest.target_price,
                    'buy_below': buy_below,
                    'sell_above': sell_above,
                    
                    # NEW: Structured sections
                    'company_description': agent_findings.get('company_description'),
                    'analysis': agent_findings.get('analysis') or latest.why_current_price,
                    'forward_outlook': agent_findings.get('forward_outlook') or latest.future_outlook,
                    'market_comparison': agent_findings.get('market_comparison') or latest.comparison_to_market,
                    
                    # Insights (displayed on frontend)
                    'risk_factors': latest.risk_factors,
                    'catalysts': latest.catalysts,
                    
                    # Legacy fallback (keep comparison_to_market for backwards compat)
                    'comparison_to_market': latest.comparison_to_market,
                    
                    # NOTE: Removed unused legacy fields that are NOT displayed:
                    # - key_insights, why_current_price, future_outlook, technical_rating, 
                    # - support_level, resistance_level, agent_confidence
                    
                    # Fundamental Metrics
                    'pe_ratio': latest.pe_ratio,
                    'forward_pe': latest.forward_pe,
                    'peg_ratio': latest.peg_ratio,
                    'market_cap': latest.market_cap,
                    'revenue_growth': latest_fund.revenue_growth if latest_fund else None,
                    'earnings_growth': latest_fund.earnings_growth if latest_fund else None,
                    'profit_margins': latest_fund.profit_margins if latest_fund else None,
                    'debt_to_equity': latest_fund.debt_to_equity if latest_fund else None,
                    'return_on_equity': latest_fund.return_on_equity if latest_fund else None,
                    'valuation_conclusion': latest_fund.valuation_conclusion if latest_fund else None,
                    
                    # Quarter Information
                    'latest_quarter_date': latest_fund.latest_quarter_date if latest_fund and hasattr(latest_fund, 'latest_quarter_date') else None,
                    'latest_quarter_label': latest_fund.latest_quarter_label if latest_fund and hasattr(latest_fund, 'latest_quarter_label') else None,
                    'latest_eps': latest_fund.latest_eps if latest_fund and hasattr(latest_fund, 'latest_eps') else None,
                }
                
                # Add comprehensive news analysis if available
                if latest_news:
                    response.update({
                        'company_summary': latest_news.company_summary,
                        'recent_developments': latest_news.recent_developments_summary,
                        'outlook': latest_news.outlook,
                        'latest_earnings': {
                            'date': latest_news.latest_earnings_date.isoformat() if latest_news.latest_earnings_date else None,
                            'result': latest_news.latest_earnings_result,
                            'summary': latest_news.latest_earnings_summary,
                            'eps_actual': latest_news.eps_actual,
                            'eps_expected': latest_news.eps_expected
                        },
                        'key_risks': latest_news.key_risks or [],
                        'key_opportunities': latest_news.key_opportunities or [],
                        'recent_products': latest_news.recent_product_developments or [],
                        'management_changes': latest_news.management_changes or [],
                        'regulatory_issues': latest_news.regulatory_issues or [],
                        'competitive_position': latest_news.competitive_position,
                        'articles_analyzed': latest_news.articles_analyzed or 0,
                        'news_last_updated': latest_news.last_significant_update.isoformat() if latest_news.last_significant_update else None
                    })
                else:
                    # Provide empty news structure
                    response.update({
                        'company_summary': None,
                        'recent_developments': None,
                        'outlook': None,
                        'latest_earnings': {},
                        'key_risks': [],
                        'key_opportunities': [],
                        'recent_products': [],
                        'management_changes': [],
                        'regulatory_issues': [],
                        'competitive_position': None,
                        'articles_analyzed': 0,
                        'news_last_updated': None
                    })
                
                return response
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error getting latest analysis: {e}")
            return {'error': str(e)}

