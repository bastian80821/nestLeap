"""
Stock Technical Agent (Redesigned)

Analyzes time series data for individual stocks to provide technical analysis.
Integrates with market sentiment for broader context.
"""

import json
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional
from loguru import logger
import numpy as np

from .base_stock_agent import BaseStockAgent
from ..database import SessionLocal
from ..models import StockTimeSeries, StockTechnicalAnalysis
from ..services.stock_data_collector import StockDataCollector


class StockTechnicalAgent(BaseStockAgent):
    """Agent specialized in technical analysis of stocks using time series data"""
    
    def __init__(self, ticker: str, agent_id: str = None):
        if not agent_id:
            agent_id = f"stock_technical_{ticker.lower()}_001"
        
        specialized_prompt = f"""
You are a Technical Analysis AI specializing in {ticker}.

Your role is to:
1. Analyze {ticker}'s price patterns, trends, and momentum using time series data
2. Identify key support and resistance levels with high accuracy
3. Assess volume patterns and their significance
4. Compare {ticker}'s technical performance to the broader market
5. Provide actionable entry/exit points for traders

You receive:
- Complete time series data (price, volume, technical indicators)
- Market sentiment context (is the overall market bullish/bearish?)
- S&P 500 performance for relative comparison
- Historical technical patterns

Output Format (JSON):
{{
    "trend_direction": "Bullish|Bearish|Sideways",
    "trend_strength": float (0-1),
    "trend_duration_days": int,
    "trend_reliability": float (0-1),
    
    "support_level_1": float,
    "support_level_2": float, 
    "resistance_level_1": float,
    "resistance_level_2": float,
    "support_strength": float (0-1),
    "resistance_strength": float (0-1),
    
    "momentum_score": float (-1 to 1),
    "momentum_trend": "Accelerating|Stable|Decelerating",
    "rsi_assessment": "Oversold|Neutral|Overbought",
    "macd_signal": "Bullish|Bearish|Neutral",
    
    "volatility_level": "Low|Medium|High",
    "volatility_percentile": float (0-100),
    "bollinger_position": "Upper|Middle|Lower",
    
    "volume_trend": "Increasing|Stable|Decreasing",
    "unusual_volume": bool,
    "volume_confirmation": bool,
    
    "chart_pattern": "description of any patterns",
    "pattern_reliability": float (0-1),
    "pattern_target": float (projected price),
    
    "vs_market_performance": float (% vs S&P 500),
    "relative_strength": float (0-100),
    
    "entry_points": [{{"price": float, "reason": str, "strength": float}}],
    "exit_points": [{{"price": float, "reason": str, "strength": float}}],
    "stop_loss_level": float,
    
    "technical_summary": "2-3 sentence summary",
    "key_observations": ["obs1", "obs2"],
    "trading_strategy": "recommended strategy",
    "risk_assessment": "key technical risks",
    
    "short_term_outlook": "Bullish|Bearish|Neutral (1-5 days)",
    "medium_term_outlook": "Bullish|Bearish|Neutral (1-4 weeks)",
    
    "confidence": float (0-1),
    "finding_type": "stock_technical_analysis"
}}

Focus on actionable insights based on real data patterns. Reference specific price levels and indicator values.
"""
        
        super().__init__(agent_id, "stock_technical", ticker, specialized_prompt)
        self.data_collector = StockDataCollector()
        
    async def run_cycle(self):
        """Main technical analysis cycle"""
        try:
            logger.info(f"[{self.agent_id}] Starting technical analysis for {self.ticker}")
            
            # Ensure we have recent data
            await self._ensure_timeseries_data()
            
            # Collect technical data
            technical_data = await self._collect_technical_data()
            
            if not technical_data or not technical_data.get('has_sufficient_data'):
                logger.warning(f"[{self.agent_id}] Insufficient data for {self.ticker}")
                return
            
            # Perform technical analysis with LLM
            technical_analysis = await self.analyze_with_full_context(
                technical_data,
                f"Perform comprehensive technical analysis for {self.ticker}. "
                f"Analyze trends, support/resistance, momentum, and volume patterns. "
                f"Provide specific price levels and actionable trading insights. "
                f"Consider the broader market context in your analysis."
            )
            
            # Store technical analysis
            await self._store_technical_analysis(technical_data, technical_analysis)
            
            logger.info(f"[{self.agent_id}] Technical analysis completed for {self.ticker}: {technical_analysis.get('trend_direction', 'Unknown')}")
            
        except Exception as e:
            logger.error(f"[{self.agent_id}] Error in technical analysis cycle: {e}")
    
    async def _ensure_timeseries_data(self):
        """Ensure we have recent time series data"""
        try:
            db = SessionLocal()
            try:
                # Check for recent data (within last 2 days)
                cutoff = date.today() - timedelta(days=2)
                recent_data = db.query(StockTimeSeries).filter(
                    StockTimeSeries.ticker == self.ticker,
                    StockTimeSeries.date >= cutoff
                ).first()
                
                if not recent_data:
                    logger.info(f"[{self.agent_id}] No recent data found, collecting...")
                    await self.data_collector.collect_stock_data(self.ticker, days_back=90)
                    
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error ensuring timeseries data: {e}")
    
    async def _collect_technical_data(self) -> Dict:
        """Collect time series data and calculate technical metrics"""
        try:
            db = SessionLocal()
            try:
                # Get last 90 days of data
                cutoff_date = date.today() - timedelta(days=90)
                
                records = db.query(StockTimeSeries).filter(
                    StockTimeSeries.ticker == self.ticker,
                    StockTimeSeries.date >= cutoff_date
                ).order_by(StockTimeSeries.date.asc()).all()
                
                if len(records) < 20:  # Need at least 20 days for meaningful analysis
                    return {'has_sufficient_data': False}
                
                # Extract price and indicator data
                prices = [r.close_price for r in records if r.close_price]
                volumes = [r.volume for r in records if r.volume]
                dates = [r.date for r in records]
                
                # Get latest values
                latest = records[-1]
                previous = records[-2] if len(records) > 1 else None
                
                # Calculate basic metrics
                current_price = latest.close_price
                price_change_1d = ((current_price - previous.close_price) / previous.close_price * 100) if previous else 0
                price_change_5d = ((current_price - records[-6].close_price) / records[-6].close_price * 100) if len(records) > 5 else 0
                price_change_20d = ((current_price - records[-21].close_price) / records[-21].close_price * 100) if len(records) > 20 else 0
                
                # Calculate volatility (standard deviation of returns)
                returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
                volatility = np.std(returns) * 100 if returns else 0
                
                # Get market sentiment context
                market_context = await self.request_market_context('sentiment')
                
                # Get S&P 500 performance for comparison (simplified)
                sp500_change = market_context.get('market_indicators', {}).get('sp500', {}).get('change_pct', 0)
                
                technical_data = {
                    'timestamp': datetime.utcnow().isoformat(),
                    'ticker': self.ticker,
                    'has_sufficient_data': True,
                    
                    # Current State
                    'current_price': current_price,
                    'price_change_1d': price_change_1d,
                    'price_change_5d': price_change_5d,
                    'price_change_20d': price_change_20d,
                    
                    # Time Series Data
                    'timeseries': [
                        {
                            'date': r.date.isoformat(),
                            'close': r.close_price,
                            'open': r.open_price,
                            'high': r.high_price,
                            'low': r.low_price,
                            'volume': r.volume,
                            'rsi': r.rsi_14,
                            'macd': r.macd,
                            'macd_signal': r.macd_signal,
                            'sma_20': r.sma_20,
                            'sma_50': r.sma_50,
                            'sma_200': r.sma_200,
                            'bb_upper': r.bollinger_upper,
                            'bb_lower': r.bollinger_lower
                        }
                        for r in records[-30:]  # Last 30 days for LLM context
                    ],
                    
                    # Latest Indicators
                    'latest_indicators': {
                        'rsi': latest.rsi_14,
                        'macd': latest.macd,
                        'macd_signal': latest.macd_signal,
                        'sma_20': latest.sma_20,
                        'sma_50': latest.sma_50,
                        'sma_200': latest.sma_200,
                        'bb_upper': latest.bollinger_upper,
                        'bb_lower': latest.bollinger_lower,
                        'volume': latest.volume,
                        'volume_sma': latest.volume_sma_20,
                        'volume_ratio': latest.volume_ratio
                    },
                    
                    # Volatility
                    'volatility': volatility,
                    'volatility_percentile': self._calculate_percentile(volatility, [np.std(returns[i:i+20]) * 100 for i in range(len(returns)-20)] if len(returns) > 20 else [volatility]),
                    
                # Support/Resistance Candidates (from last 30 days only)
                'support_candidates': self._find_support_levels(prices[-30:], dates[-30:]),
                'resistance_candidates': self._find_resistance_levels(prices[-30:], dates[-30:]),
                    
                    # Volume Analysis
                    'avg_volume': np.mean(volumes) if volumes else 0,
                    'recent_volume': latest.volume,
                    'volume_trend': 'Increasing' if len(volumes) > 5 and np.mean(volumes[-5:]) > np.mean(volumes[:-5]) else 'Stable',
                    
                    # Market Context
                    'market_context': market_context,
                    'vs_sp500': price_change_5d - sp500_change,
                    'market_sentiment_score': market_context.get('market_sentiment_score', 5.0),
                    
                    # Data Quality
                    'days_analyzed': len(records),
                    'data_completeness': sum(1 for r in records if r.close_price) / len(records) if records else 0
                }
                
                return technical_data
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error collecting technical data: {e}")
            return {'has_sufficient_data': False}
    
    def _find_support_levels(self, prices: List[float], dates: List[date], num_levels: int = 2) -> List[Dict]:
        """Find potential support levels from price history"""
        try:
            if len(prices) < 20:
                return []
            
            # Find local minima (potential support)
            supports = []
            for i in range(5, len(prices) - 5):
                if prices[i] == min(prices[i-5:i+6]):
                    supports.append({
                        'price': prices[i],
                        'date': dates[i].isoformat(),
                        'touches': 1
                    })
            
            # Group nearby supports and count touches
            grouped = []
            for support in supports:
                found_group = False
                for group in grouped:
                    if abs(support['price'] - group['price']) / group['price'] < 0.02:  # Within 2%
                        group['touches'] += 1
                        group['price'] = (group['price'] * (group['touches'] - 1) + support['price']) / group['touches']
                        found_group = True
                        break
                if not found_group:
                    grouped.append(support)
            
            # Sort by number of touches and return top levels
            grouped.sort(key=lambda x: x['touches'], reverse=True)
            return grouped[:num_levels]
            
        except Exception as e:
            logger.error(f"Error finding support levels: {e}")
            return []
    
    def _find_resistance_levels(self, prices: List[float], dates: List[date], num_levels: int = 2) -> List[Dict]:
        """Find potential resistance levels from price history"""
        try:
            if len(prices) < 20:
                return []
            
            # Find local maxima (potential resistance)
            resistances = []
            for i in range(5, len(prices) - 5):
                if prices[i] == max(prices[i-5:i+6]):
                    resistances.append({
                        'price': prices[i],
                        'date': dates[i].isoformat(),
                        'touches': 1
                    })
            
            # Group nearby resistances and count touches
            grouped = []
            for resistance in resistances:
                found_group = False
                for group in grouped:
                    if abs(resistance['price'] - group['price']) / group['price'] < 0.02:  # Within 2%
                        group['touches'] += 1
                        group['price'] = (group['price'] * (group['touches'] - 1) + resistance['price']) / group['touches']
                        found_group = True
                        break
                if not found_group:
                    grouped.append(resistance)
            
            # Sort by number of touches and return top levels
            grouped.sort(key=lambda x: x['touches'], reverse=True)
            return grouped[:num_levels]
            
        except Exception as e:
            logger.error(f"Error finding resistance levels: {e}")
            return []
    
    def _calculate_percentile(self, value: float, historical_values: List[float]) -> float:
        """Calculate percentile of value in historical distribution"""
        try:
            if not historical_values:
                return 50.0
            return (sum(1 for v in historical_values if v < value) / len(historical_values)) * 100
        except:
            return 50.0
    
    async def _store_technical_analysis(self, technical_data: Dict, analysis: Dict):
        """Store technical analysis in database"""
        try:
            db = SessionLocal()
            try:
                latest = technical_data.get('latest_indicators', {})
                
                technical_analysis = StockTechnicalAnalysis(
                    ticker=self.ticker,
                    analysis_date=datetime.utcnow(),
                    
                    # Trend
                    trend_direction=analysis.get('trend_direction'),
                    trend_strength=analysis.get('trend_strength'),
                    trend_duration_days=analysis.get('trend_duration_days'),
                    trend_reliability=analysis.get('trend_reliability'),
                    
                    # Support/Resistance
                    support_level_1=analysis.get('support_level_1'),
                    support_level_2=analysis.get('support_level_2'),
                    resistance_level_1=analysis.get('resistance_level_1'),
                    resistance_level_2=analysis.get('resistance_level_2'),
                    support_strength=analysis.get('support_strength'),
                    resistance_strength=analysis.get('resistance_strength'),
                    
                    # Momentum
                    momentum_score=analysis.get('momentum_score'),
                    momentum_trend=analysis.get('momentum_trend'),
                    rsi_assessment=analysis.get('rsi_assessment'),
                    macd_signal=analysis.get('macd_signal'),
                    
                    # Volatility
                    volatility_level=analysis.get('volatility_level'),
                    volatility_percentile=technical_data.get('volatility_percentile'),
                    bollinger_position=analysis.get('bollinger_position'),
                    
                    # Volume
                    volume_trend=analysis.get('volume_trend'),
                    unusual_volume=analysis.get('unusual_volume', False),
                    volume_confirmation=analysis.get('volume_confirmation', False),
                    
                    # Patterns
                    chart_pattern=analysis.get('chart_pattern'),
                    pattern_reliability=analysis.get('pattern_reliability'),
                    pattern_target=analysis.get('pattern_target'),
                    
                    # Market Context
                    vs_market_performance=technical_data.get('vs_sp500'),
                    vs_sector_performance=0.0,  # TODO: Add sector comparison
                    relative_strength=analysis.get('relative_strength'),
                    correlation_to_market=0.0,  # TODO: Calculate correlation
                    
                    # Entry/Exit
                    entry_points=analysis.get('entry_points', []),
                    exit_points=analysis.get('exit_points', []),
                    stop_loss_level=analysis.get('stop_loss_level'),
                    
                    # LLM Insights
                    technical_summary=analysis.get('technical_summary'),
                    key_observations=analysis.get('key_observations', []),
                    trading_strategy=analysis.get('trading_strategy'),
                    risk_assessment=analysis.get('risk_assessment'),
                    
                    # Outlook
                    short_term_outlook=analysis.get('short_term_outlook'),
                    medium_term_outlook=analysis.get('medium_term_outlook'),
                    
                    # Metadata
                    agent_id=self.agent_id,
                    confidence_score=analysis.get('confidence', 0.7),
                    days_analyzed=technical_data.get('days_analyzed', 0),
                    market_context_integrated=True
                )
                
                db.add(technical_analysis)
                db.commit()
                
                logger.info(f"[{self.agent_id}] Stored technical analysis for {self.ticker}")
                
            except Exception as e:
                db.rollback()
                logger.error(f"Error storing technical analysis: {e}")
                raise
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error in _store_technical_analysis: {e}")
    
    async def get_latest_technical_analysis(self) -> Dict:
        """Get latest technical analysis"""
        try:
            db = SessionLocal()
            try:
                latest = db.query(StockTechnicalAnalysis).filter(
                    StockTechnicalAnalysis.ticker == self.ticker
                ).order_by(StockTechnicalAnalysis.analysis_date.desc()).first()
                
                if not latest:
                    return {'error': f'No technical analysis available for {self.ticker}'}
                
                return {
                    'ticker': self.ticker,
                    'analysis_date': latest.analysis_date.isoformat(),
                    'trend_direction': latest.trend_direction,
                    'trend_strength': latest.trend_strength,
                    'support_level': latest.support_level_1,
                    'resistance_level': latest.resistance_level_1,
                    'momentum_score': latest.momentum_score,
                    'rsi_assessment': latest.rsi_assessment,
                    'technical_summary': latest.technical_summary,
                    'short_term_outlook': latest.short_term_outlook,
                    'entry_points': latest.entry_points,
                    'stop_loss_level': latest.stop_loss_level
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error getting technical analysis: {e}")
            return {'error': str(e)}

