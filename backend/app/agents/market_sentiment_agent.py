"""
Market Sentiment Agent

Analyzes market technicals, volatility, and sentiment indicators to generate daily market sentiment assessment
with full agent architecture integration, historical context, and professional customer-facing analysis.
"""

import asyncio
import json
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional
from loguru import logger

from .base_agent import BaseAgent
from ..database import SessionLocal
from ..models import (
    MarketIndicator, MarketSentiment, MarketSentimentAnalysis, 
    MarketNewsSummary, AgentFinding, EconomicIndicator, MarketArticle
)
from ..services.market_sentiment_collector import MarketSentimentCollector


class MarketSentimentAgent(BaseAgent):
    """Agent for comprehensive market sentiment analysis with multi-agent integration"""
    
    def __init__(self, agent_id: str = "market_sentiment_001"):
        specialized_prompt = """
You are a Chief Market Sentiment Analyst providing comprehensive market sentiment assessment for traders and investors.

Your role is to:
1. Analyze overall market sentiment using technical indicators, Fear & Greed levels, and market psychology
2. Integrate economic fundamentals and macro conditions into sentiment assessment
3. Consider market news and narratives affecting investor psychology
4. Evaluate risk appetite and market regime shifts
5. Provide specific, actionable sentiment outlook based on current conditions

Analysis Guidelines:
- Focus on SENTIMENT ANALYSIS, not just technical analysis - how do investors FEEL about the market?
- Integrate technical levels with psychological factors (fear, greed, optimism, pessimism)
- Use economic context to understand WHY sentiment is changing
- Consider news flow and market narratives in sentiment assessment
- Be SPECIFIC in outlook - mention actual market levels, timeframes, and catalysts
- Write for professional traders and investors who need actionable insights
- NO generic technical jargon - focus on sentiment drivers and psychology

Key Data Sources Available:
- Current market indicators (S&P 500, NASDAQ, VIX) with technical analysis
- Fear & Greed Index showing market psychology
- Economic fundamentals analysis and cycle assessment
- Market news sentiment and themes
- Historical sentiment patterns and agent memory

Output Format (JSON):
{
    "sentiment_score": float (1-10 scale where 1=Extremely Bearish, 5-6=Neutral, 10=Extremely Bullish),
    "sentiment_assessment": "extremely_bearish|bearish|mildly_bearish|neutral|mildly_bullish|bullish|extremely_bullish",
    "volatility_environment": "low|moderate|elevated|extreme", 
    "fear_greed_reading": "extreme_fear|fear|neutral|greed|extreme_greed",
    "market_regime": "risk_on|transitional|risk_off",
    "technical_outlook": "strong_uptrend|uptrend|sideways|downtrend|strong_downtrend",
    "explanation": "4 sentences analyzing current market sentiment, integrating technical levels, psychology, economics, and news. Focus on WHY investors feel the way they do.",
    "outlook": "2-3 specific sentences with concrete levels, timeframes, and catalysts. Example: 'Watch for S&P 500 break above 4400 to confirm bullish sentiment shift. Key risk is Fed hawkishness next week which could trigger sentiment reversal below 4300.'"
}

Focus on SENTIMENT and PSYCHOLOGY, not just technical patterns. Integrate all available data to understand investor emotions and market psychology. Be SPECIFIC in your outlook - mention actual levels, dates, and catalysts that could change sentiment.
"""
        
        super().__init__(agent_id, "market_sentiment", specialized_prompt)
        
        # Initialize market data collector
        self.collector = MarketSentimentCollector()
        
        # Agent-specific settings
        self.analysis_threshold = 0.7
        
    async def run_cycle(self, force: bool = False):
        """Main agent cycle - comprehensive market sentiment analysis with agent integration"""
        try:
            logger.info(f"[{self.agent_id}] Starting market sentiment analysis cycle (force={force})")
            
            # First, ensure we have fresh market data
            await self._ensure_fresh_market_data()
            
            # Check if we already have analysis for today (duplicate prevention) - skip if force=True
            if not force and await self._has_analysis_for_today():
                logger.info(f"[{self.agent_id}] Analysis already exists for today - skipping")
                return
            
            # If force=True, delete existing analysis for today
            if force:
                await self._delete_todays_analysis()
            
            # Collect comprehensive market and sentiment data
            market_data = await self._collect_comprehensive_market_data()
            
            logger.info(f"[{self.agent_id}] Collected market data keys: {list(market_data.keys()) if market_data else 'None'}")
            logger.info(f"[{self.agent_id}] Market indicators: {list(market_data.get('market_indicators', {}).keys())}")
            logger.info(f"[{self.agent_id}] Fear & Greed available: {market_data.get('fear_greed_index') is not None}")
            logger.info(f"[{self.agent_id}] Agent intelligence: {list(market_data.get('agent_intelligence', {}).keys())}")
            
            if not market_data:
                logger.warning(f"[{self.agent_id}] Insufficient market data for analysis")
                return
            
            # Run LLM analysis with contextual prompt
            logger.info(f"[{self.agent_id}] Running LLM analysis with market data")
            analysis = await self._analyze_sentiment_with_llm(market_data)
            
            # Validate LLM response
            if not analysis:
                raise ValueError("LLM returned empty analysis - check Gemini API connection and prompt")
            
            if 'error' in analysis:
                raise ValueError(f"LLM analysis failed: {analysis.get('error')}")
            
            if not analysis.get('sentiment_score'):
                raise ValueError("LLM analysis missing required sentiment_score field")
            
            logger.info(f"[{self.agent_id}] LLM analysis successful: {analysis.get('sentiment_assessment')} ({analysis.get('sentiment_score')}/10)")
            
            # Store analysis with duplicate prevention
            await self._store_analysis_with_duplicate_prevention(analysis)
            
            logger.info(f"[{self.agent_id}] Market sentiment analysis completed: {analysis.get('sentiment_assessment', 'N/A')}")
            
        except Exception as e:
            error_msg = f"Market Sentiment Agent error: {str(e)}"
            logger.error(f"[{self.agent_id}] {error_msg}")
            
            # Return error details for debugging
            return {
                'success': False,
                'error': error_msg,
                'error_type': type(e).__name__,
                'agent_id': self.agent_id,
                'timestamp': datetime.utcnow().isoformat()
            }
    
    async def _ensure_fresh_market_data(self):
        """Ensure we have the latest market data before analysis"""
        try:
            # Collect fresh market indicators
            from ..services.historical_market_collector import HistoricalMarketCollector
            
            market_collector = HistoricalMarketCollector()
            
            # Collect key market indicators
            indicators = {
                'sp500': '^GSPC',
                'nasdaq': '^IXIC', 
                'vix': '^VIX'
            }
            
            collection_results = []
            for indicator_type, symbol in indicators.items():
                try:
                    result = await market_collector.collect_indicator_data(indicator_type, symbol)
                    if result:
                        collection_results.append(f"{indicator_type}: {result['value']:.2f}")
                except Exception as e:
                    logger.warning(f"Failed to collect {indicator_type}: {e}")
            
            # Collect Fear & Greed Index
            fear_greed = await self.collector.collect_fear_greed_index()
            if fear_greed:
                collection_results.append(f"Fear&Greed: {fear_greed['value']}")
            
            logger.info(f"[{self.agent_id}] Market data collection: {', '.join(collection_results)}")
            
        except Exception as e:
            logger.error(f"Error ensuring fresh market data: {e}")
    
    async def _has_analysis_for_today(self) -> bool:
        """Check if we already have market sentiment analysis for today (duplicate prevention)"""
        try:
            db = SessionLocal()
            today = datetime.utcnow().date()
            
            existing_analysis = db.query(MarketSentimentAnalysis).filter(
                MarketSentimentAnalysis.analysis_date >= datetime.combine(today, datetime.min.time()),
                MarketSentimentAnalysis.analysis_date < datetime.combine(today, datetime.min.time()) + timedelta(days=1)
            ).first()
            
            return existing_analysis is not None
            
        except Exception as e:
            logger.error(f"Error checking for existing analysis: {e}")
            return False
        finally:
            db.close()
    
    async def _delete_todays_analysis(self):
        """Delete existing market sentiment analysis for today if force=True"""
        try:
            db = SessionLocal()
            today = datetime.utcnow().date()
            
            existing_analysis = db.query(MarketSentimentAnalysis).filter(
                MarketSentimentAnalysis.analysis_date >= datetime.combine(today, datetime.min.time()),
                MarketSentimentAnalysis.analysis_date < datetime.combine(today, datetime.min.time()) + timedelta(days=1)
            ).first()
            
            if existing_analysis:
                db.delete(existing_analysis)
                db.commit()
                logger.info(f"[{self.agent_id}] Deleted existing analysis for today")
            else:
                logger.info(f"[{self.agent_id}] No existing analysis found for today to delete")
                
        except Exception as e:
            logger.error(f"Error deleting todays analysis: {e}")
            if 'db' in locals():
                db.rollback()
        finally:
            if 'db' in locals():
                db.close()
    
    async def _collect_comprehensive_market_data(self) -> Dict:
        """Collect market indicators with agent intelligence and historical context"""
        try:
            db = SessionLocal()
            
            # Get current market indicators (frontend display data)
            market_indicators = await self._get_current_market_indicators()
            
            # Get Fear & Greed Index
            fear_greed_data = await self.collector.collect_fear_greed_index()
            
            # Get economic fundamentals intelligence
            economic_context = await self._get_economic_agent_intelligence()
            
            # Get market news intelligence
            news_context = await self._get_news_agent_intelligence()
            
            # Get historical sentiment analyses (last 5 days for context)
            historical_analyses = await self._get_historical_sentiment_context(5)
            
            # Get market technicals timeseries
            market_timeseries = await self._get_market_timeseries()
            
            comprehensive_data = {
                'timestamp': datetime.utcnow().isoformat(),
                'market_indicators': market_indicators,
                'fear_greed_index': fear_greed_data,
                'volatility_metrics': await self._calculate_volatility_metrics(market_indicators),
                'agent_intelligence': {
                    'economic_context': economic_context,
                    'news_context': news_context
                },
                'historical_context': {
                    'previous_analyses': historical_analyses,
                    'market_timeseries': market_timeseries
                },
                'agent_memory_context': await self._get_agent_memory_context(),
                'market_regime_indicators': await self._assess_market_regime(market_indicators, fear_greed_data)
            }
            
            return comprehensive_data
            
        except Exception as e:
            logger.error(f"Error collecting comprehensive market data: {e}")
            return {}
        finally:
            db.close()
    
    async def _get_current_market_indicators(self) -> Dict:
        """Get current market indicators for frontend display (exclude treasury/dollar)"""
        try:
            db = SessionLocal()
            
            # Key indicators for frontend display
            frontend_indicators = ['sp500', 'nasdaq', 'vix']  # Removed dow
            current_indicators = {}
            
            for indicator_type in frontend_indicators:
                latest_indicator = db.query(MarketIndicator).filter(
                    MarketIndicator.indicator_type == indicator_type
                ).order_by(MarketIndicator.timestamp.desc()).first()
                
                if latest_indicator:
                    current_indicators[indicator_type] = {
                        'value': latest_indicator.value,
                        'change_pct': latest_indicator.change_pct,
                        'timestamp': latest_indicator.timestamp.isoformat(),
                        'data_source': latest_indicator.data_source,
                        'is_valid': latest_indicator.is_valid
                    }
            
            return current_indicators
            
        except Exception as e:
            logger.error(f"Error getting current market indicators: {e}")
            return {}
        finally:
            db.close()
    
    async def _calculate_volatility_metrics(self, market_indicators: Dict) -> Dict:
        """Enhanced volatility metrics with technical analysis context"""
        try:
            metrics = {}
            
            # VIX-based volatility assessment
            if 'vix' in market_indicators and market_indicators['vix']:
                vix_value = market_indicators['vix']['value']
                if vix_value < 15:
                    metrics['volatility_regime'] = 'low'
                    metrics['market_stress'] = 'minimal'
                    metrics['technical_environment'] = 'favorable'
                elif vix_value < 20:
                    metrics['volatility_regime'] = 'moderate' 
                    metrics['market_stress'] = 'low'
                    metrics['technical_environment'] = 'neutral'
                elif vix_value < 30:
                    metrics['volatility_regime'] = 'elevated'
                    metrics['market_stress'] = 'moderate'
                    metrics['technical_environment'] = 'challenging'
                else:
                    metrics['volatility_regime'] = 'extreme'
                    metrics['market_stress'] = 'high'
                    metrics['technical_environment'] = 'difficult'
            
            # Market momentum assessment with technical context
            changes = []
            for indicator in ['sp500', 'nasdaq']:  # Removed dow
                if indicator in market_indicators and market_indicators[indicator]:
                    change = market_indicators[indicator].get('change_pct', 0)
                    changes.append(change)
            
            if changes:
                avg_change = sum(changes) / len(changes)
                if avg_change > 1.5:
                    metrics['momentum'] = 'strong_positive'
                    metrics['technical_bias'] = 'bullish'
                elif avg_change > 0.5:
                    metrics['momentum'] = 'positive'
                    metrics['technical_bias'] = 'mildly_bullish'
                elif avg_change > -0.5:
                    metrics['momentum'] = 'neutral'
                    metrics['technical_bias'] = 'mixed'
                elif avg_change > -1.5:
                    metrics['momentum'] = 'negative'
                    metrics['technical_bias'] = 'mildly_bearish'
                else:
                    metrics['momentum'] = 'strong_negative'
                    metrics['technical_bias'] = 'bearish'
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error calculating enhanced volatility metrics: {e}")
            return {}
    
    async def _get_economic_agent_intelligence(self) -> Dict:
        """Get intelligence from EconomicFundamentalsAgent"""
        try:
            db = SessionLocal()
            
            # Get latest economic fundamentals analysis
            from ..models import FundamentalsAnalysis
            latest_economic_analysis = db.query(FundamentalsAnalysis).order_by(
                FundamentalsAnalysis.analysis_date.desc()
            ).first()
            
            if latest_economic_analysis:
                return {
                    'has_analysis': True,
                    'overall_assessment': latest_economic_analysis.overall_assessment,
                    'economic_cycle_stage': latest_economic_analysis.economic_cycle_stage,
                    'monetary_policy_stance': latest_economic_analysis.monetary_policy_stance,
                    'inflation_outlook': latest_economic_analysis.inflation_outlook,
                    'employment_outlook': latest_economic_analysis.employment_outlook,
                    'confidence_level': latest_economic_analysis.confidence_level,
                    'explanation_sample': latest_economic_analysis.explanation[:200] if latest_economic_analysis.explanation else None,
                    'analysis_date': latest_economic_analysis.analysis_date.isoformat()
                }
            
            # Also check for recent economic indicators
            latest_indicators = db.query(EconomicIndicator).order_by(
                EconomicIndicator.reference_date.desc()
            ).limit(10).all()
            
            if latest_indicators:
                key_indicators = {}
                for indicator in latest_indicators:
                    key_indicators[indicator.indicator_name] = {
                        'value': indicator.value,
                        'change_type': indicator.change_type,
                        'reference_date': indicator.reference_date.isoformat()
                    }
                
                return {
                    'has_analysis': False,
                    'has_indicators': True,
                    'key_indicators': key_indicators,
                    'indicators_count': len(latest_indicators)
                }
            
            return {'has_analysis': False, 'has_indicators': False, 'status': 'no_economic_data'}
            
        except Exception as e:
            logger.error(f"Error getting economic intelligence: {e}")
            return {'error': str(e)}
        finally:
            db.close()
    
    async def _get_news_agent_intelligence(self) -> Dict:
        """Get intelligence from NewsAgent"""
        try:
            db = SessionLocal()
            
            # Get latest market news summary
            latest_news = db.query(MarketNewsSummary).order_by(
                MarketNewsSummary.created_at.desc()
            ).first()
            
            if latest_news:
                return {
                    'has_news_analysis': True,
                    'summary': latest_news.summary[:300] if latest_news.summary else None,
                    'key_themes': latest_news.key_themes if hasattr(latest_news, 'key_themes') else [],
                    'sentiment_score': latest_news.sentiment_score if hasattr(latest_news, 'sentiment_score') else None,
                    'created_at': latest_news.created_at.isoformat(),
                    'article_count': latest_news.article_count if hasattr(latest_news, 'article_count') else 0
                }
            
            # Fallback to recent articles
            recent_articles = db.query(MarketArticle).order_by(
                MarketArticle.published_at.desc()
            ).limit(5).all()
            
            if recent_articles:
                return {
                    'has_news_analysis': False,
                    'has_recent_articles': True,
                    'article_count': len(recent_articles),
                    'latest_headlines': [article.title[:100] for article in recent_articles[:3]]
                }
            
            return {'has_news_analysis': False, 'has_recent_articles': False, 'status': 'no_news_data'}
            
        except Exception as e:
            logger.error(f"Error getting news intelligence: {e}")
            return {'error': str(e)}
        finally:
            db.close()
    
    async def _get_historical_sentiment_context(self, days_back: int = 5) -> List[Dict]:
        """Get previous sentiment analyses for historical context"""
        try:
            db = SessionLocal()
            cutoff_date = datetime.utcnow() - timedelta(days=days_back)
            
            previous_analyses = db.query(MarketSentimentAnalysis).filter(
                MarketSentimentAnalysis.analysis_date >= cutoff_date
            ).order_by(MarketSentimentAnalysis.analysis_date.desc()).limit(5).all()
            
            historical_context = []
            for analysis in previous_analyses:
                historical_context.append({
                    'date': analysis.analysis_date.isoformat(),
                    'sentiment_score': analysis.sentiment_score,
                    'sentiment_label': analysis.sentiment_label,
                    'confidence_level': analysis.confidence_level,
                    'trend_analysis': analysis.trend_analysis[:150] + '...' if analysis.trend_analysis and len(analysis.trend_analysis) > 150 else analysis.trend_analysis
                })
            
            return historical_context
            
        except Exception as e:
            logger.error(f"Error getting historical context: {e}")
            return []
        finally:
            db.close()
    
    async def _get_market_timeseries(self) -> Dict:
        """Get extended market timeseries for proper technical analysis"""
        try:
            from ..services.historical_market_collector import HistoricalMarketCollector
            
            # Get much more historical data for technical analysis
            market_collector = HistoricalMarketCollector()
            historical_data = await market_collector.get_historical_data(60)  # 60 trading days for technical analysis
            
            # Convert to technical analysis format
            technical_data = {}
            
            for indicator_type in ['sp500', 'nasdaq', 'vix']:
                if indicator_type in historical_data:
                    indicator_data = historical_data[indicator_type]
                    if len(indicator_data) >= 20:  # Need minimum data for technical analysis
                        
                        # Extract prices for technical analysis
                        prices = [point['value'] for point in indicator_data]
                        timestamps = [point['timestamp'] for point in indicator_data]
                        
                        # Calculate technical indicators
                        technical_analysis = await self._calculate_technical_indicators(prices, timestamps[-1])
                        
                        technical_data[indicator_type] = {
                            'historical_data': indicator_data[-20:],  # Last 20 points for context
                            'technical_analysis': technical_analysis,
                            'data_points_analyzed': len(prices)
                        }
            
            return technical_data
            
        except Exception as e:
            logger.error(f"Error getting market timeseries for technical analysis: {e}")
            return {}
    
    async def _calculate_technical_indicators(self, prices: List[float], latest_timestamp: str) -> Dict:
        """Calculate comprehensive technical indicators for market sentiment"""
        try:
            # Try to import numpy, fallback to basic calculations if not available
            try:
                import numpy as np
                use_numpy = True
            except ImportError:
                logger.warning("Numpy not available, using basic technical analysis")
                use_numpy = False
            
            if len(prices) < 20:
                return {'error': 'Insufficient data for technical analysis'}
            
            current_price = prices[-1]
            
            if use_numpy:
                # Advanced technical analysis with numpy
                prices_array = np.array(prices)
                
                # Moving Averages
                sma_10 = np.mean(prices_array[-10:]) if len(prices) >= 10 else None
                sma_20 = np.mean(prices_array[-20:]) if len(prices) >= 20 else None
                sma_50 = np.mean(prices_array[-50:]) if len(prices) >= 50 else None
                
                # Support and Resistance (using 20-day highs/lows)
                recent_prices = prices_array[-20:]
                resistance_level = np.max(recent_prices)
                support_level = np.min(recent_prices)
                
                # Volatility analysis
                returns = np.diff(prices_array) / prices_array[:-1]
                volatility = np.std(returns) * np.sqrt(252)  # Annualized volatility
                
                # Trend analysis with linear regression
                if len(prices) >= 20:
                    x = np.arange(len(prices))
                    slope = np.polyfit(x, prices, 1)[0]
                    trend_strength = abs(slope) / np.mean(prices) * 100
                    trend_direction = 'bullish' if slope > 0 else 'bearish'
                else:
                    trend_strength = 0
                    trend_direction = 'neutral'
                
            else:
                # Basic technical analysis without numpy
                sma_10 = sum(prices[-10:]) / 10 if len(prices) >= 10 else None
                sma_20 = sum(prices[-20:]) / 20 if len(prices) >= 20 else None
                sma_50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else None
                
                # Basic support/resistance
                recent_prices = prices[-20:]
                resistance_level = max(recent_prices)
                support_level = min(recent_prices)
                
                # Basic volatility (simplified)
                price_changes = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
                avg_change = sum(price_changes) / len(price_changes)
                volatility = (avg_change / current_price) * 16  # Approximate annualized
                
                # Basic trend analysis
                if len(prices) >= 20:
                    early_avg = sum(prices[:10]) / 10
                    recent_avg = sum(prices[-10:]) / 10
                    trend_strength = abs(recent_avg - early_avg) / early_avg * 100
                    trend_direction = 'bullish' if recent_avg > early_avg else 'bearish'
                else:
                    trend_strength = 0
                    trend_direction = 'neutral'
            
            # Price position relative to moving averages
            above_sma10 = bool(current_price > sma_10) if sma_10 else None
            above_sma20 = bool(current_price > sma_20) if sma_20 else None
            above_sma50 = bool(current_price > sma_50) if sma_50 else None
            
            # Price position in range
            price_range = resistance_level - support_level
            price_position = (current_price - support_level) / price_range if price_range > 0 else 0.5
            
            # Momentum indicators
            momentum_5d = (prices[-1] / prices[-6] - 1) * 100 if len(prices) >= 6 else 0
            momentum_10d = (prices[-1] / prices[-11] - 1) * 100 if len(prices) >= 11 else 0
            momentum_20d = (prices[-1] / prices[-21] - 1) * 100 if len(prices) >= 21 else 0
            
            # RSI-like momentum (simplified)
            if len(prices) >= 14:
                price_changes = [prices[i] - prices[i-1] for i in range(-14, 0)]
                gains = [change for change in price_changes if change > 0]
                losses = [abs(change) for change in price_changes if change < 0]
                avg_gain = sum(gains) / len(gains) if gains else 0
                avg_loss = sum(losses) / len(losses) if losses else 0.01
                rs = avg_gain / avg_loss
                rsi_like = 100 - (100 / (1 + rs))
            else:
                rsi_like = 50  # Neutral
            
            # Technical sentiment score (0-1)
            tech_score = 0.5  # Start neutral
            
            # Add points for bullish indicators
            if above_sma10: tech_score += 0.1
            if above_sma20: tech_score += 0.1
            if above_sma50: tech_score += 0.1
            if price_position > 0.7: tech_score += 0.1  # Near resistance (bullish)
            if price_position < 0.3: tech_score -= 0.1  # Near support (bearish)
            if momentum_5d > 2: tech_score += 0.1   # Strong 5-day momentum
            if momentum_10d > 5: tech_score += 0.1  # Strong 10-day momentum
            if rsi_like > 70: tech_score -= 0.05  # Overbought
            if rsi_like < 30: tech_score += 0.05  # Oversold (potentially bullish)
            if trend_direction == 'bullish' and trend_strength > 0.5: tech_score += 0.1
            
            tech_score = max(0, min(1, tech_score))
            
            return {
                'current_price': float(current_price),
                'moving_averages': {
                    'sma_10': float(sma_10) if sma_10 is not None else None,
                    'sma_20': float(sma_20) if sma_20 is not None else None,
                    'sma_50': float(sma_50) if sma_50 is not None else None,
                    'above_sma10': above_sma10,
                    'above_sma20': above_sma20,
                    'above_sma50': above_sma50
                },
                'support_resistance': {
                    'support_level': float(support_level),
                    'resistance_level': float(resistance_level),
                    'price_position': float(price_position),
                    'distance_to_support': float(((current_price - support_level) / current_price) * 100),
                    'distance_to_resistance': float(((resistance_level - current_price) / current_price) * 100)
                },
                'momentum': {
                    'momentum_5d': float(momentum_5d),
                    'momentum_10d': float(momentum_10d),
                    'momentum_20d': float(momentum_20d),
                    'rsi_like': float(rsi_like)
                },
                'trend_analysis': {
                    'direction': str(trend_direction),
                    'strength': float(trend_strength),
                    'slope': 0.0  # Simplified for basic version
                },
                'volatility': {
                    'annualized_volatility': float(volatility * 100),
                    'volatility_regime': 'high' if volatility > 0.25 else 'moderate' if volatility > 0.15 else 'low'
                },
                'technical_sentiment_score': float(tech_score),
                'analysis_timestamp': str(latest_timestamp),
                'calculation_method': 'numpy' if use_numpy else 'basic'
            }
            
        except Exception as e:
            logger.error(f"Error calculating technical indicators: {e}")
            return {'error': str(e)}
    
    async def _get_agent_memory_context(self) -> Dict:
        """Get relevant agent memory for context"""
        try:
            # Use the base agent memory system
            short_term = await self.memory.get_short_term_memory(5)
            medium_term = await self.memory.get_medium_term_memory(4)
            
            return {
                'recent_findings': short_term.get('recent_findings', [])[:5],
                'recent_market_data': short_term.get('recent_market_data', [])[:10]
            }
        except Exception as e:
            logger.error(f"Error getting agent memory context: {e}")
            return {}
    
    async def _assess_market_regime(self, market_indicators: Dict, fear_greed_data: Dict) -> Dict:
        """Assess current market regime for analysis context"""
        try:
            regime_indicators = {}
            
            # Fear & Greed regime
            if fear_greed_data and 'value' in fear_greed_data:
                fg_value = fear_greed_data['value']
                if fg_value < 25:
                    regime_indicators['fear_greed_regime'] = 'extreme_fear'
                elif fg_value < 45:
                    regime_indicators['fear_greed_regime'] = 'fear'
                elif fg_value < 55:
                    regime_indicators['fear_greed_regime'] = 'neutral'
                elif fg_value < 75:
                    regime_indicators['fear_greed_regime'] = 'greed'
                else:
                    regime_indicators['fear_greed_regime'] = 'extreme_greed'
            
            # Volatility regime
            if 'vix' in market_indicators and market_indicators['vix']:
                vix_value = market_indicators['vix']['value']
                regime_indicators['volatility_regime'] = (
                    'low' if vix_value < 20 else 
                    'moderate' if vix_value < 30 else 'elevated'
                )
            
            return regime_indicators
            
        except Exception as e:
            logger.error(f"Error assessing market regime: {e}")
            return {}
    
    def _convert_sentiment_to_score(self, sentiment_assessment: str) -> float:
        """Convert sentiment assessment to numerical score for database (1-10 scale)"""
        sentiment_map = {
            'extremely_bearish': 1.5,
            'bearish': 3.0,
            'mildly_bearish': 4.5,
            'neutral': 5.5,
            'mildly_bullish': 6.5,
            'bullish': 7.5,
            'extremely_bullish': 9.0
        }
        return sentiment_map.get(sentiment_assessment, 5.5)
    
    async def _store_sentiment_analysis(self, market_data: Dict, analysis: Dict, force: bool = False):
        """Store market sentiment analysis with duplicate prevention"""
        try:
            db = SessionLocal()
            
            # Double-check for duplicates before storing
            today = datetime.utcnow().date()
            existing = db.query(MarketSentimentAnalysis).filter(
                MarketSentimentAnalysis.analysis_date >= datetime.combine(today, datetime.min.time()),
                MarketSentimentAnalysis.analysis_date < datetime.combine(today, datetime.min.time()) + timedelta(days=1)
            ).first()
            
            if existing and not force:
                logger.warning(f"[{self.agent_id}] Analysis already exists for today - not storing duplicate")
                return
            elif existing and force:
                # Force overwrite - delete existing first
                logger.info(f"[{self.agent_id}] Force overwriting existing analysis from {existing.analysis_date}")
                db.delete(existing)
                db.commit()
            
            # Store new analysis with 1-10 sentiment score
            sentiment_analysis = MarketSentimentAnalysis(
                analysis_date=datetime.utcnow(),
                sentiment_score=analysis.get('sentiment_score', 5.5),  # Use direct 1-10 score
                sentiment_label=analysis.get('sentiment_assessment'),
                confidence_level=0.85,  # Fixed confidence for database compatibility
                key_factors=[],  # No longer used
                trend_analysis=analysis.get('explanation'),
                market_outlook=analysis.get('outlook'),
                historical_context=f"Volatility: {analysis.get('volatility_environment')}, Technical: {analysis.get('technical_outlook')}",
                data_period_start=datetime.utcnow() - timedelta(days=1),
                data_period_end=datetime.utcnow(),
                indicators_analyzed=list(market_data.get('market_indicators', {}).keys())
            )
            
            db.add(sentiment_analysis)
            db.commit()
            
            # Also store as agent finding for the memory system
            await self._store_finding(analysis, market_data)
            
            logger.info(f"[{self.agent_id}] Stored market sentiment analysis in database")
            
        except Exception as e:
            logger.error(f"Error storing sentiment analysis: {e}")
            if 'db' in locals():
                db.rollback()
        finally:
            if 'db' in locals():
                db.close()
    
    async def get_latest_analysis(self) -> Dict:
        """Get latest market sentiment analysis"""
        try:
            db = SessionLocal()
            
            latest_analysis = db.query(MarketSentimentAnalysis).order_by(
                MarketSentimentAnalysis.analysis_date.desc()
            ).first()
            
            if not latest_analysis:
                return {'error': 'No market sentiment analysis available'}
            
            # Handle both old and new data structure
            sentiment_assessment = getattr(latest_analysis, 'sentiment_assessment', None) or latest_analysis.sentiment_label
            explanation = getattr(latest_analysis, 'explanation', None) or latest_analysis.trend_analysis
            outlook = getattr(latest_analysis, 'outlook', None) or latest_analysis.market_outlook
            volatility_environment = getattr(latest_analysis, 'volatility_environment', 'moderate')
            fear_greed_reading = getattr(latest_analysis, 'fear_greed_reading', 'neutral')
            market_regime = getattr(latest_analysis, 'market_regime', 'transitional')
            technical_outlook = getattr(latest_analysis, 'technical_outlook', 'sideways')
            
            return {
                'analysis_date': latest_analysis.analysis_date.isoformat(),
                'sentiment_assessment': sentiment_assessment,
                'sentiment_score': latest_analysis.sentiment_score,
                'explanation': explanation,
                'outlook': outlook,
                'volatility_environment': volatility_environment,
                'fear_greed_reading': fear_greed_reading,
                'market_regime': market_regime,
                'technical_outlook': technical_outlook,
                'agent_id': self.agent_id
            }
            
        except Exception as e:
            logger.error(f"Error getting latest analysis: {e}")
            return {'error': f'Failed to retrieve analysis: {str(e)}'}
        finally:
            if 'db' in locals():
                db.close()
    
    async def _analyze_sentiment_with_llm(self, market_data: Dict) -> Dict:
        """Analyze market sentiment using LLM with comprehensive market data"""
        try:
            # Build contextual prompt with market data and agent intelligence
            contextual_prompt = await self.get_contextual_prompt({
                'task': 'market_sentiment_analysis',
                'market_data': market_data,
                'analysis_type': 'comprehensive_sentiment'
            })
            
            logger.info(f"[{self.agent_id}] Sending prompt to LLM (length: {len(contextual_prompt)} chars)")
            
            # Log Gemini API call for debugging
            await self._log_gemini_call(contextual_prompt, "sentiment_analysis")
            
            # Generate analysis
            response = self.model.generate_content(contextual_prompt)
            
            if not response or not response.text:
                raise ValueError("Empty response from Gemini API")
            
            logger.info(f"[{self.agent_id}] LLM response received (length: {len(response.text)} chars)")
            
            # Parse JSON response
            try:
                # Strip markdown code blocks if present
                response_text = response.text.strip()
                if response_text.startswith('```json'):
                    response_text = response_text[7:]  # Remove ```json
                if response_text.startswith('```'):
                    response_text = response_text[3:]  # Remove ```
                if response_text.endswith('```'):
                    response_text = response_text[:-3]  # Remove trailing ```
                
                response_text = response_text.strip()
                analysis = json.loads(response_text)
            except json.JSONDecodeError as e:
                raise ValueError(f"LLM returned invalid JSON: {e}. Response: {response.text[:200]}...")
            
            # Validate required fields
            required_fields = ['sentiment_score', 'sentiment_assessment', 'explanation', 'outlook']
            missing_fields = [field for field in required_fields if field not in analysis]
            if missing_fields:
                raise ValueError(f"LLM response missing required fields: {missing_fields}")
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error in LLM sentiment analysis: {e}")
            raise
    
    async def _store_analysis_with_duplicate_prevention(self, analysis: Dict):
        """Store sentiment analysis with duplicate prevention"""
        try:
            db = SessionLocal()
            today = date.today()
            
            # Check for existing analysis today
            existing = db.query(MarketSentimentAnalysis).filter(
                MarketSentimentAnalysis.analysis_date == today
            ).first()
            
            if existing:
                logger.info(f"[{self.agent_id}] Updating existing sentiment analysis for {today}")
                # Update existing record
                existing.sentiment_score = analysis.get('sentiment_score', 5.5)
                existing.sentiment_label = analysis.get('sentiment_assessment', 'neutral')
                existing.trend_analysis = analysis.get('explanation', '')
                existing.market_outlook = analysis.get('outlook', '')
                existing.historical_context = f"Volatility: {analysis.get('volatility_environment', 'moderate')}, Technical: {analysis.get('technical_outlook', 'sideways')}"
                existing.confidence_level = 0.85  # Fixed for database compatibility
            else:
                logger.info(f"[{self.agent_id}] Creating new sentiment analysis for {today}")
                # Create new record
                sentiment_analysis = MarketSentimentAnalysis(
                    analysis_date=datetime.utcnow(),
                    sentiment_score=analysis.get('sentiment_score', 5.5),
                    sentiment_label=analysis.get('sentiment_assessment', 'neutral'),
                    confidence_level=0.85,  # Fixed for database compatibility
                    key_factors=[],  # Empty list for JSON field
                    trend_analysis=analysis.get('explanation', ''),
                    market_outlook=analysis.get('outlook', ''),
                    historical_context=f"Volatility: {analysis.get('volatility_environment', 'moderate')}, Technical: {analysis.get('technical_outlook', 'sideways')}",
                    data_period_start=datetime.utcnow() - timedelta(days=1),
                    data_period_end=datetime.utcnow(),
                    indicators_analyzed=['sp500', 'nasdaq', 'vix']  # Standard indicators
                )
                db.add(sentiment_analysis)
            
            db.commit()
            logger.info(f"[{self.agent_id}] Sentiment analysis stored successfully")
            
        except Exception as e:
            logger.error(f"Error storing sentiment analysis: {e}")
            db.rollback()
            raise
        finally:
            db.close() 