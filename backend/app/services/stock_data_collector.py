"""
Stock Data Collector

Collects and stores time series data for individual stocks.
Similar to economic_fundamentals_collector but for stocks.
"""

import asyncio
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional
from loguru import logger
from sqlalchemy import and_

from ..database import SessionLocal
from ..models import StockTimeSeries, TrackedStock


class StockDataCollector:
    """Collects and stores time series data for stocks"""
    
    def __init__(self):
        self.data_source = "yfinance"
        
    async def collect_stock_data(self, ticker: str, days_back: int = 90) -> Dict:
        """
        Collect and store time series data for a stock
        
        Args:
            ticker: Stock ticker symbol
            days_back: Number of days of historical data to collect
            
        Returns:
            Dict with collection status and statistics
        """
        try:
            logger.info(f"Collecting data for {ticker} (last {days_back} days)")
            
            # Fetch data from yfinance
            stock = yf.Ticker(ticker)
            
            # Get historical price data
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            
            hist = stock.history(start=start_date, end=end_date, actions=False)
            
            if hist.empty:
                logger.warning(f"No historical data found for {ticker}")
                return {
                    'success': False,
                    'ticker': ticker,
                    'error': 'No historical data available'
                }
            
            # Get current stock info for fundamental metrics
            info = stock.info
            
            # Calculate technical indicators
            hist_with_indicators = self._calculate_technical_indicators(hist)
            
            # Store in database
            db = SessionLocal()
            try:
                records_added = 0
                records_updated = 0
                
                for idx, row in hist_with_indicators.iterrows():
                    trade_date = idx.date()
                    
                    # Check if record exists
                    existing = db.query(StockTimeSeries).filter(
                        and_(
                            StockTimeSeries.ticker == ticker,
                            StockTimeSeries.date == trade_date
                        )
                    ).first()
                    
                    # Prepare data
                    data = {
                        'ticker': ticker,
                        'date': trade_date,
                        'open_price': float(row['Open']) if not pd.isna(row['Open']) else None,
                        'high_price': float(row['High']) if not pd.isna(row['High']) else None,
                        'low_price': float(row['Low']) if not pd.isna(row['Low']) else None,
                        'close_price': float(row['Close']) if not pd.isna(row['Close']) else None,
                        'adjusted_close': float(row.get('Adj Close', row['Close'])) if not pd.isna(row.get('Adj Close', row['Close'])) else None,
                        'volume': float(row['Volume']) if not pd.isna(row['Volume']) else None,
                        
                        # Technical indicators
                        'rsi_14': float(row['RSI']) if 'RSI' in row and not pd.isna(row['RSI']) else None,
                        'macd': float(row['MACD']) if 'MACD' in row and not pd.isna(row['MACD']) else None,
                        'macd_signal': float(row['MACD_Signal']) if 'MACD_Signal' in row and not pd.isna(row['MACD_Signal']) else None,
                        'sma_20': float(row['SMA_20']) if 'SMA_20' in row and not pd.isna(row['SMA_20']) else None,
                        'sma_50': float(row['SMA_50']) if 'SMA_50' in row and not pd.isna(row['SMA_50']) else None,
                        'sma_200': float(row['SMA_200']) if 'SMA_200' in row and not pd.isna(row['SMA_200']) else None,
                        'bollinger_upper': float(row['BB_Upper']) if 'BB_Upper' in row and not pd.isna(row['BB_Upper']) else None,
                        'bollinger_lower': float(row['BB_Lower']) if 'BB_Lower' in row and not pd.isna(row['BB_Lower']) else None,
                        'volume_sma_20': float(row['Volume_SMA']) if 'Volume_SMA' in row and not pd.isna(row['Volume_SMA']) else None,
                        'volume_ratio': float(row['Volume_Ratio']) if 'Volume_Ratio' in row and not pd.isna(row['Volume_Ratio']) else None,
                        
                        # Data quality
                        'data_quality': self._calculate_data_quality(row),
                        'data_source': self.data_source
                    }
                    
                    # Add fundamental metrics for most recent date
                    if trade_date == hist_with_indicators.index[-1].date():
                        data.update({
                            'pe_ratio': info.get('trailingPE'),
                            'pb_ratio': info.get('priceToBook'),
                            'ps_ratio': info.get('priceToSalesTrailing12Months'),
                            'market_cap': info.get('marketCap'),
                            'enterprise_value': info.get('enterpriseValue'),
                        })
                    
                    if existing:
                        # Update existing record
                        for key, value in data.items():
                            if key not in ['ticker', 'date']:  # Don't update primary keys
                                setattr(existing, key, value)
                        records_updated += 1
                    else:
                        # Create new record
                        new_record = StockTimeSeries(**data)
                        db.add(new_record)
                        records_added += 1
                
                db.commit()
                
                # Update tracked stock status
                await self._update_tracked_stock_status(ticker, db, success=True)
                
                logger.info(f"✅ {ticker}: Added {records_added} records, updated {records_updated} records")
                
                return {
                    'success': True,
                    'ticker': ticker,
                    'records_added': records_added,
                    'records_updated': records_updated,
                    'date_range': {
                        'start': hist.index[0].strftime('%Y-%m-%d'),
                        'end': hist.index[-1].strftime('%Y-%m-%d')
                    },
                    'data_quality': data.get('data_quality', 0.0)
                }
                
            except Exception as e:
                db.rollback()
                logger.error(f"Database error for {ticker}: {e}")
                await self._update_tracked_stock_status(ticker, db, success=False, error=str(e))
                raise
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error collecting data for {ticker}: {e}")
            return {
                'success': False,
                'ticker': ticker,
                'error': str(e)
            }
    
    def _calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate technical indicators from price data"""
        try:
            df = df.copy()
            
            # RSI (Relative Strength Index)
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['RSI'] = 100 - (100 / (1 + rs))
            
            # MACD (Moving Average Convergence Divergence)
            exp1 = df['Close'].ewm(span=12, adjust=False).mean()
            exp2 = df['Close'].ewm(span=26, adjust=False).mean()
            df['MACD'] = exp1 - exp2
            df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
            
            # Simple Moving Averages
            df['SMA_20'] = df['Close'].rolling(window=20).mean()
            df['SMA_50'] = df['Close'].rolling(window=50).mean()
            df['SMA_200'] = df['Close'].rolling(window=200).mean()
            
            # Bollinger Bands
            sma_20 = df['Close'].rolling(window=20).mean()
            std_20 = df['Close'].rolling(window=20).std()
            df['BB_Upper'] = sma_20 + (std_20 * 2)
            df['BB_Lower'] = sma_20 - (std_20 * 2)
            
            # Volume analysis
            df['Volume_SMA'] = df['Volume'].rolling(window=20).mean()
            df['Volume_Ratio'] = df['Volume'] / df['Volume_SMA']
            
            return df
            
        except Exception as e:
            logger.warning(f"Error calculating technical indicators: {e}")
            return df
    
    def _calculate_data_quality(self, row: pd.Series) -> float:
        """Calculate data quality score based on completeness"""
        required_fields = ['Open', 'High', 'Low', 'Close', 'Volume']
        present_fields = sum(1 for field in required_fields if not pd.isna(row.get(field)))
        return present_fields / len(required_fields)
    
    async def _update_tracked_stock_status(self, ticker: str, db, success: bool, error: str = None):
        """Update the tracked stock's collection status"""
        try:
            tracked = db.query(TrackedStock).filter(TrackedStock.ticker == ticker).first()
            
            if tracked:
                tracked.last_data_collection_date = datetime.utcnow()
                if success:
                    tracked.data_collection_status = 'active'
                    tracked.consecutive_errors = 0
                    tracked.last_error = None
                else:
                    tracked.consecutive_errors += 1
                    tracked.last_error = error
                    if tracked.consecutive_errors >= 3:
                        tracked.data_collection_status = 'error'
                
                db.commit()
        except Exception as e:
            logger.error(f"Error updating tracked stock status: {e}")
    
    async def collect_daily_data_for_tracked_stocks(self) -> Dict:
        """Collect data for all tracked stocks (called by daily scheduler)"""
        try:
            db = SessionLocal()
            try:
                tracked_stocks = db.query(TrackedStock).filter(
                    TrackedStock.is_active == True,
                    TrackedStock.data_collection_status.in_(['active', 'error'])
                ).order_by(TrackedStock.priority).all()
                
                logger.info(f"Collecting data for {len(tracked_stocks)} tracked stocks")
                
                results = []
                for stock in tracked_stocks:
                    # Add delay to avoid rate limiting
                    await asyncio.sleep(1)
                    
                    result = await self.collect_stock_data(stock.ticker, days_back=7)
                    results.append(result)
                
                success_count = sum(1 for r in results if r.get('success'))
                
                return {
                    'success': True,
                    'total_stocks': len(tracked_stocks),
                    'successful': success_count,
                    'failed': len(tracked_stocks) - success_count,
                    'results': results
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error in daily data collection: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def add_tracked_stock(self, ticker: str, priority: int = 5) -> Dict:
        """Add a stock to the tracking list"""
        try:
            db = SessionLocal()
            try:
                # Check if already tracked
                existing = db.query(TrackedStock).filter(TrackedStock.ticker == ticker).first()
                
                if existing:
                    logger.info(f"{ticker} is already tracked")
                    return {
                        'success': True,
                        'ticker': ticker,
                        'message': 'Already tracked',
                        'was_inactive': not existing.is_active
                    }
                
                # Get stock info
                stock = yf.Ticker(ticker)
                info = stock.info
                
                # Create tracked stock entry
                tracked = TrackedStock(
                    ticker=ticker,
                    company_name=info.get('longName', ticker),
                    sector=info.get('sector'),
                    exchange=info.get('exchange'),
                    priority=priority,
                    is_active=True,
                    data_collection_status='active',
                    added_by='api'
                )
                
                db.add(tracked)
                db.commit()
                
                # Collect initial data
                logger.info(f"Collecting initial data for newly tracked stock {ticker}")
                await self.collect_stock_data(ticker, days_back=365)  # Get 1 year of history
                
                return {
                    'success': True,
                    'ticker': ticker,
                    'message': 'Stock added to tracking list and initial data collected'
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error adding tracked stock {ticker}: {e}")
            return {
                'success': False,
                'ticker': ticker,
                'error': str(e)
            }
    
    async def get_latest_timeseries_data(self, ticker: str, days: int = 90) -> List[Dict]:
        """Retrieve time series data for a stock"""
        try:
            db = SessionLocal()
            try:
                cutoff_date = date.today() - timedelta(days=days)
                
                records = db.query(StockTimeSeries).filter(
                    StockTimeSeries.ticker == ticker,
                    StockTimeSeries.date >= cutoff_date
                ).order_by(StockTimeSeries.date.asc()).all()
                
                return [
                    {
                        'date': record.date.isoformat(),
                        'close': record.close_price,
                        'open': record.open_price,
                        'high': record.high_price,
                        'low': record.low_price,
                        'volume': record.volume,
                        'rsi': record.rsi_14,
                        'macd': record.macd,
                        'sma_50': record.sma_50,
                        'sma_200': record.sma_200
                    }
                    for record in records
                ]
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error retrieving time series for {ticker}: {e}")
            return []

