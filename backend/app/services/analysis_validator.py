"""
Analysis Validator

Validates that stock analyses have all required fields populated.
Helps identify incomplete or failed analyses during batch processing.
"""

from typing import Dict, List, Tuple
from loguru import logger
from ..database import SessionLocal
from ..models import StockAnalysis, SP500Stock


class AnalysisValidator:
    """Validates completeness of stock analyses"""
    
    # Required fields that must be present (ONLY fields displayed on frontend)
    REQUIRED_FIELDS = {
        'basic': [
            'ticker',
            'current_price',
            'analysis_date',
        ],
        'valuation': [
            'valuation_assessment',
            'fair_value_price',  # From fundamentals_outlook
            'buy_below',  # From fundamentals_outlook
            'sell_above',  # From fundamentals_outlook
        ],
        'master_analysis': [
            'company_description',  # From fundamentals_outlook
            'analysis',  # From fundamentals_outlook
            'forward_outlook',  # From fundamentals_outlook
            'market_comparison',  # From fundamentals_outlook
        ],
        'insights': [
            # key_insights removed - not displayed on frontend
            'risk_factors',
            'catalysts',
        ],
    }
    
    def validate_analysis(self, ticker: str) -> Tuple[bool, List[str]]:
        """
        Validate if a stock has a complete analysis
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        db = SessionLocal()
        try:
            # Get latest analysis
            analysis = db.query(StockAnalysis).filter(
                StockAnalysis.ticker == ticker
            ).order_by(StockAnalysis.analysis_date.desc()).first()
            
            if not analysis:
                return False, [f"No analysis found for {ticker}"]
            
            errors = []
            
            # Check basic fields
            for field in self.REQUIRED_FIELDS['basic']:
                if not getattr(analysis, field, None):
                    errors.append(f"Missing: {field}")
            
            # Check valuation assessment
            if not analysis.valuation_assessment:
                errors.append("Missing: valuation_assessment")
            
            # Check fundamentals_outlook JSONB fields
            fundamentals_outlook = analysis.fundamentals_outlook or {}
            for field in ['fair_value_price', 'buy_below', 'sell_above', 
                         'company_description', 'analysis', 'forward_outlook', 'market_comparison']:
                if not fundamentals_outlook.get(field):
                    errors.append(f"Missing in fundamentals_outlook: {field}")
            
            # Check risk_factors, catalysts (key_insights not displayed on frontend)
            for field in ['risk_factors', 'catalysts']:
                value = getattr(analysis, field, None)
                if not value or (isinstance(value, list) and len(value) == 0):
                    errors.append(f"Missing or empty: {field}")
            
            is_valid = len(errors) == 0
            
            if not is_valid:
                logger.warning(f"[{ticker}] Analysis validation failed: {len(errors)} errors")
                for error in errors:
                    logger.debug(f"[{ticker}]   - {error}")
            else:
                logger.debug(f"[{ticker}] ✅ Analysis validation passed")
            
            return is_valid, errors
            
        finally:
            db.close()
    
    def get_all_failed_analyses(self) -> List[Dict]:
        """
        Get all stocks with incomplete or failed analyses
        
        Returns:
            List of dicts with ticker, status, errors, last_analyzed_at
        """
        db = SessionLocal()
        try:
            failed_analyses = []
            
            # Get all stocks that were marked as completed
            stocks = db.query(SP500Stock).filter(
                SP500Stock.analysis_status == 'completed'
            ).all()
            
            for stock in stocks:
                is_valid, errors = self.validate_analysis(stock.ticker)
                
                if not is_valid:
                    failed_analyses.append({
                        'ticker': stock.ticker,
                        'company_name': stock.company_name,
                        'sector': stock.sector,
                        'last_analyzed_at': stock.last_analyzed_at.isoformat() if stock.last_analyzed_at else None,
                        'error_count': len(errors),
                        'errors': errors
                    })
            
            logger.info(f"Found {len(failed_analyses)} incomplete analyses out of {len(stocks)} completed")
            
            return failed_analyses
            
        finally:
            db.close()
    
    def mark_analysis_validation_status(self, ticker: str) -> None:
        """
        Validate analysis and update SP500Stock validation status
        
        This should be called after each analysis completes
        """
        is_valid, errors = self.validate_analysis(ticker)
        
        db = SessionLocal()
        try:
            stock = db.query(SP500Stock).filter(SP500Stock.ticker == ticker).first()
            if stock:
                if is_valid:
                    stock.analysis_status = 'completed'
                else:
                    stock.analysis_status = 'incomplete'
                    logger.warning(f"[{ticker}] Marked as incomplete: {', '.join(errors[:3])}")
                
                db.commit()
        finally:
            db.close()

