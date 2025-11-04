"""
Economic Fundamentals Agent - Clean Implementation

Simple, reliable agent that:
1. Collects key economic indicators from database 
2. Gets latest news context from news agent
3. Analyzes economic trends and time series
4. Generates one daily economic summary
5. Stores summary for other agents to access
"""

import asyncio
import json
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional
from loguru import logger

from .base_agent import BaseAgent
from ..database import SessionLocal
from ..models import (
    EconomicIndicator, FundamentalsAnalysis, MarketNewsSummary
)


class EconomicFundamentalsAgent(BaseAgent):
    """Clean economic fundamentals agent with simple, reliable implementation"""
    
    def __init__(self, agent_id: str = "economic_fundamentals_001"):
        specialized_prompt = """
You are a Chief Economic Analyst providing daily economic assessment for investors.

CONTEXT: You will receive current economic indicators with proper quarter labels, recent news, time series data, and previous analyses.

IMPORTANT RULES:
- NO SPECIFIC NUMBERS in your analysis (no "4.1%", "-0.5%", "$621M" etc.) 
- Use descriptive terms: "strong", "weak", "elevated", "stable", "improving", "deteriorating"
- For quarterly data, use proper quarter references (Q1 2025, Q2 2025) based on the quarter_label provided
- Economic data has reporting lags - February 2025 data refers to Q4 2024 results
- Weigh ALL 8 indicators equally: GDP, inflation, unemployment, Fed rate, retail sales, production, home prices, Treasury yields
- Only call it recession if: 2+ consecutive quarters negative GDP AND deteriorating employment

OUTPUT FORMAT (JSON):
{
    "overall_assessment": "bullish|neutral|bearish",
    "economic_cycle_stage": "early_cycle|mid_cycle|late_cycle|recession",
    "monetary_policy_stance": "accommodative|neutral|restrictive", 
    "inflation_outlook": "rising|stable|moderating|declining",
    "employment_outlook": "strong|moderate|weak|deteriorating",
    "confidence_level": 0.85,
    "comprehensive_analysis": "Write 3-4 sentences using descriptive terms (strong, weak, elevated, stable) instead of specific numbers. Reference proper quarters when discussing GDP or quarterly data. Provide balanced assessment of all economic indicators for investors.",
    "key_economic_risks": ["Risk 1 with quarter timeframe", "Risk 2 with quarter timeframe"],
    "market_implications": ["Market implication 1", "Market implication 2"]
}

Focus on balanced economic analysis using professional language without specific numeric values.
"""
        
        super().__init__(agent_id, "economic_fundamentals", specialized_prompt)
        
    def _get_quarter_from_date(self, reference_date: str, indicator_name: str = None) -> str:
        """Convert reference date to proper quarter label considering economic data lags"""
        try:
            from datetime import datetime
            date_obj = datetime.fromisoformat(reference_date.replace('Z', '+00:00'))
            
            year = date_obj.year
            month = date_obj.month
            
            # For GDP specifically, there's a ~1-2 month reporting lag
            # Data released in April represents Q1 data, not Q2 data
            if indicator_name == 'gdp_yoy_growth_bea':
                # Map release month to actual quarter represented
                if month in [1, 2, 3]:  # Released in Q1 = Q4 of previous year
                    quarter = "Q4"
                    year = year - 1
                elif month in [4, 5, 6]:  # Released in Q2 = Q1 of same year
                    quarter = "Q1"
                elif month in [7, 8, 9]:  # Released in Q3 = Q2 of same year
                    quarter = "Q2"
                else:  # Released in Q4 = Q3 of same year
                    quarter = "Q3"
            else:
                # For other quarterly indicators, use standard mapping
                if month in [1, 2, 3]:
                    quarter = "Q1"
                elif month in [4, 5, 6]:
                    quarter = "Q2"
                elif month in [7, 8, 9]:
                    quarter = "Q3"
                else:
                    quarter = "Q4"
            
            return f"{quarter} {year}"
            
        except Exception as e:
            logger.warning(f"Error parsing quarter from date {reference_date}: {e}")
            return "recent quarter"
        
    def _get_indicator_direction(self, indicator) -> str:
        """Get directional description for an indicator based on its value and trend"""
        try:
            current_value = indicator.value
            previous_value = indicator.previous_value
            
            if not previous_value or previous_value == current_value:
                # No change or no previous data
                if indicator.indicator_name == 'unemployment_rate':
                    if current_value <= 4.0:
                        return "very_strong"
                    elif current_value <= 4.5:
                        return "strong"
                    elif current_value <= 5.0:
                        return "moderate"
                    else:
                        return "elevated"
                elif indicator.indicator_name == 'cpi_yoy_inflation':
                    if current_value <= 2.0:
                        return "subdued"
                    elif current_value <= 2.5:
                        return "stable"
                    elif current_value <= 3.0:
                        return "moderate"
                    else:
                        return "elevated"
                elif indicator.indicator_name == 'gdp_yoy_growth_bea':
                    if current_value < 0:
                        return "contracting"
                    elif current_value < 1.0:
                        return "weak"
                    elif current_value < 2.5:
                        return "moderate"
                    else:
                        return "strong"
                else:
                    return "stable"
            
            # Calculate change direction
            change = current_value - previous_value
            change_pct = (change / abs(previous_value)) * 100 if previous_value != 0 else 0
            
            # For unemployment (lower is better)
            if indicator.indicator_name == 'unemployment_rate':
                if change < -0.1:
                    return "improving_strongly"
                elif change < 0:
                    return "improving"
                elif change > 0.1:
                    return "deteriorating"
                else:
                    return "stable"
            
            # For inflation (stable around 2% is good)
            elif indicator.indicator_name == 'cpi_yoy_inflation':
                if abs(change) < 0.1:
                    return "stable"
                elif change > 0.2:
                    return "rising"
                elif change < -0.2:
                    return "moderating"
                else:
                    return "stable"
            
            # For GDP and other growth indicators (higher is better)
            elif indicator.indicator_name in ['gdp_yoy_growth_bea', 'retail_sales', 'industrial_production']:
                if change_pct > 2:
                    return "strengthening"
                elif change_pct > 0.5:
                    return "improving"
                elif change_pct < -2:
                    return "weakening"
                elif change_pct < -0.5:
                    return "declining"
                else:
                    return "stable"
            
            # For rates (direction depends on context)
            else:
                if abs(change_pct) < 1:
                    return "stable"
                elif change > 0:
                    return "rising"
                else:
                    return "falling"
                    
        except Exception as e:
            logger.warning(f"Error getting indicator direction: {e}")
            return "stable"
        
    async def get_frontend_summary(self) -> str:
        """Get frontend-friendly summary from explanation field"""
        try:
            db = SessionLocal()
            latest = db.query(FundamentalsAnalysis).order_by(
                FundamentalsAnalysis.analysis_date.desc()
            ).first()
            
            if latest and latest.explanation:
                # Return the full explanation - no need to truncate good analysis
                return latest.explanation
            
            return "Economic fundamentals analysis available."
            
        except Exception as e:
            logger.error(f"Error getting frontend summary: {e}")
            return "Economic analysis not available."
        finally:
            if 'db' in locals():
                db.close()
        
    async def run_cycle(self, force: bool = False):
        """Main agent cycle - clean economic analysis"""
        try:
            logger.info(f"[{self.agent_id}] Starting economic analysis cycle (force={force})")
            
            # Check if analysis already exists for today (unless force=True)
            if not force and await self._has_todays_analysis():
                logger.info(f"[{self.agent_id}] Analysis already exists for today")
                return {"status": "skipped", "reason": "analysis_exists_for_today"}
            
            # Collect economic data and context
            economic_context = await self._collect_economic_context()
            if not economic_context:
                logger.error(f"[{self.agent_id}] Failed to collect economic context")
                return {"success": False, "error": "Failed to collect economic data"}
            
            # Generate LLM analysis
            logger.info(f"[{self.agent_id}] Generating economic analysis")
            analysis = await self._generate_analysis(economic_context)
            
            if not analysis or 'error' in analysis:
                logger.error(f"[{self.agent_id}] LLM analysis failed: {analysis}")
                return {"success": False, "error": "LLM analysis failed", "details": analysis}
            
            # Store analysis for other agents to access
            stored = await self._store_analysis(analysis, force=force)
            if not stored:
                logger.error(f"[{self.agent_id}] Failed to store analysis")
                return {"success": False, "error": "Failed to store analysis"}
            
            logger.info(f"[{self.agent_id}] Economic analysis completed: {analysis.get('overall_assessment')}")
            return {"status": "success", "analysis": analysis}
            
        except Exception as e:
            logger.error(f"[{self.agent_id}] Error in economic analysis cycle: {e}")
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
                "agent_id": self.agent_id,
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def _has_todays_analysis(self) -> bool:
        """Check if we already have analysis for today"""
        try:
            db = SessionLocal()
            today = datetime.utcnow().date()
            
            existing = db.query(FundamentalsAnalysis).filter(
                FundamentalsAnalysis.analysis_date >= datetime.combine(today, datetime.min.time())
            ).first()
            
            return existing is not None
            
        except Exception as e:
            logger.error(f"Error checking for today's analysis: {e}")
            return False
        finally:
            db.close()
    
    async def _collect_economic_context(self) -> Dict:
        """Collect economic indicators, news context, and historical data with full context"""
        try:
            db = SessionLocal()
            
            # 1. Get current economic indicators (the 8 key ones displayed on frontend)
            key_indicators = [
                'gdp_yoy_growth_bea', 'cpi_yoy_inflation', 'fed_funds_rate',
                'unemployment_rate', 'retail_sales', 'industrial_production', 
                'home_price_index', 'treasury_10y_yield'
            ]
            
            current_indicators = {}
            for indicator_name in key_indicators:
                latest = db.query(EconomicIndicator).filter(
                    EconomicIndicator.indicator_name == indicator_name
                ).order_by(EconomicIndicator.reference_date.desc()).first()
                
                if latest:
                    # Add quarter label for quarterly data
                    quarter_label = None
                    if latest.period_type == 'quarterly':
                        quarter_label = self._get_quarter_from_date(latest.reference_date.isoformat(), indicator_name)
                    
                    current_indicators[indicator_name] = {
                        'value': latest.value,
                        'unit': latest.unit,
                        'reference_date': latest.reference_date.isoformat(),
                        'period_type': latest.period_type,
                        'quarter_label': quarter_label,
                        'direction': self._get_indicator_direction(latest),
                        'previous_value': latest.previous_value
                    }
            
            # 2. Get recent news context from news agent
            news_context = await self._get_news_context()
            
            # 3. Get time series for trend analysis (last 12 data points per indicator)
            time_series = await self._get_economic_time_series(key_indicators)
            
            # 4. Get previous economic analyses for historical context (last 5 for rich context)
            previous_analyses = await self._get_previous_analyses(5)
            
            economic_context = {
                'timestamp': datetime.utcnow().isoformat(),
                'current_indicators': current_indicators,
                'news_context': news_context,
                'time_series_trends': time_series,
                'previous_analyses': previous_analyses,
                'indicators_count': len(current_indicators)
            }
            
            logger.info(f"[{self.agent_id}] Collected comprehensive context: {len(current_indicators)} indicators, {len(time_series)} time series, news: {news_context.get('has_news', False)}")
            return economic_context
            
        except Exception as e:
            logger.error(f"Error collecting economic context: {e}")
            return {}
        finally:
            db.close()
    
    async def _get_news_context(self) -> Dict:
        """Get latest news context from news agent"""
        try:
            db = SessionLocal()
            
            # Get latest market news summary (last 2 days)
            cutoff = datetime.utcnow() - timedelta(days=2)
            latest_news = db.query(MarketNewsSummary).filter(
                MarketNewsSummary.created_at >= cutoff
            ).order_by(MarketNewsSummary.created_at.desc()).first()
            
            if latest_news:
                return {
                    'has_news': True,
                    'news_summary': latest_news.summary,
                    'news_date': latest_news.created_at.isoformat(),
                    'article_count': len(latest_news.article_ids) if latest_news.article_ids else 0
                }
            else:
                return {'has_news': False, 'reason': 'no_recent_news'}
                
        except Exception as e:
            logger.error(f"Error getting news context: {e}")
            return {'has_news': False, 'error': str(e)}
        finally:
            db.close()
    
    async def _get_economic_time_series(self, indicators: List[str]) -> Dict:
        """Get time series data for trend analysis"""
        try:
            db = SessionLocal()
            time_series = {}
            
            for indicator_name in indicators:
                # Get last 12 data points for each indicator
                recent_data = db.query(EconomicIndicator).filter(
                    EconomicIndicator.indicator_name == indicator_name
                ).order_by(EconomicIndicator.reference_date.desc()).limit(12).all()
                
                if recent_data:
                    # Reverse to get chronological order
                    time_series[indicator_name] = [
                        {
                            'date': point.reference_date.isoformat(),
                            'value': point.value
                        } for point in reversed(recent_data)
                    ]
            
            return time_series
            
        except Exception as e:
            logger.error(f"Error getting time series: {e}")
            return {}
        finally:
            db.close()
    
    async def _get_previous_analyses(self, limit: int = 5) -> List[Dict]:
        """Get previous economic analyses for comprehensive historical context"""
        try:
            db = SessionLocal()
            
            previous = db.query(FundamentalsAnalysis).order_by(
                FundamentalsAnalysis.analysis_date.desc()
            ).limit(limit).all()
            
            return [
                {
                    'date': analysis.analysis_date.isoformat(),
                    'overall_assessment': analysis.overall_assessment,
                    'economic_cycle_stage': analysis.economic_cycle_stage,
                    'monetary_policy_stance': analysis.monetary_policy_stance,
                    'inflation_outlook': analysis.inflation_outlook,
                    'employment_outlook': analysis.employment_outlook,
                    'confidence_level': analysis.confidence_level,
                    'explanation_summary': analysis.explanation[:300] + "..." if analysis.explanation and len(analysis.explanation) > 300 else analysis.explanation
                } for analysis in previous
            ]
            
        except Exception as e:
            logger.error(f"Error getting previous analyses: {e}")
            return []
        finally:
            db.close()
    
    async def _generate_analysis(self, context: Dict) -> Dict:
        """Generate comprehensive LLM analysis from full economic context"""
        try:
            # Build comprehensive prompt with full context for rich analysis
            prompt = f"""
COMPREHENSIVE ECONOMIC CONTEXT FOR ANALYSIS:

CURRENT INDICATORS:
{json.dumps(context.get('current_indicators', {}), indent=2)}

NEWS CONTEXT (from News Agent):
{json.dumps(context.get('news_context', {}), indent=2)}

TIME SERIES TRENDS (Last 12 data points per indicator):
{json.dumps(context.get('time_series_trends', {}), indent=2)}

PREVIOUS ANALYSES (Historical Context):
{json.dumps(context.get('previous_analyses', []), indent=2)}

ANALYSIS INSTRUCTIONS:
Based on this comprehensive economic context, provide your daily economic assessment for investors.

Consider:
- Current indicator values vs historical trends from time series
- How recent economic news impacts policy expectations
- Continuity/changes from previous analyses
- Cross-indicator relationships and economic cycle dynamics
- Investment implications across asset classes and sectors

Focus on economic trends, relationships, and forward-looking investment implications.
Provide nuanced analysis that leverages all available context.
Return only valid JSON with the required fields.
"""
            
            # Call LLM with full comprehensive context
            analysis = await self.analyze_with_context(context, prompt)
            
            if not analysis or 'error' in analysis:
                return {'error': 'LLM analysis failed', 'details': analysis}
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error generating analysis: {e}")
            return {'error': str(e)}
    
    async def _store_analysis(self, analysis: Dict, force: bool = False) -> bool:
        """Store analysis in database for other agents to access"""
        try:
            db = SessionLocal()
            
            # If force=True, delete any existing analysis for today
            if force:
                today = datetime.utcnow().date()
                existing = db.query(FundamentalsAnalysis).filter(
                    FundamentalsAnalysis.analysis_date >= datetime.combine(today, datetime.min.time())
                ).first()
                if existing:
                    db.delete(existing)
                    db.commit()
                    logger.info(f"[{self.agent_id}] Deleted existing analysis for force refresh")
            
            # Store new analysis - simple approach
            fundamentals_analysis = FundamentalsAnalysis(
                analysis_date=datetime.utcnow(),
                overall_assessment=analysis.get('overall_assessment'),
                economic_cycle_stage=analysis.get('economic_cycle_stage'),
                monetary_policy_stance=analysis.get('monetary_policy_stance'),
                inflation_outlook=analysis.get('inflation_outlook'),
                employment_outlook=analysis.get('employment_outlook'),
                confidence_level=analysis.get('confidence_level', 0.8),
                explanation=analysis.get('comprehensive_analysis'),
                key_insights=analysis.get('key_economic_risks', []),
                market_implications=analysis.get('market_implications', []),
                risk_factors=analysis.get('key_economic_risks', [])
            )
            
            db.add(fundamentals_analysis)
            db.commit()
            
            logger.info(f"[{self.agent_id}] Stored economic analysis in database")
            return True
            
        except Exception as e:
            logger.error(f"Error storing analysis: {e}")
            if 'db' in locals():
                db.rollback()
            return False
        finally:
            if 'db' in locals():
                db.close()
    
    async def get_latest_analysis(self) -> Dict:
        """Get latest economic analysis for other agents to access"""
        try:
            db = SessionLocal()
            
            latest = db.query(FundamentalsAnalysis).order_by(
                FundamentalsAnalysis.analysis_date.desc()
            ).first()
            
            if not latest:
                return {'error': 'No economic analysis available'}
            
            return {
                'analysis_date': latest.analysis_date.isoformat(),
                'overall_assessment': latest.overall_assessment,
                'economic_cycle_stage': latest.economic_cycle_stage,
                'monetary_policy_stance': latest.monetary_policy_stance,
                'inflation_outlook': latest.inflation_outlook,
                'employment_outlook': latest.employment_outlook,
                'confidence_level': latest.confidence_level,
                'comprehensive_analysis': latest.explanation,  # Full analysis for other agents
                'key_insights': latest.key_insights,
                'market_implications': latest.market_implications,
                'sector_impacts': latest.sector_impacts,
                'risk_factors': latest.risk_factors,
                'data_period_start': latest.data_period_start.isoformat() if latest.data_period_start else None,
                'data_period_end': latest.data_period_end.isoformat() if latest.data_period_end else None,
                'indicators_analyzed': latest.indicators_analyzed,
                'agent_id': self.agent_id
            }
            
        except Exception as e:
            logger.error(f"Error getting latest analysis: {e}")
            return {'error': str(e)}
        finally:
            db.close() 