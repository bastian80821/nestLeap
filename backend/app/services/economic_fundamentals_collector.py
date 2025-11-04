"""
Economic Fundamentals Collector Service

Collects economic indicators and fundamental data from various sources including:
- FRED (Federal Reserve Economic Data)
- Bureau of Labor Statistics
- Bureau of Economic Analysis
- Other economic data sources
"""

import asyncio
import aiohttp
import json
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta, date
import pytz
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, or_, not_
from ..database import SessionLocal
from ..models import EconomicIndicator, EconomicEvent, FundamentalsAnalysis, MarketNewsSummary, GeminiApiCallLog
from ..config import settings
import google.generativeai as genai
import re
from bs4 import BeautifulSoup


class EconomicFundamentalsCollector:
    """Collects economic fundamentals data from multiple sources."""
    
    ALLOWED_INDICATORS = [
        'gdp_yoy_growth_bea',
        'cpi_yoy_inflation',
        'fed_funds_rate',
        'unemployment_rate',
        'retail_sales',
        'industrial_production',
        'home_price_index',
        'treasury_10y_yield'
    ]
    
    def __init__(self):
        self.fred_api_key = getattr(settings, 'fred_api_key', None) or "demo"
        self.bls_api_key = getattr(settings, 'bls_api_key', None)
        
        # Configure Gemini if API key is available
        if hasattr(settings, 'google_api_key') and settings.google_api_key:
            genai.configure(api_key=settings.google_api_key)
            self.model = genai.GenerativeModel('gemini-2.5-flash')
        else:
            self.model = None
        
        # Only keep indicators shown on the frontend
        self.indicators_config = {
            # GDP YoY Growth (BEA)
            'gdp_yoy_growth_bea': {
                'fred_id': None,  # Not used
                'name': 'Real GDP YoY Growth (BEA)',
                'category': 'gdp',
                'unit': '%',
                'period_type': 'quarterly',
                'importance': 'high'
            },
            # CPI YoY Inflation (calculated from raw CPI index)
            'cpi_yoy_inflation': {
                'fred_id': 'CPIAUCSL',  # Use raw CPI index, calculate YoY ourselves
                'name': 'CPI YoY Inflation Rate',
                'category': 'inflation',
                'unit': '%',
                'period_type': 'monthly',
                'importance': 'high',
                'needs_yoy_calculation': True  # Flag to calculate YoY percentage change
            },
            # Fed Funds Rate (using upper target rate set by Fed)
            'fed_funds_rate': {
                'fred_id': 'DFEDTARU',
                'name': 'Federal Funds Target Rate (Upper)',
                'category': 'interest_rates',
                'unit': '%',
                'period_type': 'monthly',
                'importance': 'high'
            },
            # Unemployment Rate
            'unemployment_rate': {
                'fred_id': 'UNRATE',
                'name': 'Unemployment Rate',
                'category': 'employment',
                'unit': '%',
                'period_type': 'monthly',
                'importance': 'high'
            },
            # Retail Sales
            'retail_sales': {
                'fred_id': 'RSXFS',
                'name': 'Retail Sales (Ex Auto)',
                'category': 'retail',
                'unit': 'millions',
                'period_type': 'monthly',
                'importance': 'medium'
            },
            # Industrial Production
            'industrial_production': {
                'fred_id': 'INDPRO',
                'name': 'Industrial Production Index',
                'category': 'manufacturing',
                'unit': 'index',
                'period_type': 'monthly',
                'importance': 'medium'
            },
            # Home Price Index
            'home_price_index': {
                'fred_id': 'CSUSHPINSA',
                'name': 'Case-Shiller Home Price Index',
                'category': 'home_prices',
                'unit': 'index',
                'period_type': 'monthly',
                'importance': 'medium'
            },
            # 10-Year Treasury Yield
            'treasury_10y_yield': {
                'fred_id': 'GS10',
                'name': '10-Year Treasury Yield',
                'category': 'interest_rates',
                'unit': '%',
                'period_type': 'daily',
                'importance': 'high'
            }
        }
        
        # Economic events calendar
        self.upcoming_events = [
            {
                'event_name': 'Consumer Price Index (CPI)',
                'category': 'inflation',
                'importance': 'high',
                'typical_release_day': 10,  # Usually around 10th of month
                'impact_description': 'Primary measure of inflation, directly impacts Fed policy decisions'
            },
            {
                'event_name': 'Employment Situation Report',
                'category': 'employment', 
                'importance': 'high',
                'typical_release_day': 1,  # First Friday of month
                'impact_description': 'Key labor market indicator including unemployment rate and job growth'
            },
            {
                'event_name': 'Federal Open Market Committee Meeting',
                'category': 'interest_rates',
                'importance': 'high',
                'typical_release_day': None,  # Scheduled dates
                'impact_description': 'Fed monetary policy decisions affecting interest rates'
            },
            {
                'event_name': 'Gross Domestic Product (GDP)',
                'category': 'gdp',
                'importance': 'high',
                'typical_release_day': None,  # End of quarter
                'impact_description': 'Comprehensive measure of economic growth and activity'
            }
        ]

    async def collect_fred_data(self, series_id: str, start_date: str = None) -> Optional[List[Dict]]:
        """Collect data from FRED API."""
        try:
            if not self.fred_api_key or self.fred_api_key == "demo":
                logger.warning("FRED API key not configured, using mock data")
                return await self._get_mock_fred_data(series_id)
                
            if not start_date:
                # Get last 2 years of data
                start_date = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')
            
            url = "https://api.stlouisfed.org/fred/series/observations"
            params = {
                'series_id': series_id,
                'api_key': self.fred_api_key,
                'file_type': 'json',
                'start_date': start_date,
                'sort_order': 'desc',
                'limit': 100
            }
            
            # Add timeout to prevent hanging
            timeout = aiohttp.ClientTimeout(total=10.0, connect=5.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        observations = data.get('observations', [])
                        
                        # Filter out missing values
                        valid_observations = [
                            obs for obs in observations 
                            if obs.get('value') != '.' and obs.get('value') is not None
                        ]
                        
                        logger.info(f"Retrieved {len(valid_observations)} observations for {series_id}")
                        return valid_observations
                    else:
                        logger.error(f"FRED API error for {series_id}: {response.status}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.warning(f"FRED API timeout for {series_id}")
            return None
        except Exception as e:
            logger.error(f"Error fetching FRED data for {series_id}: {str(e)}")
            return None

    async def _get_mock_fred_data(self, series_id: str) -> List[Dict]:
        """Generate mock data when FRED API is not available."""
        logger.info(f"Generating mock data for {series_id}")
        
        # Create realistic mock data based on series type
        mock_data = []
        base_date = datetime.now() - timedelta(days=365)
        
        if 'CPI' in series_id or 'PCE' in series_id:
            # Inflation data - trending upward
            base_value = 280.0
            for i in range(12):
                date_str = (base_date + timedelta(days=30*i)).strftime('%Y-%m-%d')
                value = base_value + (i * 2.5) + (i * 0.1 * i)  # Realistic inflation trend
                mock_data.append({'date': date_str, 'value': str(round(value, 1))})
        
        elif 'UNRATE' in series_id:
            # Unemployment rate - fluctuating around 3.7%
            base_value = 3.7
            for i in range(12):
                date_str = (base_date + timedelta(days=30*i)).strftime('%Y-%m-%d')
                value = base_value + (0.2 * (i % 3 - 1))  # Small fluctuations
                mock_data.append({'date': date_str, 'value': str(round(value, 1))})
        
        elif 'FEDFUNDS' in series_id:
            # Fed funds rate - recent hiking cycle
            base_value = 0.25
            for i in range(12):
                date_str = (base_date + timedelta(days=30*i)).strftime('%Y-%m-%d')
                value = min(5.5, base_value + (i * 0.5))  # Rate hiking cycle
                mock_data.append({'date': date_str, 'value': str(round(value, 2))})
        
        else:
            # Generic positive trending data
            base_value = 100.0
            for i in range(12):
                date_str = (base_date + timedelta(days=30*i)).strftime('%Y-%m-%d')
                value = base_value + (i * 2)
                mock_data.append({'date': date_str, 'value': str(round(value, 1))})
        
        return mock_data

    async def collect_indicator_data(self, indicator_key: str, store_full_history: bool = False) -> Optional[List[Dict]]:
        """Collect data for a specific economic indicator."""
        if indicator_key not in self.indicators_config:
            logger.error(f"Unknown indicator: {indicator_key}")
            return None
        
        # Special case: Get Treasury yield from live market data (much faster and more current)
        if indicator_key == 'treasury_10y_yield':
            return await self._get_live_treasury_data()
            
        config = self.indicators_config[indicator_key]
        fred_data = await self.collect_fred_data(config['fred_id'])
        
        if not fred_data:
            return None
        
        # Check if we need to calculate YoY percentage change (for CPI inflation)
        needs_yoy_calc = config.get('needs_yoy_calculation', False)
            
        # Process all observations if storing full history, otherwise just the latest
        observations_to_process = fred_data if store_full_history else [fred_data[0]]
        
        indicator_data_list = []
        for i, observation in enumerate(observations_to_process):
            # Calculate previous value for comparison (from the next observation in time)
            previous_value = None
            if i < len(fred_data) - 1:
                try:
                    previous_value = float(fred_data[i + 1]['value'])
                except (ValueError, TypeError):
                    previous_value = None
            
            # Calculate the value (YoY if needed)
            current_value = float(observation['value'])
            
            if needs_yoy_calc:
                # For YoY calculation, we need the value from 12 months ago
                yoy_value = None
                if i + 12 < len(fred_data):
                    try:
                        value_12mo_ago = float(fred_data[i + 12]['value'])
                        # Calculate YoY percentage change
                        yoy_value = ((current_value - value_12mo_ago) / value_12mo_ago) * 100
                        logger.debug(f"CPI YoY: {current_value:.2f} vs {value_12mo_ago:.2f} 12mo ago = {yoy_value:.2f}%")
                    except (ValueError, TypeError, ZeroDivisionError):
                        yoy_value = None
                
                # Skip if we can't calculate YoY (need 12 months of history)
                if yoy_value is None:
                    continue
                    
                current_value = yoy_value
            
            indicator_data = {
                'indicator_name': indicator_key,
                'category': config['category'],
                'value': current_value,
                'unit': config['unit'],
                'period_type': config['period_type'],
                'reference_date': datetime.strptime(observation['date'], '%Y-%m-%d').date(),
                'release_date': datetime.now().date(),  # Approximate
                'source': 'fred',
                'previous_value': previous_value,
                'display_name': config['name'],
                'importance': config['importance']
            }
            indicator_data_list.append(indicator_data)
        
        return indicator_data_list
    
    async def _get_live_treasury_data(self) -> Optional[List[Dict]]:
        """Get live 10-Year Treasury yield from market data collector (same source as live stocks)."""
        try:
            from .historical_market_collector import HistoricalMarketCollector
            
            # Use our existing live market data collector
            market_collector = HistoricalMarketCollector()
            
            # Get live treasury data (^TNX symbol)
            treasury_data = await market_collector.collect_indicator_data('treasury_10y', '^TNX')
            
            if not treasury_data:
                logger.warning("Failed to get live Treasury data, falling back to FRED")
                return None
            
            # Get historical data for previous value calculation
            db = SessionLocal()
            try:
                # Get the most recent Treasury yield from our database for comparison
                recent_treasury = db.query(EconomicIndicator).filter(
                    EconomicIndicator.indicator_name == 'treasury_10y_yield'
                ).order_by(EconomicIndicator.reference_date.desc()).first()
                
                previous_value = recent_treasury.value if recent_treasury else None
                    
            finally:
                db.close()
            
            # Convert market data to fundamentals format
            config = self.indicators_config['treasury_10y_yield']
            
            treasury_fundamental = [{
                'indicator_name': 'treasury_10y_yield',
                'category': config['category'],
                'value': treasury_data['value'],
                'unit': config['unit'],
                'period_type': 'daily',  # Live data is daily
                'reference_date': datetime.now().date(),
                'release_date': datetime.now().date(),
                'source': f"live_market_{treasury_data['data_source']}",
                'previous_value': previous_value,
                'display_name': config['name'],
                'importance': config['importance']
            }]
            
            logger.info(f"✅ Got LIVE Treasury yield: {treasury_data['value']:.2f}% from {treasury_data['data_source']}")
            return treasury_fundamental
            
        except Exception as e:
            logger.error(f"Error getting live Treasury data: {e}")
            return None

    async def collect_bea_gdp_yoy_growth(self) -> list:
        """Fetch quarterly real GDP YoY growth rates from BEA API (Table 1.1.11, Line 1)."""
        api_key = getattr(settings, 'bea_api_key', None)
        if not api_key:
            logger.error('BEA API key not configured')
            return []
        url = 'https://apps.bea.gov/api/data/'
        params = {
            'UserID': api_key,
            'method': 'GetData',
            'datasetname': 'NIPA',
            'TableName': 'T10111',
            'Frequency': 'Q',
            'Year': 'ALL',
            'ResultFormat': 'JSON'
        }
        results = []
        try:
            # Add timeout to prevent hanging
            timeout = aiohttp.ClientTimeout(total=15.0, connect=5.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        logger.error(f'BEA API error: {response.status}')
                        return []
                    data = await response.json()
                    if 'Data' not in data.get('BEAAPI', {}).get('Results', {}):
                        logger.error(f'BEA API response missing Data key: {json.dumps(data)}')
                        return []
                    
                    table_data = data['BEAAPI']['Results']['Data']
                    
                    # Filter for GDP data (Line 1, real GDP percent change)
                    gdp_data = [row for row in table_data if row.get('LineDescription', '').lower().find('percent change from preceding period') != -1]
                    
                    # Process recent quarters only (last 8 quarters)
                    for row in gdp_data[-8:]:
                        try:
                            year = int(row['TimePeriod'][:4])
                            quarter = int(row['TimePeriod'][5:])
                            value = float(row['DataValue'])
                            
                            # Convert to reference date (end of quarter)
                            quarter_end_month = quarter * 3
                            reference_date = date(year, quarter_end_month, 1)
                            
                            # Calculate quarter label
                            quarter_label = f"Q{quarter} {year}"
                            
                            results.append({
                                'indicator_name': 'gdp_yoy_growth_bea',
                                'category': 'gdp',
                                'value': value,
                                'unit': '%',
                                'period_type': 'quarterly',
                                'reference_date': reference_date,
                                'release_date': date.today(),
                                'source': 'bea_api',
                                'quarter_label': quarter_label,
                                'display_name': 'Real GDP YoY Growth (BEA)',
                                'importance': 'high'
                            })
                        except (ValueError, KeyError) as e:
                            logger.warning(f'Error parsing BEA GDP row: {e}')
                            continue
                    
                    logger.info(f'Successfully fetched {len(results)} GDP quarters from BEA API')
                    return results
                    
        except asyncio.TimeoutError:
            logger.warning('BEA API timeout - using fallback data if available')
            return []
        except Exception as e:
            logger.error(f'Error fetching BEA GDP data: {e}')
            return []

    async def crawl_bea_gdp_web(self) -> list:
        """Crawl the BEA GDP page for the latest quarter and growth rate. Only return if newer than API data."""
        url = 'https://www.bea.gov/data/gdp/gross-domestic-product'
        results = []
        try:
            # Add timeout to prevent hanging
            timeout = aiohttp.ClientTimeout(total=10.0, connect=5.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        logger.error(f'BEA web crawl error: {response.status}')
                        return []
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    # Look for the table with the latest GDP numbers
                    # Example: | Q1 2025 (3rd) | -0.5% |
                    table = soup.find('table')
                    if not table:
                        logger.error('BEA GDP table not found on web page')
                        return []
                    rows = table.find_all('tr')
                    for row in rows:
                        cells = row.find_all(['td', 'th'])
                        if len(cells) >= 2:
                            quarter_text = cells[0].get_text(strip=True)
                            value_text = cells[1].get_text(strip=True)
                            # Match quarter and estimate type, e.g., Q1 2025 (3rd)
                            m = re.match(r'Q([1-4]) (\d{4}) \(([^)]+)\)', quarter_text)
                            if m:
                                q = int(m.group(1))
                                year = int(m.group(2))
                                estimate_type = m.group(3)
                                # Convert to reference_date (Jan=Q4 prev year, Apr=Q1, Jul=Q2, Oct=Q3)
                                if q == 1:
                                    month = 4
                                elif q == 2:
                                    month = 7
                                elif q == 3:
                                    month = 10
                                elif q == 4:
                                    month = 1
                                    year += 1
                                reference_date = date(year, month, 1)
                                # Parse value (e.g., -0.5% or +2.4%)
                                value_match = re.match(r'([+-]?\d+(?:\.\d+)?)%', value_text)
                                if value_match:
                                    value = float(value_match.group(1))
                                    results.append({
                                        'indicator_name': 'gdp_yoy_growth_bea',
                                        'category': 'gdp',
                                        'value': value,
                                        'unit': '%',
                                        'period_type': 'quarterly',
                                        'reference_date': reference_date,
                                        'release_date': datetime.now().date(),
                                        'source': 'bea_web',
                                        'previous_value': None,
                                        'display_name': f'Real GDP YoY Growth (BEA, {estimate_type})',
                                        'importance': 'high',
                                        'estimate_type': estimate_type
                                    })
                    return results
        except Exception as e:
            logger.error(f'Error crawling BEA GDP web page: {e}')
            return []

    async def collect_all_indicators(self, store_full_history: bool = False) -> List[Dict]:
        """Collect data for all configured economic indicators."""
        logger.info(f"Starting collection of all economic indicators (full_history={store_full_history})")
        
        tasks = []
        for indicator_key in self.indicators_config.keys():
            if indicator_key == 'gdp_yoy_growth_bea':
                continue  # handled separately
            tasks.append(self.collect_indicator_data(indicator_key, store_full_history))
        
        # Collect all indicators concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out failed requests and flatten the results
        successful_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Failed to collect {list(self.indicators_config.keys())[i]}: {result}")
            elif result is not None:
                # result is now a list of dictionaries, so extend instead of append
                successful_results.extend(result)
        
        # Fetch BEA GDP YoY growth from API
        bea_gdp_growth = await self.collect_bea_gdp_yoy_growth()
        successful_results.extend(bea_gdp_growth)
        # Fetch BEA GDP from web if newer than API
        web_gdp = await self.crawl_bea_gdp_web()
        # Find latest API date
        api_dates = {d['reference_date'] for d in bea_gdp_growth}
        for web_entry in web_gdp:
            if web_entry['reference_date'] not in api_dates:
                successful_results.append(web_entry)
        
        logger.info(f"Successfully collected {len(successful_results)} indicator data points (including BEA GDP YoY growth and web crawl if newer)")
        return successful_results

    async def store_indicators(self, indicators_data: List[Dict], allow_duplicates: bool = False) -> Dict[str, int]:
        """Store economic indicators in the database with duplicate prevention."""
        try:
            db = SessionLocal()
            
            stored_count = 0
            updated_count = 0
            skipped_count = 0
            
            for indicator_data in indicators_data:
                # Check if we already have this data point
                existing = db.query(EconomicIndicator).filter(
                    and_(
                        EconomicIndicator.indicator_name == indicator_data['indicator_name'],
                        EconomicIndicator.reference_date == indicator_data['reference_date']
                    )
                ).first()
                
                if not existing:
                    # New data point - store it
                    indicator = EconomicIndicator(
                        indicator_name=indicator_data['indicator_name'],
                        category=indicator_data['category'],
                        value=indicator_data['value'],
                        unit=indicator_data['unit'],
                        period_type=indicator_data['period_type'],
                        reference_date=indicator_data['reference_date'],
                        release_date=indicator_data['release_date'],
                        source=indicator_data['source'],
                        previous_value=indicator_data.get('previous_value')
                    )
                    db.add(indicator)
                    stored_count += 1
                else:
                    # Data point exists - check if value has changed (revision)
                    if existing.value != indicator_data['value']:
                        existing.value = indicator_data['value']
                        existing.previous_value = indicator_data.get('previous_value')
                        existing.is_revised = True
                        existing.release_date = indicator_data['release_date']
                        updated_count += 1
                    else:
                        skipped_count += 1
            
            db.commit()
            
            result = {
                'stored': stored_count,
                'updated': updated_count, 
                'skipped': skipped_count,
                'total_processed': len(indicators_data)
            }
            
            logger.info(f"Storage results: {stored_count} new, {updated_count} updated, {skipped_count} skipped out of {len(indicators_data)} total")
            return result
            
        except Exception as e:
            logger.error(f"Error storing indicators: {str(e)}")
            db.rollback()
            return {'stored': 0, 'updated': 0, 'skipped': 0, 'total_processed': 0, 'error': str(e)}
        finally:
            db.close()

    async def generate_fundamentals_analysis(self) -> Optional[Dict]:
        """Generate LLM analysis using the new EconomicFundamentalsAgent"""
        try:
            from ..agents.economic_fundamentals_agent import EconomicFundamentalsAgent
            
            # Use the new agent for analysis
            agent = EconomicFundamentalsAgent()
            analysis = await agent.get_latest_analysis()
            
            # If no recent analysis exists, trigger agent cycle
            if 'error' in analysis:
                await agent.run_cycle()
                analysis = await agent.get_latest_analysis()
            
            return analysis if 'error' not in analysis else None
            
        except Exception as e:
            logger.error(f"Error generating fundamentals analysis with agent: {e}")
            # Fallback to original analysis method
            return await self._generate_legacy_analysis()
            
    async def _generate_legacy_analysis(self) -> Optional[Dict]:
        """Legacy analysis method as fallback"""
        if not self.model:
            logger.warning("LLM not configured, skipping fundamentals analysis")
            return None
        try:
            db = SessionLocal()
            # --- Inject latest market news summary ---
            latest_news_summary = None
            try:
                latest_summary_obj = db.query(MarketNewsSummary).order_by(MarketNewsSummary.created_at.desc()).first()
                if latest_summary_obj:
                    latest_news_summary = latest_summary_obj.summary
            except Exception as e:
                logger.warning(f"Could not fetch latest market news summary: {e}")
            # --- End inject ---
            allowed_categories = ['gdp', 'inflation', 'interest_rates', 'employment', 'home_prices', 'manufacturing']
            allowed_indicators = {
                'gdp': ['gdp_yoy_growth_bea'],
                'inflation': ['cpi_yoy_inflation'],
                'interest_rates': ['fed_funds_rate', 'treasury_10y_yield'],
                'employment': ['unemployment_rate'],
                'home_prices': ['home_price_index'],
                'manufacturing': ['industrial_production']
            }
            # Collect full time series for each indicator (up to 36 months/quarters)
            time_series = {}
            for category in allowed_categories:
                indicators = db.query(EconomicIndicator).filter(
                    EconomicIndicator.category == category,
                    EconomicIndicator.indicator_name.in_(allowed_indicators[category])
                ).order_by(
                    EconomicIndicator.reference_date.asc()
                ).all()
                time_series[category] = [
                    {
                        'name': ind.indicator_name,
                        'value': ind.value,
                        'unit': ind.unit,
                        'date': ind.reference_date.strftime('%Y-%m-%d'),
                        'source': ind.source
                    }
                    for ind in indicators
                ]
            db.close()
            # Build structured prompt for Gemini
            from datetime import datetime
            current_date = datetime.utcnow().strftime('%Y-%m-%d')
            news_section = f"\n\nLATEST MARKET NEWS SUMMARY:\n{latest_news_summary}\n" if latest_news_summary else ""
            prompt = (
                f"You are an expert macroeconomic analyst. "
                f"The current date is {current_date}. "
                "You will receive the full time series for six key US economic indicators as JSON. "
                "IMPORTANT: For GDP, a date like '2025-04-01' refers to Q1 2025 (the quarter ending in March, reported in April). For monthly indicators, the date is the reference month, but the data is typically released with a lag. Always use the provided dates as the reference period for the data, not as the release or current period."
                "You will start by examining the time series and understanding what happened in recent years, by focusing on the relationships between indicators (e.g., how inflation, unemployment, GDP, and interest rates interact). "
                "You will then contrast this with whatever data is available for the most recent 4 months (you know this through the current date). This should give you an understanding of the current situation."
                "Now, for your future assesment, you should look at how factors interact. For example, if inflation is low and interest rates are high, there is potential for future rate cuts. If the economy contracted but interest rates are high, is that a sign of a true recession or could this be fixed by lowering interest rates? "
                "You are also given a summary of the latest market news. you should never go into specific events (this is a daily summary), but it can help you understand what's currently going on. for example, if interest rates are high, is there evidence from the news that this will change? if so, how would such a move fit in with the rest of the data? Use the news to help explain why something is happening (i.e. are interest rates high because of tariffs? is that likely to change?)"
                "Think of the big picture between the indicators, and about future scenarios. Use your own knowlege and historically healthy or unhealthy levels for each indicator to help you make your assessment."
                "Now that you thought about these things, you will internally make an assesment of the situation, either bullish, neutral, or bearish. You will only assess as bullish or bearish if factors start to significantly deviate form where they have historially been (i.e. 2021 inflation, 2022 interest rate hikes which you can see in the time series). You will start your text with summarizing the situation and your assesment. this is followed by a sentence of historical context, and then two sentences outlining possible future scenarios."
                "Never say sentences such as more data is needed. if necessary, focus instead on the indicators or decisions investors should monitor. Never mention specific numbers, and never repeat yourself (i.e. never mention gdp twice). Never explicitly mention the word news. the summary should fit together and be smooth to read."
                + news_section +
                "Return a JSON object with: "
                "overall_assessment (bullish, neutral, or bearish), "
                "economic_cycle_stage (early_cycle, mid_cycle, late_cycle, recession), "
                "monetary_policy_stance (accommodative, neutral, restrictive), "
                "inflation_outlook (rising, stable, moderating, declining), "
                "employment_outlook (strong, moderate, weak, deteriorating), "
                "confidence_level (0-1), and explanation (4 sentences, plain text, no markdown). "
                "Focus only on the data provided, news, and your own knowledge of macroeconomics."
                "\n\nECONOMIC_INDICATORS_TIME_SERIES = " + json.dumps(time_series, indent=2) + "\n\n"
                "Respond ONLY with a valid JSON object like: {\"overall_assessment\": \"neutral\", \"economic_cycle_stage\": \"late_cycle\", \"monetary_policy_stance\": \"restrictive\", \"inflation_outlook\": \"moderating\", \"employment_outlook\": \"moderate\", \"confidence_level\": 0.7, \"explanation\": \"...\"}"
            )
            # Log Gemini API call
            try:
                db_log = SessionLocal()
                log_entry = GeminiApiCallLog(
                    timestamp=datetime.utcnow(),
                    purpose='fundamentals_analysis',
                    prompt=prompt
                )
                db_log.add(log_entry)
                db_log.commit()
                db_log.close()
            except Exception as e:
                logger.warning(f"Failed to log Gemini API call: {e}")
            # Call Gemini
            response = await asyncio.to_thread(
                self.model.generate_content,
                prompt
            )
            # Try to parse JSON from Gemini's response
            import re
            import json as pyjson
            match = re.search(r'\{[\s\S]*\}', response.text)
            if match:
                try:
                    analysis = pyjson.loads(match.group(0))
                    # Add analysis_date for frontend display
                    analysis['analysis_date'] = datetime.utcnow().isoformat()
                    return analysis
                except Exception as e:
                    logger.error(f"Failed to parse LLM JSON: {e}\nResponse: {response.text}")
            # Fallback if no valid JSON
            logger.error(f"LLM did not return valid JSON. Response: {response.text}")
            return {
                'overall_assessment': 'neutral',
                'confidence_level': 0.5,
                'explanation': 'The LLM did not return a valid analysis.',
                'analysis_date': datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Error generating fundamentals analysis: {str(e)}")
            return None

    async def collect_and_analyze_fundamentals(self, store_full_history: bool = False) -> Dict[str, Any]:
        """Main method to collect all fundamentals data and generate analysis."""
        collection_type = "full historical" if store_full_history else "incremental"
        logger.info(f"Starting {collection_type} fundamentals data collection and analysis")
        
        # Collect indicator data
        indicators_data = await self.collect_all_indicators(store_full_history)
        
        # Store in database with duplicate prevention
        storage_results = await self.store_indicators(indicators_data)
        
        # Generate LLM analysis if we have new data
        analysis = None
        analysis_stored = False
        if storage_results.get('stored', 0) > 0 or storage_results.get('updated', 0) > 0:
            analysis = await self.generate_fundamentals_analysis()
            if analysis:
                analysis_stored = await self._store_analysis(analysis)
        
        return {
            'collection_type': collection_type,
            'indicators_collected': len(indicators_data),
            'storage_results': storage_results,
            'analysis_generated': analysis is not None,
            'analysis_stored': analysis_stored,
            'timestamp': datetime.now().isoformat()
        }
    
    async def backfill_historical_data(self, days_back: int = 730) -> Dict[str, Any]:
        """Backfill historical economic data for the specified period."""
        logger.info(f"Starting historical data backfill for {days_back} days")
        
        # Store full history for backfill
        return await self.collect_and_analyze_fundamentals(store_full_history=True)
    
    async def collect_latest_data(self) -> Dict[str, Any]:
        """Collect only the latest data points (incremental update)."""
        logger.info("Starting incremental data collection")
        
        # Store only latest data points
        return await self.collect_and_analyze_fundamentals(store_full_history=False)

    async def _store_analysis(self, analysis_data: Dict) -> bool:
        """Store fundamentals analysis in database."""
        try:
            db = SessionLocal()
            analysis = FundamentalsAnalysis(
                overall_assessment=analysis_data.get('overall_assessment'),
                confidence_level=analysis_data.get('confidence_level'),
                explanation=analysis_data.get('explanation'),
                economic_cycle_stage=analysis_data.get('economic_cycle_stage'),
                inflation_outlook=analysis_data.get('inflation_outlook'),
                employment_outlook=analysis_data.get('employment_outlook'),
                monetary_policy_stance=analysis_data.get('monetary_policy_stance'),
                key_insights=None,
                market_implications=None,
                sector_impacts=None,
                risk_factors=None,
                data_period_start=None,
                data_period_end=None,
                indicators_analyzed=None
            )
            db.add(analysis)
            db.commit()
            logger.info("Stored fundamentals analysis in database")
            return True
        except Exception as e:
            logger.error(f"Error storing analysis: {str(e)}")
            db.rollback()
            return False
        finally:
            db.close()

    @staticmethod
    def purge_non_frontend_indicators():
        """Delete all EconomicIndicator rows not used by the frontend."""
        db = SessionLocal()
        try:
            deleted = db.query(EconomicIndicator).filter(
                not_(EconomicIndicator.indicator_name.in_(EconomicFundamentalsCollector.ALLOWED_INDICATORS))
            ).delete(synchronize_session=False)
            db.commit()
            print(f"Purged {deleted} non-frontend indicators from the database.")
        except Exception as e:
            db.rollback()
            print(f"Error purging indicators: {e}")
        finally:
            db.close()


# Create global instance
economic_fundamentals_collector = EconomicFundamentalsCollector() 