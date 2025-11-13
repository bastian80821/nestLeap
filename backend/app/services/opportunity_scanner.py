"""
Opportunity Scanner Service

Scans all S&P 500 stocks hourly to identify:
- Best Buy Opportunities (price well below buy_below threshold)
- Urgent Sell Signals (price well above sell_above threshold)
- Biggest Movers (significant price changes)
"""

import yfinance as yf
from datetime import datetime, timedelta
from typing import List, Dict
from loguru import logger

from ..database import SessionLocal
from ..models import StockOpportunity, StockAnalysis, SP500Stock


class OpportunityScanner:
    """Scans stocks for buy/sell opportunities and movements"""
    
    def __init__(self):
        # No more arbitrary thresholds - we'll identify top 10 by % discrepancy
        pass
    
    async def scan_all_opportunities(self) -> Dict:
        """
        Main hourly scan function
        
        Deletes old opportunities and scans all stocks with analyses.
        Processes stocks CONCURRENTLY to avoid blocking the API.
        
        Returns:
            Dict with scan statistics
        """
        import asyncio
        
        logger.info("🔍 Starting hourly opportunity scan...")
        
        db = SessionLocal()
        try:
            # Delete all old opportunities (we only keep the latest scan)
            deleted_count = db.query(StockOpportunity).delete()
            db.commit()
            logger.info(f"🗑️  Deleted {deleted_count} old opportunities")
            
            # Get all active S&P 500 stocks
            sp_stocks = db.query(SP500Stock).filter(SP500Stock.is_active == True).all()
            tickers = [stock.ticker for stock in sp_stocks]
            
            if not tickers:
                logger.warning("No stocks found to scan")
                return {'error': 'No stocks configured'}
            
            logger.info(f"📊 Scanning {len(tickers)} stocks (concurrent batches of 50)...")
            
            # Process stocks in concurrent batches of 50 to avoid blocking
            batch_size = 50
            total_scanned = 0
            total_errors = 0
            
            for i in range(0, len(tickers), batch_size):
                batch = tickers[i:i+batch_size]
                
                # Process this batch concurrently
                tasks = [self._scan_single_stock(ticker, db) for ticker in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Count successes and errors
                for result in results:
                    if isinstance(result, Exception):
                        total_errors += 1
                    elif result is not None:
                        total_scanned += 1
                
                # Small delay between batches to avoid overwhelming yfinance
                if i + batch_size < len(tickers):
                    await asyncio.sleep(0.5)
            
            logger.info(f"✅ Scan complete: {total_scanned} stocks scanned, {total_errors} errors")
            
            return {
                'scan_completed': True,
                'timestamp': datetime.utcnow().isoformat(),
                'total_scanned': total_scanned,
                'errors': total_errors
            }
            
        finally:
            db.close()
    
    async def _scan_single_stock(self, ticker: str, db) -> StockOpportunity:
        """Scan a single stock for opportunities (minimum $50B market cap)"""
        
        # Get stock info (sector, company name)
        sp_stock = db.query(SP500Stock).filter(SP500Stock.ticker == ticker).first()
        sector = sp_stock.sector if sp_stock else None
        company_name = sp_stock.company_name if sp_stock else None
        
        # Get latest analysis
        latest_analysis = db.query(StockAnalysis).filter(
            StockAnalysis.ticker == ticker
        ).order_by(StockAnalysis.analysis_date.desc()).first()
        
        if not latest_analysis:
            logger.debug(f"{ticker}: No analysis found, skipping")
            return None
        
        # Skip stocks with market cap < $50B
        if latest_analysis.market_cap and latest_analysis.market_cap < 50_000_000_000:
            logger.debug(f"{ticker}: Market cap ${latest_analysis.market_cap/1e9:.1f}B below $50B threshold, skipping")
            return None
        
        # Get averaged buy/sell thresholds
        last_3_analyses = db.query(StockAnalysis).filter(
            StockAnalysis.ticker == ticker
        ).order_by(StockAnalysis.analysis_date.desc()).limit(3).all()
        
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
        
        if not buy_belows or not sell_aboves:
            logger.debug(f"{ticker}: No buy/sell thresholds, skipping")
            return None
        
        fair_value = sum(fair_values) / len(fair_values) if fair_values else None
        buy_below = sum(buy_belows) / len(buy_belows)
        sell_above = sum(sell_aboves) / len(sell_aboves)
        
        # Get current price and movement data (NON-BLOCKING)
        try:
            import asyncio
            
            # Run yfinance call in thread pool to avoid blocking event loop
            def fetch_price_data():
                stock = yf.Ticker(ticker)
                return stock.history(period="7d")
            
            hist = await asyncio.to_thread(fetch_price_data)
            
            if hist.empty:
                logger.debug(f"{ticker}: No price data, skipping")
                return None
            
            current_price = hist['Close'].iloc[-1]
            
            # Calculate price changes
            price_change_1d = 0.0
            if len(hist) >= 2:
                price_change_1d = ((hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
            
            price_change_1w = 0.0
            if len(hist) >= 5:
                price_change_1w = ((hist['Close'].iloc[-1] - hist['Close'].iloc[0]) / hist['Close'].iloc[0]) * 100
            
            # Calculate volume vs average
            volume_vs_avg = 1.0
            if len(hist) >= 2:
                avg_volume = hist['Volume'].iloc[:-1].mean()
                if avg_volume > 0:
                    volume_vs_avg = hist['Volume'].iloc[-1] / avg_volume
            
        except Exception as e:
            logger.error(f"{ticker}: Error fetching price data: {e}")
            return None
        
        # Calculate opportunity metrics
        buy_opportunity_pct = None
        if buy_below and current_price < buy_below:
            buy_opportunity_pct = ((buy_below - current_price) / current_price) * 100
        
        sell_urgency_pct = None
        if sell_above and current_price > sell_above:
            sell_urgency_pct = ((current_price - sell_above) / sell_above) * 100
        
        distance_from_fair_pct = None
        if fair_value:
            distance_from_fair_pct = ((current_price - fair_value) / fair_value) * 100
        
        # Classify opportunity
        opportunity_type = self._classify_opportunity(
            current_price, buy_below, sell_above, fair_value
        )
        
        # Don't flag as "best" or "urgent" here - we'll determine top 10 at query time
        # Just store all the metrics
        opportunity = StockOpportunity(
            ticker=ticker,
            company_name=company_name,
            sector=sector,
            scan_date=datetime.utcnow(),
            current_price=float(current_price),
            fair_value_price=float(fair_value) if fair_value else None,
            buy_below=float(buy_below),
            sell_above=float(sell_above),
            buy_opportunity_pct=float(buy_opportunity_pct) if buy_opportunity_pct else None,
            sell_urgency_pct=float(sell_urgency_pct) if sell_urgency_pct else None,
            distance_from_fair_pct=float(distance_from_fair_pct) if distance_from_fair_pct else None,
            price_change_1d=float(price_change_1d),
            price_change_1w=float(price_change_1w),
            volume_vs_avg=float(volume_vs_avg),
            opportunity_type=opportunity_type,
            is_best_buy=False,  # Will be determined by top 10 query
            is_urgent_sell=False,  # Will be determined by top 10 query
            is_big_mover=False,  # Will be determined by top 10 query
            valuation_assessment=latest_analysis.valuation_assessment,
            overall_rating=latest_analysis.overall_rating
        )
        
        db.add(opportunity)
        db.commit()
        
        return opportunity
    
    def _classify_opportunity(self, current_price: float, buy_below: float, 
                             sell_above: float, fair_value: float = None) -> str:
        """Classify opportunity type"""
        
        if current_price <= buy_below * 0.90:  # 10%+ below buy threshold
            return 'strong_buy'
        elif current_price <= buy_below:
            return 'buy'
        elif current_price >= sell_above * 1.10:  # 10%+ above sell threshold
            return 'strong_sell'
        elif current_price >= sell_above:
            return 'sell'
        else:
            return 'hold'
    
    def _get_excluded_tickers(self, db) -> List[str]:
        """Get list of excluded tickers"""
        from ..models import ExcludedTicker
        return [e.ticker for e in db.query(ExcludedTicker).all()]
    
    def get_best_buys(self, limit: int = 10) -> List[Dict]:
        """
        Get top 10 best buy opportunities
        
        Returns stocks that are most undervalued (furthest BELOW fair value)
        Sorted by distance_from_fair_pct (most negative = best buy)
        """
        db = SessionLocal()
        try:
            # Get excluded tickers
            excluded = self._get_excluded_tickers(db)
            
            # Get all opportunities from latest scan where price < fair_value
            query = db.query(StockOpportunity).filter(
                StockOpportunity.distance_from_fair_pct < 0  # Price below fair value
            )
            
            # Filter out excluded tickers
            if excluded:
                query = query.filter(~StockOpportunity.ticker.in_(excluded))
            
            opportunities = query.order_by(
                StockOpportunity.distance_from_fair_pct.asc()  # Most negative first
            ).limit(limit).all()
            
            return [self._opportunity_to_dict(opp) for opp in opportunities]
            
        finally:
            db.close()
    
    def get_urgent_sells(self, limit: int = 10) -> List[Dict]:
        """
        Get top 10 urgent sell signals
        
        Returns stocks that are most overvalued (furthest ABOVE fair value)
        Sorted by distance_from_fair_pct (most positive = most urgent to sell)
        """
        db = SessionLocal()
        try:
            # Get excluded tickers
            excluded = self._get_excluded_tickers(db)
            
            # Get all opportunities from latest scan where price > fair_value
            query = db.query(StockOpportunity).filter(
                StockOpportunity.distance_from_fair_pct > 0  # Price above fair value
            )
            
            # Filter out excluded tickers
            if excluded:
                query = query.filter(~StockOpportunity.ticker.in_(excluded))
            
            opportunities = query.order_by(
                StockOpportunity.distance_from_fair_pct.desc()  # Most positive first
            ).limit(limit).all()
            
            return [self._opportunity_to_dict(opp) for opp in opportunities]
            
        finally:
            db.close()
    
    def get_big_movers(self, limit: int = 10) -> List[Dict]:
        """
        Get top 10 biggest movers
        
        Returns stocks with largest absolute price changes (1 day)
        Sorted by absolute value of price_change_1d
        """
        db = SessionLocal()
        try:
            from sqlalchemy import func
            
            # Get excluded tickers
            excluded = self._get_excluded_tickers(db)
            
            # Get all opportunities, ordered by absolute value of 1-day price change
            query = db.query(StockOpportunity)
            
            # Filter out excluded tickers
            if excluded:
                query = query.filter(~StockOpportunity.ticker.in_(excluded))
            
            opportunities = query.order_by(
                func.abs(StockOpportunity.price_change_1d).desc()
            ).limit(limit).all()
            
            return [self._opportunity_to_dict(opp) for opp in opportunities]
            
        finally:
            db.close()
    
    def get_best_buys_by_sector(self, sector: str, limit: int = 5) -> List[Dict]:
        """
        Get top best buy opportunities for a specific sector
        
        Returns stocks in the sector that are most undervalued
        Handles virtual "Megacap" sector for companies > $500B
        """
        from ..models import StockAnalysis
        db = SessionLocal()
        try:
            # Get excluded tickers
            excluded = self._get_excluded_tickers(db)
            
            # Handle Megacap as a virtual sector (filter by market cap)
            if sector == 'Megacap':
                query = db.query(StockOpportunity).join(
                    StockAnalysis,
                    StockOpportunity.ticker == StockAnalysis.ticker
                ).filter(
                    StockAnalysis.market_cap > 500_000_000_000,
                    StockOpportunity.distance_from_fair_pct < 0
                )
            else:
                query = db.query(StockOpportunity).filter(
                    StockOpportunity.sector == sector,
                    StockOpportunity.distance_from_fair_pct < 0
                )
            
            # Filter out excluded tickers
            if excluded:
                query = query.filter(~StockOpportunity.ticker.in_(excluded))
            
            opportunities = query.order_by(
                StockOpportunity.distance_from_fair_pct.asc()
            ).limit(limit).all()
            
            return [self._opportunity_to_dict(opp) for opp in opportunities]
            
        finally:
            db.close()
    
    def get_urgent_sells_by_sector(self, sector: str, limit: int = 5) -> List[Dict]:
        """
        Get top urgent sell signals for a specific sector
        
        Returns stocks in the sector that are most overvalued
        Handles virtual "Megacap" sector for companies > $500B
        """
        from ..models import StockAnalysis
        db = SessionLocal()
        try:
            # Get excluded tickers
            excluded = self._get_excluded_tickers(db)
            
            # Handle Megacap as a virtual sector (filter by market cap)
            if sector == 'Megacap':
                query = db.query(StockOpportunity).join(
                    StockAnalysis,
                    StockOpportunity.ticker == StockAnalysis.ticker
                ).filter(
                    StockAnalysis.market_cap > 500_000_000_000,
                    StockOpportunity.distance_from_fair_pct > 0
                )
            else:
                query = db.query(StockOpportunity).filter(
                    StockOpportunity.sector == sector,
                    StockOpportunity.distance_from_fair_pct > 0
                )
            
            # Filter out excluded tickers
            if excluded:
                query = query.filter(~StockOpportunity.ticker.in_(excluded))
            
            opportunities = query.order_by(
                StockOpportunity.distance_from_fair_pct.desc()
            ).limit(limit).all()
            
            return [self._opportunity_to_dict(opp) for opp in opportunities]
            
        finally:
            db.close()
    
    def _opportunity_to_dict(self, opp: StockOpportunity) -> Dict:
        """Convert opportunity to dict"""
        return {
            'ticker': opp.ticker,
            'company_name': opp.company_name,
            'sector': opp.sector,
            'current_price': opp.current_price,
            'fair_value_price': opp.fair_value_price,
            'buy_below': opp.buy_below,
            'sell_above': opp.sell_above,
            'buy_opportunity_pct': opp.buy_opportunity_pct,
            'sell_urgency_pct': opp.sell_urgency_pct,
            'distance_from_fair_pct': opp.distance_from_fair_pct,
            'price_change_1d': opp.price_change_1d,
            'price_change_1w': opp.price_change_1w,
            'volume_vs_avg': opp.volume_vs_avg,
            'opportunity_type': opp.opportunity_type,
            'valuation_assessment': opp.valuation_assessment,
            'overall_rating': opp.overall_rating,
            'scan_date': opp.scan_date.isoformat() if opp.scan_date else None
        }

