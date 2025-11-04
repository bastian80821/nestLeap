"""
Batch Analysis Worker
Runs in separate process to avoid blocking FastAPI event loop
"""

import asyncio
import sys
import os
from datetime import datetime
from typing import List
from loguru import logger

# Configure logger for worker process
logger.remove()
logger.add(sys.stderr, level="INFO")


def run_batch_analysis_sync(job_id: str, tickers: List[str], max_concurrent: int = 10):
    """
    Synchronous wrapper for batch analysis - runs in separate process
    This function creates its own event loop and runs the async analysis
    """
    logger.info(f"[{job_id}] Worker process started (PID: {os.getpid()})")
    logger.info(f"[{job_id}] Processing {len(tickers)} stocks with max_concurrent={max_concurrent}")
    
    # Create new event loop for this process
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # Run the async batch processing
        result = loop.run_until_complete(
            _process_batch_async(job_id, tickers, max_concurrent)
        )
        logger.info(f"[{job_id}] Worker process completed: {result['completed']} succeeded, {result['failed']} failed")
        return result
    except Exception as e:
        logger.error(f"[{job_id}] Worker process failed: {e}")
        return {'completed': 0, 'failed': len(tickers), 'error': str(e)}
    finally:
        loop.close()


async def _process_batch_async(job_id: str, tickers: List[str], max_concurrent: int):
    """
    Async batch processing logic - runs in worker process's event loop
    """
    from ..database import SessionLocal
    from ..models import SP500Stock, BatchAnalysisJob
    from ..agents.stock_master_agent_v2 import StockMasterAgentV2
    
    completed = 0
    failed = 0
    
    # Process in batches of max_concurrent
    for i in range(0, len(tickers), max_concurrent):
        batch = tickers[i:i + max_concurrent]
        logger.info(f"[{job_id}] Processing batch {i//max_concurrent + 1}: {batch}")
        
        # Process batch concurrently
        tasks = [_analyze_single_stock(job_id, ticker) for ticker in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Count successes/failures
        for result in results:
            if isinstance(result, Exception):
                failed += 1
            elif result:
                completed += 1
            else:
                failed += 1
        
        # Update job progress in database
        try:
            db = SessionLocal()
            job = db.query(BatchAnalysisJob).filter(BatchAnalysisJob.job_id == job_id).first()
            if job:
                job.completed_stocks = completed
                job.failed_stocks = failed
                db.commit()
            db.close()
        except Exception as e:
            logger.error(f"[{job_id}] Error updating progress: {e}")
        
        # Small delay between batches
        if i + max_concurrent < len(tickers):
            await asyncio.sleep(0.5)
    
    # Mark job as completed
    try:
        db = SessionLocal()
        job = db.query(BatchAnalysisJob).filter(BatchAnalysisJob.job_id == job_id).first()
        if job:
            job.status = 'completed'
            job.completed_stocks = completed
            job.failed_stocks = failed
            job.completed_at = datetime.utcnow()
            db.commit()
        db.close()
    except Exception as e:
        logger.error(f"[{job_id}] Error marking job complete: {e}")
    
    return {'completed': completed, 'failed': failed}


async def _analyze_single_stock(job_id: str, ticker: str) -> bool:
    """Analyze a single stock - same logic as before"""
    from ..database import SessionLocal
    from ..models import SP500Stock
    from ..agents.stock_master_agent_v2 import StockMasterAgentV2
    
    try:
        # Check if stock was recently analyzed (within 6 hours)
        db = SessionLocal()
        try:
            sp_stock = db.query(SP500Stock).filter(SP500Stock.ticker == ticker).first()
            if sp_stock and sp_stock.last_analyzed_at:
                hours_since_analysis = (datetime.utcnow() - sp_stock.last_analyzed_at).total_seconds() / 3600
                if hours_since_analysis < 6:
                    logger.info(f"[{job_id}] ⏭️  {ticker} analyzed {hours_since_analysis:.1f}h ago, skipping")
                    return True  # Count as success, just skipped
        finally:
            db.close()
        
        logger.info(f"[{job_id}] Analyzing {ticker}...")
        
        # Update stock status in sp500_stocks
        db = SessionLocal()
        try:
            sp_stock = db.query(SP500Stock).filter(SP500Stock.ticker == ticker).first()
            if sp_stock:
                sp_stock.analysis_status = 'analyzing'
                db.commit()
        finally:
            db.close()
        
        # Run analysis
        agent = StockMasterAgentV2(ticker)
        await agent.run_cycle()
        
        # Update stock status to completed
        db = SessionLocal()
        try:
            sp_stock = db.query(SP500Stock).filter(SP500Stock.ticker == ticker).first()
            if sp_stock:
                sp_stock.analysis_status = 'completed'
                sp_stock.last_analyzed_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()
        
        # Validate analysis completeness
        from ..services.analysis_validator import AnalysisValidator
        validator = AnalysisValidator()
        validator.mark_analysis_validation_status(ticker)
        
        logger.info(f"[{job_id}] ✓ {ticker} completed")
        return True
        
    except Exception as e:
        logger.error(f"[{job_id}] ✗ {ticker} failed: {e}")
        
        # Update stock status to failed
        db = SessionLocal()
        try:
            sp_stock = db.query(SP500Stock).filter(SP500Stock.ticker == ticker).first()
            if sp_stock:
                sp_stock.analysis_status = 'failed'
                db.commit()
        finally:
            db.close()
        
        return False

