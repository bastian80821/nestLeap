"""
Company News Collector - Deep article reading and persistent company summary
Similar to market news system but for individual stocks
"""
import asyncio
import aiohttp
from typing import List, Dict, Optional
from datetime import datetime, timedelta, timezone
import yfinance as yf
from newspaper import Article
from bs4 import BeautifulSoup
import google.generativeai as genai
from ..config import settings
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import desc
from ..database import SessionLocal
from ..models import StockArticle, CompanyNewsSummary, GeminiApiCallLog
import json
from urllib.parse import urlparse


class CompanyNewsCollector:
    """
    Comprehensive company news system that:
    1. Fetches article URLs from yfinance and other sources
    2. Reads full article content (like market news does)
    3. Maintains persistent company summary
    4. Only updates summary when significant new information emerges
    """
    
    def __init__(self, ticker: str):
        self.ticker = ticker.upper()
        genai.configure(api_key=settings.google_api_key)
        self.llm_model = genai.GenerativeModel(settings.llm_model)
    
    async def collect_and_analyze(self, days_back: int = 7) -> Dict:
        """
        Main entry point: collect articles, analyze, update summary if needed
        
        Returns:
            Dict with company_summary, latest_earnings, key_risks, opportunities, etc.
        """
        try:
            db = SessionLocal()
            
            # Step 1: Get existing company summary
            existing_summary = db.query(CompanyNewsSummary).filter(
                CompanyNewsSummary.ticker == self.ticker
            ).first()
            
            # Step 2: Fetch recent article URLs
            article_urls = await self._fetch_article_urls(days_back)
            logger.info(f"[{self.ticker}] Found {len(article_urls)} article URLs")
            
            # Step 3: Process each article
            new_articles_count = 0
            for article_data in article_urls[:5]:  # Limit to most recent 5 (optimized for speed)
                # Check if article already exists
                existing_article = db.query(StockArticle).filter(
                    StockArticle.url == article_data['url']
                ).first()
                
                if existing_article:
                    logger.debug(f"[{self.ticker}] Article already processed: {article_data['title'][:50]}")
                    continue
                
                # Try to read full article content, but fall back to yfinance summary if extraction fails
                full_text = await self._extract_article_content(article_data['url'])
                if not full_text or len(full_text) < 100:
                    # Use yfinance summary as fallback
                    full_text = article_data.get('summary', '')
                    if not full_text or len(full_text) < 50:
                        logger.debug(f"[{self.ticker}] Article has insufficient content: {article_data['url']}")
                        continue
                    logger.debug(f"[{self.ticker}] Using yfinance summary for: {article_data['title'][:50]}")
                
                # Analyze article with LLM
                article_analysis = await self._analyze_article_with_llm(
                    title=article_data['title'],
                    full_text=full_text,
                    existing_summary=existing_summary
                )
                
                if not article_analysis:
                    continue
                
                # Store article in database
                db_article = StockArticle(
                    ticker=self.ticker,
                    url=article_data['url'],
                    title=article_data['title'],
                    source=article_data.get('source', 'Unknown'),
                    published_at=article_data['published_at'],
                    full_text=full_text[:5000],  # Store first 5000 chars
                    summary=article_analysis['summary'],
                    is_significant=article_analysis['is_significant'],
                    significance_score=article_analysis['significance_score'],
                    article_type=article_analysis['article_type'],
                    key_points=article_analysis['key_points'],
                    sentiment_score=article_analysis['sentiment_score'],
                    processed_at=datetime.utcnow()
                )
                db.add(db_article)
                db.commit()
                new_articles_count += 1
                
                logger.info(f"[{self.ticker}] Processed article: {article_data['title'][:50]} (significant: {article_analysis['is_significant']})")
            
            # Step 4: Decide if summary needs updating
            should_update = await self._should_update_summary(
                existing_summary=existing_summary,
                new_articles_count=new_articles_count,
                db=db
            )
            
            if should_update:
                logger.info(f"[{self.ticker}] Significant new information found - updating company summary")
                updated_summary = await self._generate_company_summary(db)
                
                if existing_summary:
                    # Update existing
                    for key, value in updated_summary.items():
                        setattr(existing_summary, key, value)
                    existing_summary.last_significant_update = datetime.utcnow()
                    existing_summary.articles_since_update = 0
                else:
                    # Create new
                    updated_summary['ticker'] = self.ticker
                    updated_summary['created_at'] = datetime.utcnow()
                    updated_summary['last_significant_update'] = datetime.utcnow()
                    updated_summary['articles_since_update'] = 0
                    db_summary = CompanyNewsSummary(**updated_summary)
                    db.add(db_summary)
                
                db.commit()
                db.refresh(existing_summary or db_summary)
            
            else:
                # Just update metadata
                if existing_summary:
                    existing_summary.last_article_processed = datetime.utcnow()
                    existing_summary.articles_since_update += new_articles_count
                    existing_summary.total_articles_processed += new_articles_count
                    db.commit()
                    logger.info(f"[{self.ticker}] No significant updates - summary unchanged")
            
            # Step 5: Return current summary
            final_summary = db.query(CompanyNewsSummary).filter(
                CompanyNewsSummary.ticker == self.ticker
            ).first()
            
            if not final_summary:
                logger.warning(f"[{self.ticker}] No summary available yet")
                return self._get_empty_summary()
            
            db.close()
            return self._format_summary_for_output(final_summary)
            
        except Exception as e:
            logger.error(f"[{self.ticker}] Error in collect_and_analyze: {str(e)}")
            if 'db' in locals():
                db.close()
            return self._get_empty_summary()
    
    async def _fetch_article_urls(self, days_back: int) -> List[Dict]:
        """Fetch article URLs from yfinance and other sources"""
        articles = []
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
        
        try:
            # Primary: yfinance news (new API structure as of 2024)
            ticker_obj = yf.Ticker(self.ticker)
            yf_news = ticker_obj.news
            
            for item in yf_news:
                # New yfinance structure: data is nested under 'content'
                content = item.get('content', {})
                
                # Parse date
                pub_date_str = content.get('pubDate')
                if pub_date_str:
                    try:
                        from dateutil import parser
                        pub_date = parser.parse(pub_date_str)
                        if pub_date.tzinfo is None:
                            pub_date = pub_date.replace(tzinfo=timezone.utc)
                    except:
                        pub_date = datetime.now(timezone.utc)
                else:
                    pub_date = datetime.now(timezone.utc)
                
                if pub_date < cutoff_date:
                    continue
                
                # Extract URL
                url = ''
                canonical_url = content.get('canonicalUrl', {})
                if isinstance(canonical_url, dict):
                    url = canonical_url.get('url', '')
                elif isinstance(canonical_url, str):
                    url = canonical_url
                
                if not url:
                    continue
                
                articles.append({
                    'url': url,
                    'title': content.get('title', ''),
                    'source': content.get('provider', {}).get('displayName', 'Yahoo Finance'),
                    'published_at': pub_date,
                    'summary': content.get('summary', '')  # Use yfinance's provided summary
                })
            
            logger.info(f"[{self.ticker}] Fetched {len(articles)} articles from yfinance")
            
        except Exception as e:
            logger.error(f"[{self.ticker}] Error fetching yfinance news: {str(e)}")
        
        # Sort by date (newest first)
        articles.sort(key=lambda x: x['published_at'], reverse=True)
        return articles
    
    async def _extract_article_content(self, url: str) -> str:
        """Extract full article text using newspaper3k"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as response:
                    if response.status != 200:
                        return ""
                    
                    html = await response.text()
                    
                    # Try newspaper3k
                    article = Article('')
                    article.set_html(html)
                    article.parse()
                    
                    if article.text and len(article.text.strip()) > 100:
                        logger.debug(f"[{self.ticker}] Extracted {len(article.text)} chars from {url[:50]}")
                        return article.text.strip()
                    
        except Exception as e:
            logger.debug(f"[{self.ticker}] Failed to extract content from {url}: {str(e)}")
        
        return ""
    
    async def _analyze_article_with_llm(self, title: str, full_text: str, existing_summary: Optional[CompanyNewsSummary]) -> Optional[Dict]:
        """
        Analyze article with LLM to determine:
        - Is it significant? (earnings, major product, management change, etc.)
        - What type of news?
        - Key points
        - Sentiment
        """
        try:
            # Prepare context about existing summary
            existing_context = ""
            if existing_summary and existing_summary.company_summary:
                existing_context = f"""
EXISTING COMPANY SUMMARY:
{existing_summary.company_summary[:1000]}

KNOWN RISKS: {json.dumps(existing_summary.key_risks or [])}
KNOWN OPPORTUNITIES: {json.dumps(existing_summary.key_opportunities or [])}
"""
            
            prompt = f"""Analyze this news article for {self.ticker}:

TITLE: {title}

ARTICLE TEXT (first 2000 chars):
{full_text[:2000]}

{existing_context}

Provide analysis in JSON format:
{{
    "summary": "2-3 sentence summary of the article",
    "is_significant": true/false (Is this earnings, major product launch, management change, regulatory action, or other major news?),
    "significance_score": 0.0-1.0 (how important is this?),
    "article_type": "earnings|product|management|regulatory|acquisition|general",
    "key_points": ["point1", "point2", "point3"],
    "sentiment_score": -1.0 to 1.0 (negative to positive),
    "is_new_information": true/false (Is this materially new vs existing summary?)
}}

Respond ONLY with valid JSON."""
            
            response = self.llm_model.generate_content(prompt)
            result_text = response.text.strip()
            
            # Clean JSON
            if result_text.startswith('```json'):
                result_text = result_text[7:]
            if result_text.endswith('```'):
                result_text = result_text[:-3]
            result_text = result_text.strip()
            
            analysis = json.loads(result_text)
            
            # Log Gemini call
            await self._log_gemini_call(prompt, f"article_analysis_{self.ticker}")
            
            return analysis
            
        except Exception as e:
            logger.error(f"[{self.ticker}] Error analyzing article with LLM: {str(e)}")
            return None
    
    async def _should_update_summary(self, existing_summary: Optional[CompanyNewsSummary], new_articles_count: int, db: Session) -> bool:
        """Decide if company summary needs updating"""
        
        # Always update if no existing summary
        if not existing_summary:
            return True
        
        # Check for significant articles in recent batch
        recent_significant = db.query(StockArticle).filter(
            StockArticle.ticker == self.ticker,
            StockArticle.is_significant == True,
            StockArticle.was_used_in_summary_update == False
        ).count()
        
        if recent_significant > 0:
            return True
        
        # Update if too many articles accumulated
        if existing_summary.articles_since_update >= 20:
            return True
        
        # Update if summary is too old (30 days)
        if existing_summary.last_significant_update:
            days_since_update = (datetime.utcnow() - existing_summary.last_significant_update).days
            if days_since_update > 30:
                return True
        
        return False
    
    async def _generate_company_summary(self, db: Session) -> Dict:
        """Generate comprehensive company summary using LLM"""
        try:
            # Get all significant articles
            significant_articles = db.query(StockArticle).filter(
                StockArticle.ticker == self.ticker,
                StockArticle.is_significant == True
            ).order_by(desc(StockArticle.published_at)).limit(20).all()
            
            # Get recent articles (last 30 days)
            recent_cutoff = datetime.utcnow() - timedelta(days=30)
            recent_articles = db.query(StockArticle).filter(
                StockArticle.ticker == self.ticker,
                StockArticle.published_at >= recent_cutoff
            ).order_by(desc(StockArticle.published_at)).limit(30).all()
            
            # Get company info from yfinance
            try:
                ticker_obj = yf.Ticker(self.ticker)
                info = ticker_obj.info
                company_name = info.get('longName', self.ticker)
                sector = info.get('sector', 'Unknown')
            except:
                company_name = self.ticker
                sector = 'Unknown'
            
            # Build context for LLM
            articles_context = "\n\n".join([
                f"[{art.published_at.strftime('%Y-%m-%d')}] {art.title}\n{art.summary}\nKey Points: {json.dumps(art.key_points)}\nType: {art.article_type}"
                for art in recent_articles[:15]
            ])
            
            earnings_context = "\n\n".join([
                f"[{art.published_at.strftime('%Y-%m-%d')}] {art.title}\n{art.summary}"
                for art in significant_articles if art.article_type == 'earnings'
            ][:3])  # Last 3 earnings
            
            prompt = f"""Generate a comprehensive company profile for {self.ticker} ({company_name}) based on recent news analysis.

RECENT ARTICLES (last 30 days):
{articles_context}

RECENT EARNINGS REPORTS:
{earnings_context}

Generate a structured company summary in JSON format:
{{
    "company_name": "{company_name}",
    "sector": "{sector}",
    "company_summary": "Comprehensive 3-4 sentence overview of what the company does and current state",
    "recent_developments_summary": "What's happened in the last 30 days? Summarize key events",
    "outlook": "Forward-looking assessment based on news and trends",
    
    "latest_earnings_date": "YYYY-MM-DD or null",
    "latest_earnings_result": "Beat|Miss|In-line or null",
    "latest_earnings_summary": "What happened in latest earnings? Be specific with numbers",
    "eps_actual": float or null,
    "eps_expected": float or null,
    "revenue_actual": float or null,
    "revenue_expected": float or null,
    "guidance": "What guidance was provided?" or null,
    
    "key_risks": ["risk1", "risk2", "risk3"] (top 3-5 risks mentioned in news),
    "key_opportunities": ["opp1", "opp2", "opp3"] (top 3-5 opportunities),
    "recent_product_developments": [{{"date": "YYYY-MM-DD", "product": "name", "description": "what happened"}}],
    "management_changes": [{{"date": "YYYY-MM-DD", "change": "description"}}] or [],
    "regulatory_issues": [{{"date": "YYYY-MM-DD", "issue": "description", "status": "ongoing|resolved"}}] or [],
    "competitive_position": "Brief assessment of competitive standing",
    
    "total_articles_processed": {len(recent_articles)}
}}

Be specific and quantitative. Extract actual numbers from earnings. If information is not available, use null.
Respond ONLY with valid JSON."""
            
            response = self.llm_model.generate_content(prompt)
            result_text = response.text.strip()
            
            # Clean JSON
            if result_text.startswith('```json'):
                result_text = result_text[7:]
            if result_text.endswith('```'):
                result_text = result_text[:-3]
            result_text = result_text.strip()
            
            summary_data = json.loads(result_text)
            
            # Mark articles as used
            for article in recent_articles:
                article.was_used_in_summary_update = True
            db.commit()
            
            # Log Gemini call
            await self._log_gemini_call(prompt, f"company_summary_generation_{self.ticker}")
            
            return summary_data
            
        except Exception as e:
            logger.error(f"[{self.ticker}] Error generating company summary: {str(e)}")
            return {}
    
    def _format_summary_for_output(self, summary: CompanyNewsSummary) -> Dict:
        """Format DB summary for API output"""
        return {
            'ticker': summary.ticker,
            'company_name': summary.company_name,
            'sector': summary.sector,
            'company_summary': summary.company_summary,
            'recent_developments': summary.recent_developments_summary,
            'outlook': summary.outlook,
            'latest_earnings': {
                'date': summary.latest_earnings_date.isoformat() if summary.latest_earnings_date else None,
                'result': summary.latest_earnings_result,
                'summary': summary.latest_earnings_summary,
                'eps_actual': summary.eps_actual,
                'eps_expected': summary.eps_expected,
                'revenue_actual': summary.revenue_actual,
                'revenue_expected': summary.revenue_expected,
                'guidance': summary.guidance
            },
            'key_risks': summary.key_risks or [],
            'key_opportunities': summary.key_opportunities or [],
            'recent_products': summary.recent_product_developments or [],
            'management_changes': summary.management_changes or [],
            'regulatory_issues': summary.regulatory_issues or [],
            'competitive_position': summary.competitive_position,
            'last_updated': summary.last_significant_update.isoformat() if summary.last_significant_update else None,
            'articles_processed': summary.total_articles_processed
        }
    
    def _get_empty_summary(self) -> Dict:
        """Return empty structure when no data available"""
        return {
            'ticker': self.ticker,
            'company_name': self.ticker,
            'sector': 'Unknown',
            'company_summary': 'No news analysis available yet',
            'recent_developments': None,
            'outlook': None,
            'latest_earnings': {},
            'key_risks': [],
            'key_opportunities': [],
            'recent_products': [],
            'management_changes': [],
            'regulatory_issues': [],
            'competitive_position': None,
            'last_updated': None,
            'articles_processed': 0
        }
    
    async def _log_gemini_call(self, prompt: str, analysis_type: str):
        """Log Gemini API call to database"""
        try:
            from datetime import datetime
            db = SessionLocal()
            log_entry = GeminiApiCallLog(
                timestamp=datetime.utcnow(),
                purpose=f"company_news_{analysis_type}_{self.ticker}",
                prompt=prompt[:5000]  # Truncate very long prompts
            )
            db.add(log_entry)
            db.commit()
            db.close()
        except Exception as e:
            logger.error(f"Failed to log Gemini call: {str(e)}")

