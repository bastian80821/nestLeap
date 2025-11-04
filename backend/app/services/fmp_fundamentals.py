"""
Financial Modeling Prep (FMP) Fundamentals Service

Fetches reliable fundamental data from FMP API including:
- Quarterly financials (revenue, earnings)
- Key metrics (growth rates, margins, ratios)
- Company profile information
"""

import aiohttp
from typing import Dict, Optional
from loguru import logger
from ..config import settings


class FMPFundamentalsService:
    """Service for fetching fundamental data from Financial Modeling Prep API"""
    
    BASE_URL = "https://financialmodelingprep.com/api/v3"
    
    def __init__(self):
        self.api_key = settings.fmp_api_key
        
    async def get_key_metrics(self, ticker: str, period: str = "quarter", limit: int = 5) -> Optional[Dict]:
        """
        Get key metrics including growth rates, margins, ratios
        
        Args:
            ticker: Stock ticker symbol
            period: 'quarter' or 'annual'
            limit: Number of periods to fetch
            
        Returns:
            Dict with latest metrics or None if error
        """
        try:
            url = f"{self.BASE_URL}/key-metrics/{ticker}"
            params = {
                "period": period,
                "limit": limit,
                "apikey": self.api_key
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and len(data) > 0:
                            logger.info(f"[FMP] Fetched key metrics for {ticker}")
                            return data[0]  # Return most recent period
                    else:
                        logger.warning(f"[FMP] Key metrics request failed: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"[FMP] Error fetching key metrics for {ticker}: {e}")
            return None
    
    async def get_income_statement(self, ticker: str, period: str = "quarter", limit: int = 8) -> Optional[list]:
        """
        Get income statement data including revenue and net income
        
        Args:
            ticker: Stock ticker symbol
            period: 'quarter' or 'annual'
            limit: Number of periods to fetch (need at least 5 for YoY comparison)
            
        Returns:
            List of income statements (most recent first) or None if error
        """
        try:
            url = f"{self.BASE_URL}/income-statement/{ticker}"
            params = {
                "period": period,
                "limit": limit,
                "apikey": self.api_key
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and len(data) > 0:
                            logger.info(f"[FMP] Fetched {len(data)} income statements for {ticker}")
                            return data
                    else:
                        logger.warning(f"[FMP] Income statement request failed: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"[FMP] Error fetching income statement for {ticker}: {e}")
            return None
    
    async def calculate_growth_metrics(self, ticker: str) -> Dict:
        """
        Calculate YoY revenue and earnings growth from quarterly data
        
        Returns:
            Dict with revenue_growth, earnings_growth, latest_revenue, latest_eps
        """
        try:
            # Get quarterly income statements
            income_statements = await self.get_income_statement(ticker, period="quarter", limit=8)
            
            if not income_statements or len(income_statements) < 5:
                logger.warning(f"[FMP] Insufficient data to calculate growth for {ticker}")
                return {
                    'revenue_growth': None,
                    'earnings_growth': None,
                    'latest_revenue': None,
                    'latest_eps': None
                }
            
            # Most recent quarter
            latest = income_statements[0]
            # Same quarter last year (4 quarters ago)
            yoy = income_statements[4]
            
            # Calculate revenue growth (YoY)
            revenue_growth = None
            latest_revenue = latest.get('revenue')
            yoy_revenue = yoy.get('revenue')
            
            if latest_revenue and yoy_revenue and yoy_revenue != 0:
                revenue_growth = ((latest_revenue - yoy_revenue) / abs(yoy_revenue)) * 100
            
            # Calculate earnings growth (YoY)
            earnings_growth = None
            latest_earnings = latest.get('netIncome')
            yoy_earnings = yoy.get('netIncome')
            
            if latest_earnings and yoy_earnings and yoy_earnings != 0:
                earnings_growth = ((latest_earnings - yoy_earnings) / abs(yoy_earnings)) * 100
            
            # Get EPS
            latest_eps = latest.get('eps')
            
            logger.info(f"[FMP] {ticker} - Revenue Growth: {revenue_growth:.1f}%, Earnings Growth: {earnings_growth:.1f}%, EPS: ${latest_eps}")
            
            return {
                'revenue_growth': round(revenue_growth, 2) if revenue_growth is not None else None,
                'earnings_growth': round(earnings_growth, 2) if earnings_growth is not None else None,
                'latest_revenue': latest_revenue,
                'latest_eps': latest_eps,
                'latest_quarter_date': latest.get('date'),
                'calendar_year': latest.get('calendarYear'),
                'period': latest.get('period')
            }
            
        except Exception as e:
            logger.error(f"[FMP] Error calculating growth metrics for {ticker}: {e}")
            return {
                'revenue_growth': None,
                'earnings_growth': None,
                'latest_revenue': None,
                'latest_eps': None
            }
    
    async def get_company_profile(self, ticker: str) -> Optional[Dict]:
        """Get company profile information"""
        try:
            url = f"{self.BASE_URL}/profile/{ticker}"
            params = {"apikey": self.api_key}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and len(data) > 0:
                            return data[0]
                    return None
                    
        except Exception as e:
            logger.error(f"[FMP] Error fetching profile for {ticker}: {e}")
            return None

