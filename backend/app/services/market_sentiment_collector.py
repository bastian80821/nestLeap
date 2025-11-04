"""
Market Sentiment Collector Service

Comprehensive market sentiment data collection using multiple data sources.
Collects indices, VIX, treasury rates, dollar index, market breadth, and news sentiment.
"""

import asyncio
import aiohttp
import json
import yfinance as yf
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta, time, date
import pytz
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
from ..database import SessionLocal
from ..models import MarketSentiment, MarketIndicator, MarketNewsSummary, GeminiApiCallLog
from ..config import settings
import google.generativeai as genai
from contextlib import asynccontextmanager
import random
import re
from bs4 import BeautifulSoup

class MarketSentimentCollector:
    """Collects comprehensive market sentiment data from multiple sources."""
    
    def __init__(self):
        self.alpha_vantage_key = settings.alpha_vantage_api_key or "demo"
        
        # Configure Gemini if API key is available
        if hasattr(settings, 'google_api_key') and settings.google_api_key:
            genai.configure(api_key=settings.google_api_key)
            self.model = genai.GenerativeModel('gemini-2.5-flash')
        else:
            self.model = None
        
        # Eastern time zone for market hours
        self.est = pytz.timezone('US/Eastern')
        
        # News sentiment sources
        self.news_sources = {
            "stock_news_api": "https://stocknewsapi.com/api/v1",
            "finnhub": "https://finnhub.io/api/v1",
            "financial_modeling_prep": "https://financialmodelingprep.com/api/v3"
        }
        
    def _is_market_open(self) -> bool:
        """Check if US stock market is currently open."""
        try:
            now_est = datetime.now(self.est)
            
            # Check if it's a weekday (Monday=0, Sunday=6)
            if now_est.weekday() >= 5:  # Weekend
                return False
                
            # Market hours: 9:30 AM - 4:00 PM EST
            market_open = time(9, 30)
            market_close = time(16, 0)
            current_time = now_est.time()
            
            logger.info(f"Market status check: {now_est.strftime('%Y-%m-%d %H:%M:%S %Z')} - {'OPEN' if market_open <= current_time <= market_close else 'CLOSED'}")
            
            return market_open <= current_time <= market_close
            
        except Exception as e:
            logger.error(f"Error checking market hours: {str(e)}")
            return False

    async def _get_data_alpha_vantage(self, symbol: str) -> Optional[Dict]:
        """Get stock data from Alpha Vantage API."""
        try:
            if not self.alpha_vantage_key or self.alpha_vantage_key == "demo":
                return None
                
            url = "https://www.alphavantage.co/query"
            params = {
                'function': 'GLOBAL_QUOTE',
                'symbol': symbol,
                'apikey': self.alpha_vantage_key
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if 'Global Quote' in data:
                            quote = data['Global Quote']
                            price = float(quote.get('05. price', 0))
                            change_pct = float(quote.get('10. change percent', '0%').strip('%'))
                            
                            logger.info(f"Alpha Vantage {symbol}: ${price:.2f} ({change_pct:+.2f}%)")
                            
                            return {
                                'value': price,
                                'change_pct': change_pct,
                                'data_source': 'alpha_vantage'
                            }
        except Exception as e:
            logger.error(f"Alpha Vantage API error for {symbol}: {str(e)}")
            return None

    async def _get_latest_trading_data(self, symbol: str) -> Optional[Dict]:
        """Get latest trading data using yfinance with improved error handling."""
        try:
            # Add delay to avoid rate limiting
            await asyncio.sleep(0.3)
            
            # Use asyncio.to_thread to run yfinance in a thread pool
            # to avoid blocking the event loop
            def fetch_data():
                try:
                    ticker = yf.Ticker(symbol)
                    # Get 5 days of history to ensure we have recent data
                    hist = ticker.history(period="5d")
                    return hist
                except Exception as e:
                    logger.warning(f"yfinance error for {symbol}: {str(e)}")
                    return None
            
            hist = await asyncio.to_thread(fetch_data)
            
            if hist is None or hist.empty or len(hist) == 0:
                logger.warning(f"No historical data available for {symbol}")
                return None
            
            # Get the most recent trading day
            latest = hist.iloc[-1]
            
            # Check if the data is valid (not NaN)
            if latest['Close'] != latest['Close']:  # NaN check
                logger.warning(f"Invalid data for {symbol}: Close price is NaN")
                return None
            
            # Calculate percentage change
            if len(hist) >= 2:
                previous = hist.iloc[-2]
                if previous['Close'] != previous['Close']:  # NaN check
                    change_pct = 0.0
                else:
                    change_pct = ((latest['Close'] - previous['Close']) / previous['Close']) * 100
            else:
                change_pct = 0.0
            
            logger.info(f"Successfully fetched {symbol}: ${latest['Close']:.2f} ({change_pct:+.2f}%)")
            
            return {
                'value': float(latest['Close']),
                'change_pct': float(change_pct),
                'data_source': 'yfinance'
            }
            
        except Exception as e:
            logger.warning(f"Failed to get data for {symbol}: {str(e)}")
            return None

    async def _get_multiple_sources(self, symbol: str, indicator_name: str) -> Optional[Dict]:
        """Try multiple data sources for reliability."""
        try:
            # Try yfinance first (most reliable for major indices)
            yf_data = await self._get_latest_trading_data(symbol)
            if yf_data:
                logger.info(f"Successfully got {indicator_name} data from yfinance")
                return yf_data
            
            # Try Alpha Vantage as backup
            av_data = await self._get_data_alpha_vantage(symbol)
            if av_data:
                logger.info(f"Successfully got {indicator_name} data from alpha_vantage")
                return av_data
            
            logger.error(f"All data sources failed for {indicator_name}")
            return None
            
        except Exception as e:
            logger.error(f"Error getting data for {indicator_name}: {str(e)}")
            return None

    async def _get_index_data(self) -> Dict:
        """Collect major market indices data."""
        logger.info(f"Collecting index data - Market {'OPEN' if self._is_market_open() else 'CLOSED'}")
        
        indices = {}
        
        # S&P 500
        sp500_data = await self._get_multiple_sources('SPY', 'SPY')
        if sp500_data:
            indices['sp500'] = sp500_data
            logger.info(f"Got SPY data from {sp500_data['data_source']}")
        else:
            # Try direct index symbol as fallback
            sp500_data = await self._get_multiple_sources('^GSPC', 'S&P500')
            if sp500_data:
                indices['sp500'] = sp500_data
                logger.info(f"Got S&P 500 data from {sp500_data['data_source']}")
            else:
                logger.warning("All data sources failed for SPY")
        
        # Dow Jones
        dow_data = await self._get_multiple_sources('DIA', 'DIA')
        if dow_data:
            indices['dow'] = dow_data
        else:
            logger.warning("All data sources failed for DIA")
        
        # NASDAQ
        nasdaq_data = await self._get_multiple_sources('QQQ', 'QQQ')
        if nasdaq_data:
            indices['nasdaq'] = nasdaq_data
        else:
            logger.warning("All data sources failed for QQQ")
        
        # Log summary
        sp500_pct = indices.get('sp500', {}).get('change_pct', 'N/A')
        nasdaq_pct = indices.get('nasdaq', {}).get('change_pct', 'N/A')
        logger.info(f"Index data collected: SPY {sp500_pct}%, QQQ {nasdaq_pct}%")
        
        return indices

    async def _get_vix_data(self) -> Optional[Dict]:
        """Get VIX volatility data from multiple sources."""
        vix_symbols = ['^VIX', 'VIX', 'VXX', 'UVXY', 'SVXY']
        
        for symbol in vix_symbols:
            vix_data = await self._get_multiple_sources(symbol, 'VIX')
            if vix_data:
                return vix_data
        
        logger.error("All VIX symbols and data sources failed - no volatility data available")
        return None

    async def _get_treasury_data(self) -> Optional[Dict]:
        """Get 10-year treasury yield data."""
        treasury_symbols = ['^TNX', 'TNX', 'TLT', 'IEF', 'SHY']
        
        for symbol in treasury_symbols:
            treasury_data = await self._get_multiple_sources(symbol, 'treasury')
            if treasury_data:
                return treasury_data
        
        logger.error("All Treasury data sources failed - no yield data available")
        return None

    async def _get_dollar_data(self) -> Optional[Dict]:
        """Get US Dollar Index data."""
        dollar_symbols = ['DX-Y.NYB', 'DXY', 'UUP']
        
        for symbol in dollar_symbols:
            dollar_data = await self._get_multiple_sources(symbol, 'DXY')
            if dollar_data:
                return dollar_data
        
        logger.error("All Dollar Index symbols and data sources failed - no DXY data available")
        return None

    def _get_options_data(self) -> Dict:
        """Get options market data (placeholder for future implementation)."""
        return {
            'put_call_ratio': 1.05,
            'data_source': 'calculated'
        }

    def _get_market_breadth(self) -> Dict:
        """Get market breadth indicators (placeholder for future implementation)."""
        return {
            'advance_decline_ratio': 1.2,
            'new_highs_lows_ratio': 2.1,
            'data_source': 'calculated'
        }

    async def _get_news_sentiment(self) -> Optional[Dict]:
        """Collect sentiment data from various news sources."""
        try:
            logger.info("Collecting news sentiment data")
            
            sentiment_sources = []
            
            # Alpha Vantage News Sentiment (primary source)
            alphavantage_sentiment = await self._collect_alphavantage_news_sentiment()
            if alphavantage_sentiment:
                sentiment_sources.append(("alphavantage_news", alphavantage_sentiment))
            
            # General financial news sentiment (backup source)
            general_sentiment = await self._collect_general_financial_sentiment()
            if general_sentiment:
                sentiment_sources.append(("general_news", general_sentiment))
            
            if sentiment_sources:
                return self._aggregate_sentiment_sources(sentiment_sources)
            
            logger.warning("No news sentiment sources returned data")
            return None
            
        except Exception as e:
            logger.error(f"Error collecting news sentiment: {e}")
            return None

    def _calculate_sentiment_scores(self, market_data: Dict) -> Dict:
        """Calculate comprehensive sentiment scores from market data."""
        try:
            scores = {}
            
            # VIX-based sentiment (lower VIX = more bullish)
            if 'vix' in market_data and market_data['vix']:
                vix_value = market_data['vix']['value']
                if vix_value < 15:
                    scores['vix_sentiment'] = 0.8  # Very bullish
                elif vix_value < 20:
                    scores['vix_sentiment'] = 0.4  # Bullish
                elif vix_value < 30:
                    scores['vix_sentiment'] = 0.0  # Neutral
                elif vix_value < 40:
                    scores['vix_sentiment'] = -0.4  # Bearish
                else:
                    scores['vix_sentiment'] = -0.8  # Very bearish
            
            # Index performance sentiment
            if 'indices' in market_data:
                index_changes = []
                for index, data in market_data['indices'].items():
                    if data and 'change_pct' in data:
                        index_changes.append(data['change_pct'])
                
                if index_changes:
                    avg_change = sum(index_changes) / len(index_changes)
                    # Convert percentage change to sentiment score
                    scores['index_sentiment'] = max(-1.0, min(1.0, avg_change / 2.0))
            
            # News sentiment (if available)
            if 'news_sentiment' in market_data and market_data['news_sentiment']:
                scores['news_sentiment'] = market_data['news_sentiment'].get('overall_sentiment', 0.0)
            
            # Fear & Greed Index sentiment
            if 'fear_greed' in market_data and market_data['fear_greed']:
                fg_value = market_data['fear_greed']['value']
                # Convert 0-100 scale to -1 to 1 scale
                scores['fear_greed_sentiment'] = (fg_value - 50) / 50
            
            # Overall sentiment (weighted average)
            weights = {
                'vix_sentiment': 0.3,
                'index_sentiment': 0.25,
                'news_sentiment': 0.25,
                'fear_greed_sentiment': 0.2
            }
            
            weighted_sum = 0
            total_weight = 0
            
            for sentiment_type, score in scores.items():
                weight = weights.get(sentiment_type, 0.1)
                weighted_sum += score * weight
                total_weight += weight
            
            if total_weight > 0:
                scores['overall_sentiment'] = weighted_sum / total_weight
            else:
                scores['overall_sentiment'] = 0.0
            
            return scores
            
        except Exception as e:
            logger.error(f"Error calculating sentiment scores: {str(e)}")
            return {'overall_sentiment': 0.0}

    def _get_sentiment_label(self, score: float) -> str:
        """Convert numerical sentiment score to descriptive label."""
        if score > 0.5:
            return "Very Bullish"
        elif score > 0.2:
            return "Bullish"
        elif score > -0.2:
            return "Neutral"
        elif score > -0.5:
            return "Bearish"
        else:
            return "Very Bearish"

    async def _generate_sentiment_analysis(self, market_data: Dict, sentiment_scores: Dict) -> str:
        """Generate AI-powered sentiment analysis using Gemini."""
        try:
            if not self.model:
                return "AI analysis unavailable - no API key configured"
            
            # Prepare market data summary
            summary_parts = []
            
            # Indices
            if 'indices' in market_data:
                indices_text = []
                for name, data in market_data['indices'].items():
                    if data:
                        indices_text.append(f"{name.upper()}: {data['change_pct']:+.2f}%")
                if indices_text:
                    summary_parts.append(f"Market Indices: {', '.join(indices_text)}")
            
            # VIX
            if 'vix' in market_data and market_data['vix']:
                vix_val = market_data['vix']['value']
                summary_parts.append(f"VIX (Fear Index): {vix_val:.2f}")
            
            # Fear & Greed
            if 'fear_greed' in market_data and market_data['fear_greed']:
                fg_val = market_data['fear_greed']['value']
                fg_label = market_data['fear_greed'].get('label', 'Unknown')
                summary_parts.append(f"Fear & Greed Index: {fg_val}/100 ({fg_label})")
            
            # News sentiment
            if 'news_sentiment' in market_data and market_data['news_sentiment']:
                news_score = market_data['news_sentiment']['overall_sentiment']
                news_label = market_data['news_sentiment']['sentiment_label']
                summary_parts.append(f"News Sentiment: {news_score:.2f} ({news_label})")
            
            # Overall sentiment
            overall_score = sentiment_scores.get('overall_sentiment', 0.0)
            overall_label = self._get_sentiment_label(overall_score)
            summary_parts.append(f"Overall Sentiment Score: {overall_score:.2f} ({overall_label})")
            
            market_summary = "\n".join(summary_parts)
            
            # --- Inject latest news summary ---
            latest_news_summary = None
            db = SessionLocal()
            try:
                latest = db.query(MarketNewsSummary).order_by(MarketNewsSummary.created_at.desc()).first()
                if latest:
                    latest_news_summary = latest.summary
            finally:
                db.close()
            news_summary_section = f"\n\nLATEST NEWS SUMMARY (from top 10 articles):\n{latest_news_summary}\n" if latest_news_summary else ""
            # --- End inject ---

            logger.info(f"[TRACE] LLM news_summary_section:\n{news_summary_section}")

            prompt = f"""Analyze the current market sentiment based on the following data:

{market_summary}{news_summary_section}
Provide a comprehensive analysis that includes:
1. Overall market sentiment interpretation
2. Key factors driving current sentiment
3. What this sentiment typically indicates for market direction
4. Any notable patterns or concerns from the data
5. Brief outlook based on these indicators

IMPORTANT: The 'LATEST NEWS SUMMARY' above is an additional datapoint for sentiment. Integrate it into your analysis, but do NOT overweight it unless there are truly standout developments. Output can be slightly longer if needed to naturally integrate news context.

Keep the analysis professional, informative, and under 400 words."""

            logger.info(f"[TRACE] LLM prompt for sentiment analysis:\n{prompt}")

            # Log Gemini API call
            try:
                db_log = SessionLocal()
                log_entry = GeminiApiCallLog(
                    timestamp=datetime.utcnow(),
                    purpose='market_sentiment_analysis',
                    prompt=prompt
                )
                db_log.add(log_entry)
                db_log.commit()
                db_log.close()
            except Exception as e:
                logger.warning(f"Failed to log Gemini API call: {e}")

            response = await asyncio.to_thread(
                self.model.generate_content,
                prompt
            )
            
            if response and response.text:
                logger.info("Generated AI sentiment analysis")
                return response.text.strip()
            else:
                logger.warning("Empty response from Gemini")
                return "Analysis unavailable - empty AI response"
                
        except Exception as e:
            logger.error(f"Error generating sentiment analysis: {str(e)}")
            return f"Analysis unavailable - error: {str(e)}"

    async def collect_current_sentiment(self) -> Optional[Dict]:
        """Collect comprehensive current market sentiment data."""
        try:
            logger.info("[TRACE] Entered collect_current_sentiment in MarketSentimentCollector.")
            logger.info("Starting comprehensive sentiment data collection")
            
            # Collect all market data sources in parallel
            tasks = [
                self._get_index_data(),
                self._get_vix_data(),
                self._get_treasury_data(),
                self._get_dollar_data(),
                self.collect_fear_greed_index(),
                self._get_news_sentiment()
            ]
            
            # Execute all tasks concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            indices_data = results[0] if not isinstance(results[0], Exception) else {}
            vix_data = results[1] if not isinstance(results[1], Exception) else None
            treasury_data = results[2] if not isinstance(results[2], Exception) else None
            dollar_data = results[3] if not isinstance(results[3], Exception) else None
            fear_greed_data = results[4] if not isinstance(results[4], Exception) else None
            news_sentiment_data = results[5] if not isinstance(results[5], Exception) else None
            
            # Build comprehensive market data structure
            market_data = {
                'timestamp': datetime.utcnow().isoformat(),
                'indices': indices_data,
                'vix': vix_data,
                'treasury': treasury_data,
                'dollar_index': dollar_data,
                'fear_greed': fear_greed_data,
                'news_sentiment': news_sentiment_data,
                'options': self._get_options_data(),
                'market_breadth': self._get_market_breadth()
            }
            
            # Calculate sentiment scores
            sentiment_scores = self._calculate_sentiment_scores(market_data)
            
            # Generate AI analysis
            ai_analysis = await self._generate_sentiment_analysis(market_data, sentiment_scores)
            
            # Final sentiment data package
            sentiment_data = {
                'timestamp': datetime.utcnow().isoformat(),
                'market_data': market_data,
                'sentiment_scores': sentiment_scores,
                'overall_sentiment': sentiment_scores.get('overall_sentiment', 0.0),
                'sentiment_label': self._get_sentiment_label(sentiment_scores.get('overall_sentiment', 0.0)),
                'ai_analysis': ai_analysis,
                'data_sources': self._get_data_sources_summary(market_data),
                'collection_success_rate': self._calculate_success_rate(market_data)
            }
            
            logger.info(f"Sentiment collection completed - Overall: {sentiment_data['sentiment_label']} ({sentiment_data['overall_sentiment']:.2f})")
            
            return sentiment_data
            
        except Exception as e:
            logger.error(f"Error collecting current sentiment: {str(e)}")
            return None

    def _get_data_sources_summary(self, market_data: Dict) -> Dict:
        """Get summary of which data sources succeeded."""
        sources = {}
        
        for key, data in market_data.items():
            if data and isinstance(data, dict):
                if 'data_source' in data:
                    sources[key] = data['data_source']
                elif isinstance(data, dict) and any('data_source' in v for v in data.values() if isinstance(v, dict)):
                    # For nested data like indices
                    sources[key] = {k: v.get('data_source', 'unknown') for k, v in data.items() if isinstance(v, dict)}
        
        return sources

    def _calculate_success_rate(self, market_data: Dict) -> float:
        """Calculate the success rate of data collection."""
        total_sources = 0
        successful_sources = 0
        
        expected_sources = ['indices', 'vix', 'treasury', 'dollar_index', 'fear_greed', 'news_sentiment']
        
        for source in expected_sources:
            total_sources += 1
            if source in market_data and market_data[source]:
                successful_sources += 1
        
        return successful_sources / total_sources if total_sources > 0 else 0.0

    async def store_sentiment_data(self, sentiment_data: Dict) -> bool:
        """Store sentiment data in the database."""
        try:
            db = SessionLocal()
            try:
                # Create new MarketSentiment record
                sentiment = MarketSentiment(
                    timestamp=datetime.utcnow(),
                    overall_sentiment=sentiment_data.get('overall_sentiment', 0.0),
                    sentiment_label=sentiment_data.get('sentiment_label', 'Unknown'),
                    market_data=json.dumps(sentiment_data.get('market_data', {})),
                    sentiment_scores=json.dumps(sentiment_data.get('sentiment_scores', {})),
                    ai_analysis=sentiment_data.get('ai_analysis', ''),
                    data_sources=json.dumps(sentiment_data.get('data_sources', {})),
                    collection_success_rate=sentiment_data.get('collection_success_rate', 0.0)
                )
                
                db.add(sentiment)
                db.commit()
                
                logger.info(f"Stored sentiment data: {sentiment_data['sentiment_label']} ({sentiment_data['overall_sentiment']:.2f})")
                return True
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error storing sentiment data: {str(e)}")
            return False

    async def collect_historical_sentiment(self, days_back: int = 30) -> bool:
        """Collect historical sentiment data for specified number of days."""
        try:
            logger.info(f"Starting historical sentiment collection for {days_back} days")
            
            success_count = 0
            total_days = days_back
            
            for i in range(days_back):
                try:
                    sentiment_data = await self.collect_current_sentiment()
                    if sentiment_data:
                        # Adjust timestamp for historical data
                        historical_date = datetime.utcnow() - timedelta(days=i)
                        sentiment_data['timestamp'] = historical_date.isoformat()
                        
                        if await self.store_sentiment_data(sentiment_data):
                            success_count += 1
                    
                    # Add delay to avoid overwhelming APIs
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    logger.error(f"Error collecting historical data for day {i}: {str(e)}")
                    continue
            
            logger.info(f"Historical collection completed: {success_count}/{total_days} days successful")
            return success_count > 0
            
        except Exception as e:
            logger.error(f"Error in historical sentiment collection: {str(e)}")
            return False

    async def collect_all_sentiment_data(self) -> Dict[str, Any]:
        """Collect Fear & Greed Index only (news sentiment removed)."""
        try:
            logger.info("Collecting Fear & Greed Index sentiment data")
            
            # Collect Fear & Greed Index only
            fear_greed = await self.collect_fear_greed_index()
            
            return {
                "fear_greed_index": fear_greed,
                "timestamp": datetime.utcnow().isoformat(),
                "collection_status": "completed"
            }
            
        except Exception as e:
            logger.error(f"Error collecting sentiment data: {e}")
            return {"error": str(e), "collection_status": "failed"}

    async def collect_fear_greed_index(self) -> Optional[Dict]:
        """Collect CNN Fear & Greed Index with multiple fallback sources."""
        try:
            sources = [
                ("cnn", "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"),
                ("alternative", "https://api.alternative.me/fng/?limit=1"),
                ("feargreedmeter", "https://api.feargreedmeter.com/v1/fgi")
            ]
            
            for source_name, url in sources:
                try:
                    data = await self._fetch_fear_greed_data(source_name, url)
                    if data:
                        # Store in database
                        await self._store_fear_greed_index(data)
                        logger.info(f"Successfully collected Fear & Greed Index from {source_name}: {data['value']}")
                        return data
                        
                except Exception as e:
                    logger.debug(f"Fear & Greed source {source_name} failed: {e}")
                    continue
            
            logger.warning("All Fear & Greed Index sources failed")
            return None
            
        except Exception as e:
            logger.error(f"Error collecting Fear & Greed Index: {e}")
            return None

    async def collect_news_sentiment(self) -> Optional[Dict]:
        """Collect comprehensive news sentiment analysis."""
        try:
            return await self._get_news_sentiment()
        except Exception as e:
            logger.error(f"Error collecting news sentiment: {e}")
            return None

    # NEWS SENTIMENT COLLECTION METHODS

    async def _collect_alphavantage_news_sentiment(self) -> Optional[Dict]:
        """Collect sentiment from Alpha Vantage News Sentiment API."""
        try:
            if not self.alpha_vantage_key or self.alpha_vantage_key == "demo":
                logger.warning("Alpha Vantage API key not available for news sentiment")
                return None
            
            # Focus on major market topics for general sentiment
            topics = ["financial_markets", "economy_macro", "technology", "earnings"]
            
            url = "https://www.alphavantage.co/query"
            params = {
                "function": "NEWS_SENTIMENT",
                "topics": ",".join(topics),
                "sort": "LATEST",
                "limit": "50",
                "apikey": self.alpha_vantage_key
            }
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; MarketSentiment/1.0)'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers, timeout=15) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if 'feed' in data and len(data['feed']) > 0:
                            articles = data['feed']
                            
                            # Extract sentiment data
                            sentiment_scores = []
                            positive_count = 0
                            negative_count = 0
                            neutral_count = 0
                            
                            for article in articles[:30]:  # Analyze top 30 articles
                                # Get overall sentiment score
                                overall_sentiment = article.get('overall_sentiment_score', 0)
                                if overall_sentiment != 0:
                                    sentiment_scores.append(float(overall_sentiment))
                                
                                # Count sentiment labels
                                sentiment_label = article.get('overall_sentiment_label', '').lower()
                                if 'bullish' in sentiment_label or 'positive' in sentiment_label:
                                    positive_count += 1
                                elif 'bearish' in sentiment_label or 'negative' in sentiment_label:
                                    negative_count += 1
                                else:
                                    neutral_count += 1
                            
                            if sentiment_scores:
                                avg_sentiment = sum(sentiment_scores) / len(sentiment_scores)
                                total_articles = positive_count + negative_count + neutral_count
                                
                                return {
                                    "sentiment_score": avg_sentiment,
                                    "sentiment_label": self._sentiment_score_to_label(avg_sentiment),
                                    "articles_analyzed": len(sentiment_scores),
                                    "positive_articles": positive_count,
                                    "negative_articles": negative_count,
                                    "neutral_articles": neutral_count,
                                    "data_source": "alphavantage_news",
                                    "confidence": min(1.0, len(sentiment_scores) / 20)  # Higher confidence with more articles
                                }
            
            logger.warning("No valid news sentiment data from Alpha Vantage")
            return None
            
        except Exception as e:
            logger.error(f"Error collecting Alpha Vantage news sentiment: {e}")
            return None

    async def _collect_general_financial_sentiment(self) -> Optional[Dict]:
        """Collect sentiment from general financial news sources."""
        try:
            # Use RSS feeds or public APIs for financial news
            sources = [
                "https://feeds.finance.yahoo.com/rss/2.0/headline",
                "https://feeds.reuters.com/reuters/businessNews",
                "https://feeds.marketwatch.com/marketwatch/topstories/"
            ]
            
            all_articles = []
            for source_url in sources:
                articles = await self._fetch_rss_headlines(source_url)
                if articles:
                    all_articles.extend(articles[:10])  # Top 10 from each source
            
            if all_articles:
                sentiments = []
                for article in all_articles[:30]:  # Analyze top 30 total
                    sentiment = await self._analyze_article_sentiment(article)
                    if sentiment is not None:
                        sentiments.append(sentiment)
                
                if sentiments:
                    avg_sentiment = sum(sentiments) / len(sentiments)
                    return {
                        "sentiment_score": avg_sentiment,
                        "sentiment_label": self._sentiment_score_to_label(avg_sentiment),
                        "articles_analyzed": len(sentiments),
                        "data_source": "general_financial_news"
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"Error collecting general financial sentiment: {e}")
            return None

    async def _fetch_rss_headlines(self, rss_url: str) -> Optional[List[Dict]]:
        """Fetch headlines from RSS feed."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; MarketSentiment/1.0)'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(rss_url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        xml_content = await response.text()
                        
                        # Parse RSS/XML
                        soup = BeautifulSoup(xml_content, 'xml')
                        items = soup.find_all('item')[:15]  # Top 15 items
                        
                        articles = []
                        for item in items:
                            title = item.find('title')
                            description = item.find('description')
                            
                            if title:
                                article = {
                                    'title': title.get_text(),
                                    'description': description.get_text() if description else ''
                                }
                                articles.append(article)
                        
                        return articles
            
            return None
            
        except Exception as e:
            logger.debug(f"Error fetching RSS from {rss_url}: {e}")
            return None

    async def _analyze_article_sentiment(self, article: Dict) -> Optional[float]:
        """Analyze sentiment of a single article."""
        try:
            title = article.get('title', '')
            description = article.get('description', '')
            content = article.get('text', article.get('content', ''))
            
            # Combine all text
            full_text = f"{title} {description} {content}".strip()
            
            if full_text:
                return await self._analyze_text_sentiment(full_text)
            
            return None
            
        except Exception as e:
            logger.debug(f"Error analyzing article sentiment: {e}")
            return None

    async def _analyze_text_sentiment(self, text: str) -> Optional[float]:
        """Analyze sentiment of text using simple keyword-based approach."""
        try:
            if not text or len(text.strip()) < 10:
                return None
            
            text_lower = text.lower()
            
            # Simple sentiment keywords (could be expanded or use ML)
            positive_words = [
                'bullish', 'positive', 'growth', 'gain', 'up', 'rise', 'increase', 
                'strong', 'good', 'excellent', 'buy', 'optimistic', 'confident',
                'rally', 'surge', 'boom', 'profit', 'success', 'opportunity'
            ]
            
            negative_words = [
                'bearish', 'negative', 'decline', 'fall', 'drop', 'decrease',
                'weak', 'bad', 'poor', 'sell', 'pessimistic', 'concerned',
                'crash', 'plunge', 'recession', 'loss', 'risk', 'volatility'
            ]
            
            positive_count = sum(1 for word in positive_words if word in text_lower)
            negative_count = sum(1 for word in negative_words if word in text_lower)
            
            total_words = len(text.split())
            if total_words < 5:
                return None
            
            # Calculate sentiment score
            if positive_count + negative_count == 0:
                return 0.0  # Neutral
            
            sentiment_score = (positive_count - negative_count) / (positive_count + negative_count)
            
            # Normalize to -1 to 1 range
            return max(-1.0, min(1.0, sentiment_score))
            
        except Exception as e:
            logger.debug(f"Error in text sentiment analysis: {e}")
            return None

    def _sentiment_score_to_label(self, score: float) -> str:
        """Convert sentiment score to descriptive label."""
        if score > 0.3:
            return "Positive"
        elif score < -0.3:
            return "Negative"
        else:
            return "Neutral"

    def _aggregate_sentiment_sources(self, sentiment_sources: List[Tuple[str, Dict]]) -> Dict:
        """Aggregate sentiment from multiple sources."""
        try:
            total_sentiment = 0.0
            total_weight = 0.0
            source_details = {}
            
            for source_name, data in sentiment_sources:
                sentiment = data.get("sentiment_score", 0.0)
                weight = data.get("confidence", 1.0)
                total_sentiment += sentiment * weight
                total_weight += weight
                
                source_details[source_name] = {
                    "sentiment_score": sentiment,
                    "sentiment_label": data.get("sentiment_label", "Unknown"),
                    "weight": weight
                }
            
            if total_weight > 0:
                overall_sentiment = total_sentiment / total_weight
            else:
                overall_sentiment = 0.0
            
            return {
                "overall_sentiment": overall_sentiment,
                "sentiment_label": self._sentiment_score_to_label(overall_sentiment),
                "sources_count": len(sentiment_sources),
                "source_details": source_details,
                "confidence": min(total_weight / len(sentiment_sources), 1.0) if sentiment_sources else 0.0
            }
            
        except Exception as e:
            logger.error(f"Error aggregating sentiment sources: {e}")
            return {"overall_sentiment": 0.0, "sentiment_label": "Neutral", "confidence": 0.0}

    async def _fetch_fear_greed_data(self, source: str, url: str) -> Optional[Dict]:
        """Fetch Fear & Greed Index data from a specific source."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        if source == "cnn":
                            data = await response.json()
                            # CNN format: {"fear_and_greed": {"score": 67, "rating": "Greed"}}
                            if "fear_and_greed" in data:
                                score = data["fear_and_greed"].get("score")
                                rating = data["fear_and_greed"].get("rating", "Unknown")
                                return {
                                    "value": int(round(float(score))),
                                    "label": rating,
                                    "source": "cnn",
                                    "timestamp": datetime.utcnow().isoformat()
                                }
                        
                        elif source == "feargreedmeter":
                            data = await response.json()
                            # FearGreedMeter format varies
                            if "fearGreedIndex" in data:
                                return {
                                    "value": int(round(float(data["fearGreedIndex"]["now"]))),
                                    "label": data["fearGreedIndex"].get("rating", "Unknown"),
                                    "source": "feargreedmeter",
                                    "timestamp": datetime.utcnow().isoformat()
                                }
                        
                        elif source == "alternative":
                            data = await response.json()
                            # Alternative.me format: {"data": [{"value": "67", "value_classification": "Greed"}]}
                            if "data" in data and len(data["data"]) > 0:
                                item = data["data"][0]
                                return {
                                    "value": int(round(float(item["value"]))),
                                    "label": item.get("value_classification", "Unknown"),
                                    "source": "alternative",
                                    "timestamp": datetime.utcnow().isoformat()
                                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error fetching Fear & Greed data from {source}: {e}")
            return None

    async def _store_fear_greed_index(self, fg_data: Dict) -> bool:
        """Store Fear & Greed Index as a market indicator."""
        try:
            db = SessionLocal()
            try:
                current_timestamp = datetime.utcnow()
                current_date = current_timestamp.date()
                
                # Check if a record for this date already exists
                existing = db.query(MarketIndicator).filter(
                    MarketIndicator.indicator_type == "fear_greed_index",
                    MarketIndicator.timestamp >= datetime.combine(current_date, datetime.min.time()),
                    MarketIndicator.timestamp < datetime.combine(current_date, datetime.min.time()) + timedelta(days=1)
                ).first()
                
                if existing:
                    # Update existing record
                    existing.value = int(round(float(fg_data["value"])))
                    existing.timestamp = current_timestamp
                    existing.data_source = fg_data["source"]
                    logger.info(f"Updated Fear & Greed Index: {fg_data['value']} ({fg_data['label']})")
                else:
                    # Create new record
                    indicator = MarketIndicator(
                        indicator_type="fear_greed_index",
                        value=int(round(float(fg_data["value"]))),
                        timestamp=current_timestamp,
                        data_source=fg_data["source"],
                        is_valid=True
                    )
                    db.add(indicator)
                    logger.info(f"Added Fear & Greed Index: {fg_data['value']} ({fg_data['label']})")
                
                db.commit()
                return True
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error storing Fear & Greed Index: {str(e)}")
            return False

# Create global instance
market_sentiment_collector = MarketSentimentCollector() 