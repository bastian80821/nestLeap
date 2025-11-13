"""
Batch Analysis Service

Handles batch analysis of S&P 500 stocks using separate worker process.
This keeps the FastAPI event loop responsive while processing heavy workloads.
"""

import asyncio
import uuid
from datetime import datetime
from typing import List, Dict
from loguru import logger

from ..database import SessionLocal
from ..models import SP500Stock, BatchAnalysisJob, StockAnalysis
from .batch_worker import run_batch_analysis_sync


class BatchAnalysisService:
    """Service for batch analyzing stocks using separate worker process"""
    
    def __init__(self):
        self.max_concurrent = 10  # Process 10 stocks concurrently
        self.active_jobs = {}  # job_id -> job_status dict
    
    async def start_batch_analysis(self, tickers: List[str], initiated_by: str = "user") -> str:
        """
        Start batch analysis for multiple tickers
        
        Returns:
            job_id: Unique identifier for this batch job
        """
        # Check if there's already a running batch job
        db = SessionLocal()
        try:
            existing_job = db.query(BatchAnalysisJob).filter(
                BatchAnalysisJob.status == 'running'
            ).order_by(BatchAnalysisJob.started_at.desc()).first()
            
            if existing_job:
                logger.info(f"[{existing_job.job_id}] Batch already running, returning existing job_id")
                return existing_job.job_id
        finally:
            db.close()
        
        job_id = f"batch_{uuid.uuid4().hex[:12]}"
        
        # Create job record
        db = SessionLocal()
        try:
            job = BatchAnalysisJob(
                job_id=job_id,
                total_stocks=len(tickers),
                initiated_by=initiated_by,
                status='running'
            )
            db.add(job)
            db.commit()
            logger.info(f"[{job_id}] Starting batch analysis for {len(tickers)} stocks in separate worker process")
        finally:
            db.close()
        
        # Start batch processing as background task (non-blocking)
        asyncio.create_task(self._run_batch_async(job_id, tickers))
        logger.info(f"[{job_id}] Background batch processing started, API remains responsive")
        
        return job_id
    
    async def _run_batch_async(self, job_id: str, tickers: List[str]):
        """Run batch analysis as async background task"""
        try:
            logger.info(f"[{job_id}] Starting async batch processing for {len(tickers)} stocks")
            result = await run_batch_analysis_sync(job_id, tickers, self.max_concurrent)
            logger.info(f"[{job_id}] Batch completed: {result}")
        except Exception as e:
            logger.error(f"[{job_id}] Batch processing error: {e}")
    
    # Note: Batch processing logic moved to batch_worker.py (runs in separate process)
    # This keeps the FastAPI event loop responsive
    
    def _update_job_progress(self, job_id: str, completed: int, failed: int):
        """Update job progress in database (kept for compatibility)"""
        db = SessionLocal()
        try:
            job = db.query(BatchAnalysisJob).filter(BatchAnalysisJob.job_id == job_id).first()
            if job:
                job.completed_stocks = completed
                job.failed_stocks = failed
                db.commit()
        finally:
            db.close()
    
    def cancel_batch(self, job_id: str = None):
        """Cancel a running batch job"""
        db = SessionLocal()
        try:
            if job_id:
                job = db.query(BatchAnalysisJob).filter(
                    BatchAnalysisJob.job_id == job_id,
                    BatchAnalysisJob.status == 'running'
                ).first()
            else:
                # Cancel the most recent running job
                job = db.query(BatchAnalysisJob).filter(
                    BatchAnalysisJob.status == 'running'
                ).order_by(BatchAnalysisJob.started_at.desc()).first()
            
            if job:
                job.status = 'cancelled'
                job.completed_at = datetime.utcnow()
                db.commit()
                logger.info(f"[{job.job_id}] Batch cancelled")
                return {'status': 'success', 'message': f'Batch {job.job_id} cancelled'}
            else:
                return {'status': 'error', 'message': 'No running batch found'}
        finally:
            db.close()
    
    def _complete_job(self, job_id: str, completed: int, failed: int):
        """Mark job as completed"""
        db = SessionLocal()
        try:
            job = db.query(BatchAnalysisJob).filter(BatchAnalysisJob.job_id == job_id).first()
            if job:
                job.status = 'completed'
                job.completed_stocks = completed
                job.failed_stocks = failed
                job.completed_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()
    
    def _fail_job(self, job_id: str, error_message: str):
        """Mark job as failed"""
        db = SessionLocal()
        try:
            job = db.query(BatchAnalysisJob).filter(BatchAnalysisJob.job_id == job_id).first()
            if job:
                job.status = 'failed'
                job.error_message = error_message
                job.completed_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()
    
    def get_job_status(self, job_id: str) -> Dict:
        """Get current status of a batch job"""
        db = SessionLocal()
        try:
            job = db.query(BatchAnalysisJob).filter(BatchAnalysisJob.job_id == job_id).first()
            if not job:
                return {'error': 'Job not found'}
            
            return {
                'job_id': job.job_id,
                'status': job.status,
                'total_stocks': job.total_stocks,
                'completed_stocks': job.completed_stocks,
                'failed_stocks': job.failed_stocks,
                'progress_pct': round((job.completed_stocks / job.total_stocks) * 100, 1) if job.total_stocks > 0 else 0,
                'started_at': job.started_at.isoformat() if job.started_at else None,
                'completed_at': job.completed_at.isoformat() if job.completed_at else None,
                'error_message': job.error_message
            }
        finally:
            db.close()
    
    async def populate_stock_sectors(self):
        """Populate sector and company name for all stocks using yfinance"""
        import yfinance as yf
        
        db = SessionLocal()
        try:
            stocks = db.query(SP500Stock).filter(
                (SP500Stock.sector == None) | (SP500Stock.sector == '')
            ).all()
            
            logger.info(f"Populating sector data for {len(stocks)} stocks...")
            
            for stock in stocks:
                try:
                    ticker = yf.Ticker(stock.ticker)
                    info = ticker.info
                    
                    stock.company_name = info.get('longName') or info.get('shortName')
                    stock.sector = info.get('sector')
                    
                    if stock.sector:
                        logger.debug(f"[{stock.ticker}] {stock.company_name} - {stock.sector}")
                    
                    db.commit()
                except Exception as e:
                    logger.error(f"[{stock.ticker}] Error fetching sector: {e}")
                    continue
            
            logger.info("✅ Sector population complete")
        finally:
            db.close()
    
    async def load_sp500_tickers(self) -> List[str]:
        """
        Load or initialize large-cap US stock tickers (Russell 1000 style)
        
        Loads ~1000 of the largest US stocks. The $50B market cap filter will
        further narrow this down to the most relevant companies.
        """
        db = SessionLocal()
        try:
            # Russell 1000 style list: S&P 500 + mid/large-cap growth stocks
            all_target_tickers = [
                    'A', 'AAL', 'AAPL', 'ABBV', 'ABC', 'ABMD', 'ABT', 'ACN', 'ADBE', 'ADI',
                    'ADM', 'ADP', 'ADSK', 'AEE', 'AEP', 'AES', 'AFL', 'AIG', 'AIZ', 'AJG',
                    'AKAM', 'ALB', 'ALGN', 'ALK', 'ALL', 'ALLE', 'AMAT', 'AMCR', 'AMD', 'AME',
                    'AMGN', 'AMP', 'AMT', 'AMZN', 'ANET', 'ANSS', 'AON', 'AOS', 'APA', 'APD',
                    'APH', 'APTV', 'ARE', 'ATO', 'ATVI', 'AVB', 'AVGO', 'AVY', 'AWK', 'AXP',
                    'AZO', 'BA', 'BAC', 'BALL', 'BAX', 'BBWI', 'BBY', 'BDX', 'BEN', 'BF.B',
                    'BIIB', 'BIO', 'BK', 'BKNG', 'BKR', 'BLK', 'BMY', 'BR', 'BRK.B', 'BRO',
                    'BSX', 'BWA', 'BXP', 'C', 'CAG', 'CAH', 'CARR', 'CAT', 'CB', 'CBOE',
                    'CBRE', 'CCI', 'CCL', 'CDAY', 'CDNS', 'CDW', 'CE', 'CEG', 'CF', 'CFG',
                    'CHD', 'CHRW', 'CHTR', 'CI', 'CINF', 'CL', 'CLX', 'CMA', 'CMCSA', 'CME',
                    'CMG', 'CMI', 'CMS', 'CNC', 'CNP', 'COF', 'COO', 'COP', 'COST', 'CPB',
                    'CPRT', 'CRL', 'CRM', 'CSCO', 'CSGP', 'CSX', 'CTAS', 'CTLT', 'CTRA', 'CTSH',
                    'CTVA', 'CVS', 'CVX', 'CZR', 'D', 'DAL', 'DD', 'DE', 'DFS', 'DG',
                    'DGX', 'DHI', 'DHR', 'DIS', 'DLR', 'DLTR', 'DOV', 'DOW', 'DPZ', 'DRI',
                    'DTE', 'DUK', 'DVA', 'DVN', 'DXC', 'DXCM', 'EA', 'EBAY', 'ECL', 'ED',
                    'EFX', 'EIX', 'EL', 'ELV', 'EMN', 'EMR', 'ENPH', 'EOG', 'EPAM', 'EQIX',
                    'EQR', 'ES', 'ESS', 'ETN', 'ETR', 'ETSY', 'EVRG', 'EW', 'EXC', 'EXPD',
                    'EXPE', 'EXR', 'F', 'FANG', 'FAST', 'FBHS', 'FCX', 'FDS', 'FDX', 'FE',
                    'FFIV', 'FI', 'FICO', 'FIS', 'FITB', 'FLT', 'FMC', 'FOX', 'FOXA', 'FRC',
                    'FRT', 'FSLR', 'FTNT', 'FTV', 'GD', 'GE', 'GILD', 'GIS', 'GL', 'GLW',
                    'GM', 'GOOG', 'GOOGL', 'GPC', 'GPN', 'GRMN', 'GS', 'GWW', 'HAL', 'HAS',
                    'HBAN', 'HCA', 'HD', 'HES', 'HIG', 'HII', 'HLT', 'HOLX', 'HON', 'HPE',
                    'HPQ', 'HRL', 'HSIC', 'HST', 'HSY', 'HUBB', 'HUM', 'HWM', 'IBM', 'ICE',
                    'IDXX', 'IEX', 'IFF', 'ILMN', 'INCY', 'INTC', 'INTU', 'INVH', 'IP', 'IPG',
                    'IQV', 'IR', 'IRM', 'ISRG', 'IT', 'ITW', 'IVZ', 'J', 'JBHT', 'JCI',
                    'JKHY', 'JNJ', 'JNPR', 'JPM', 'K', 'KDP', 'KEY', 'KEYS', 'KHC', 'KIM',
                    'KLAC', 'KMB', 'KMI', 'KMX', 'KO', 'KR', 'KVUE', 'L', 'LDOS', 'LEN',
                    'LH', 'LHX', 'LIN', 'LKQ', 'LLY', 'LMT', 'LNC', 'LNT', 'LOW', 'LRCX',
                    'LULU', 'LUV', 'LVS', 'LW', 'LYB', 'LYV', 'MA', 'MAA', 'MAR', 'MAS',
                    'MCD', 'MCHP', 'MCK', 'MCO', 'MDLZ', 'MDT', 'MET', 'META', 'MGM', 'MHK',
                    'MKC', 'MKTX', 'MLM', 'MMC', 'MMM', 'MNST', 'MO', 'MOH', 'MOS', 'MPC',
                    'MPWR', 'MRK', 'MRNA', 'MRO', 'MS', 'MSCI', 'MSFT', 'MSI', 'MTB', 'MTCH',
                    'MTD', 'MU', 'NCLH', 'NDAQ', 'NDSN', 'NEE', 'NEM', 'NFLX', 'NI', 'NKE',
                    'NOC', 'NOW', 'NRG', 'NSC', 'NTAP', 'NTRS', 'NUE', 'NVDA', 'NVR', 'NWS',
                    'NWSA', 'NXPI', 'O', 'ODFL', 'OKE', 'OMC', 'ON', 'ORCL', 'ORLY', 'OTIS',
                    'OXY', 'PAYC', 'PAYX', 'PCAR', 'PCG', 'PEAK', 'PEG', 'PEP', 'PFE', 'PFG',
                    'PG', 'PGR', 'PH', 'PHM', 'PKG', 'PLD', 'PM', 'PNC', 'PNR', 'PNW',
                    'PODD', 'POOL', 'PPG', 'PPL', 'PRU', 'PSA', 'PSX', 'PTC', 'PWR', 'PXD',
                    'PYPL', 'QCOM', 'QRVO', 'RCL', 'RE', 'REG', 'REGN', 'RF', 'RHI', 'RJF',
                    'RL', 'RMD', 'ROK', 'ROL', 'ROP', 'ROST', 'RSG', 'RTX', 'RVTY', 'SBAC',
                    'SBNY', 'SBUX', 'SCHW', 'SHW', 'SIVB', 'SJM', 'SLB', 'SNA', 'SNPS', 'SO',
                    'SPG', 'SPGI', 'SRE', 'STE', 'STLD', 'STT', 'STX', 'STZ', 'SWK', 'SWKS',
                    'SYF', 'SYK', 'SYY', 'T', 'TAP', 'TDG', 'TDY', 'TECH', 'TEL', 'TER',
                    'TFC', 'TFX', 'TGT', 'TJX', 'TMO', 'TMUS', 'TPR', 'TRGP', 'TRMB', 'TROW',
                    'TRV', 'TSCO', 'TSLA', 'TSN', 'TT', 'TTWO', 'TXN', 'TXT', 'TYL', 'UAL',
                    'UDR', 'UHS', 'ULTA', 'UNH', 'UNP', 'UPS', 'URI', 'USB', 'V', 'VFC',
                    'VICI', 'VLO', 'VMC', 'VRSK', 'VRSN', 'VRTX', 'VTR', 'VTRS', 'VZ', 'WAB',
                    'WAT', 'WBA', 'WBD', 'WDC', 'WEC', 'WELL', 'WFC', 'WM', 'WMB', 'WMT',
                    'WRB', 'WRK', 'WST', 'WTW', 'WY', 'WYNN', 'XEL', 'XOM', 'XRAY', 'XYL',
                    'YUM', 'ZBH', 'ZBRA', 'ZION', 'ZTS',
                    # Additional mid/large-cap stocks (Russell 1000 additions)
                    'ABNB', 'ACGL', 'ACM', 'ADNT', 'AFG', 'AFRM', 'AGO', 'ALHC', 'ALNY', 'AMED',
                    'AMRC', 'ANDV', 'APPN', 'ARCC', 'ARMK', 'ASGN', 'ASPN', 'AYI', 'BC', 'BCPC',
                    'BERY', 'BG', 'BHF', 'BLD', 'BMRN', 'BNL', 'BOX', 'BRX', 'BURL', 'CABO',
                    'CADE', 'CACC', 'CAR', 'CBSH', 'CCS', 'CELG', 'CFR', 'CHE', 'CHGG', 'CHH',
                    'CHWY', 'CIT', 'CNHI', 'CNK', 'CNO', 'COIN', 'COLM', 'CONE', 'CPRI', 'CRS',
                    'CUBE', 'CUZ', 'CVNA', 'CVLT', 'CW', 'CWT', 'CWEN', 'DBX', 'DCI', 'DDOG',
                    'DDS', 'DECK', 'DEI', 'DELL', 'DFIN', 'DKS', 'DOC', 'DOCS', 'DOMO', 'DOCU',
                    'DT', 'DV', 'EAT', 'EEFT', 'EGP', 'EHC', 'ELS', 'ENR', 'ENTG', 'EPRT',
                    'EQC', 'ESNT', 'ESTC', 'ETH', 'EVH', 'EVR', 'EXP', 'FAF', 'FBIN', 'FCN',
                    'FHN', 'FIVE', 'FL', 'FLO', 'FLS', 'FNB', 'FNF', 'FR', 'FRSH', 'FSS',
                    'FUL', 'FWRD', 'GEN', 'GGG', 'GH', 'GHC', 'GLPI', 'GOLF', 'GPI', 'GPS',
                    'GRAM', 'GRFS', 'GRUB', 'GTLS', 'GXO', 'H', 'HALO', 'HBI', 'HCP', 'HE',
                    'HELE', 'HIBB', 'HLF', 'HLI', 'HNI', 'HOMB', 'HP', 'HRB', 'HRI', 'HTH',
                    'HTZ', 'HUBG', 'HUN', 'IAA', 'IAC', 'IBP', 'INFO', 'IPGP', 'IRT', 'ITT',
                    'JBGS', 'JBL', 'JEF', 'JHG', 'JLL', 'JMIA', 'JOUT', 'KAR', 'KEX', 'KFY',
                    'KN', 'KNX', 'KRC', 'KRG', 'KSS', 'KTB', 'LAMR', 'LAZR', 'LC', 'LEA',
                    'LEG', 'LESL', 'LFUS', 'LITE', 'LIVN', 'LPX', 'LPLA', 'LRN', 'LSI', 'LXP',
                    'LYFT', 'M', 'MAC', 'MAN', 'MANH', 'MASI', 'MCY', 'MD', 'MDC', 'MEDP',
                    'MELI', 'MFA', 'MIDD', 'MIK', 'MLI', 'MOD', 'MOG.A', 'MRC', 'MRVL', 'MSG',
                    'MSGE', 'MTG', 'MTN', 'MTZ', 'MUR', 'MXIM', 'NBR', 'NCR', 'NFE', 'NLS',
                    'NLY', 'NN', 'NNN', 'NOV', 'NPO', 'NRZ', 'NSA', 'NTB', 'NVT', 'NWL',
                    'NWN', 'OC', 'ODP', 'OFC', 'OGE', 'OGS', 'OHI', 'OII', 'OLN', 'ORA',
                    'OSK', 'OUT', 'OVV', 'OZK', 'PAG', 'PARA', 'PATK', 'PBCT', 'PBI', 'PBF',
                    'PCTY', 'PDCE', 'PEB', 'PENN', 'PII', 'PINC', 'PK', 'PLNT', 'PLTR', 'PNFP',
                    'PNM', 'POR', 'POST', 'PRGO', 'PRSP', 'PSB', 'PSTG', 'PVH', 'PZN', 'QL',
                    'R', 'RAMP', 'RBA', 'RC', 'RDN', 'REXR', 'RGA', 'RH', 'RILY', 'RIOT',
                    'RKT', 'RLI', 'RLJ', 'ROKU', 'RPRX', 'RRC', 'RRGB', 'RS', 'RST', 'RUTH',
                    'RXN', 'SAGE', 'SAIC', 'SANM', 'SAM', 'SBH', 'SCCO', 'SEIC', 'SF', 'SFM',
                    'SGEN', 'SGH', 'SIRI', 'SIX', 'SKT', 'SKX', 'SKY', 'SLG', 'SLM', 'SM',
                    'SMCI', 'SMP', 'SNAP', 'SNV', 'SNX', 'SON', 'SPCE', 'SPR', 'SPOT', 'SQ',
                    'SRC', 'SRCL', 'SSNC', 'SSL', 'ST', 'STAG', 'STER', 'STOR', 'STWD', 'SUI',
                    'SUM', 'SUN', 'SUPN', 'TEAM', 'TECK', 'TELZ', 'TEX', 'TFSL', 'THG', 'THO',
                    'TNET', 'TOL', 'TPH', 'TPL', 'TPX', 'TREX', 'TRI', 'TRIP', 'TRN', 'TRUP',
                    'TTC', 'TTD', 'TW', 'TWO', 'TWTR', 'TX', 'TXRH', 'TXMD', 'UBER', 'UE',
                    'UFPI', 'UGI', 'UPST', 'USFD', 'USLM', 'VAC', 'VC', 'VLY', 'VNO', 'VNT',
                    'VOYA', 'VRE', 'VST', 'WDAY', 'WEN', 'WEX', 'WHR', 'WING', 'WK', 'WLK',
                    'WNC', 'WPX', 'WRE', 'WRI', 'WSC', 'WSM', 'WSO', 'WWE', 'WWW', 'X',
                    'XPO', 'YETI', 'Z', 'ZEN', 'ZG', 'ZI', 'ZNGA', 'ZM', 'ZS', 'ZUO'
            ]
            
            # Get existing tickers from database
            existing_stocks = db.query(SP500Stock).all()
            existing_tickers = {stock.ticker for stock in existing_stocks}
            
            # Find new tickers to add
            new_tickers = [t for t in all_target_tickers if t not in existing_tickers]
            
            if new_tickers:
                logger.info(f"Adding {len(new_tickers)} new tickers to database: {new_tickers[:20]}{'...' if len(new_tickers) > 20 else ''}")
                
                for ticker in new_tickers:
                    sp_stock = SP500Stock(ticker=ticker, analysis_status='pending')
                    db.add(sp_stock)
                
                db.commit()
                logger.info(f"✅ Added {len(new_tickers)} new tickers (Total universe: {len(existing_tickers) + len(new_tickers)})")
            else:
                logger.info(f"Stock universe already complete with {len(existing_tickers)} tickers")
            
            # Return all active tickers
            stocks = db.query(SP500Stock).filter(SP500Stock.is_active == True).all()
            all_tickers = [stock.ticker for stock in stocks]
            
            # Filter out excluded tickers
            from ..models import ExcludedTicker
            excluded_tickers = [e.ticker for e in db.query(ExcludedTicker).all()]
            
            filtered_tickers = [t for t in all_tickers if t not in excluded_tickers]
            
            if excluded_tickers:
                logger.info(f"Filtered out {len(excluded_tickers)} excluded tickers: {excluded_tickers}")
            
            logger.info(f"Returning {len(filtered_tickers)} tickers for batch analysis")
            return filtered_tickers
            
        finally:
            db.close()

