"""
Base Agent Framework for Multi-Agent Market Intelligence System

Each agent is powered by Gemini with specialized memory and historical context.
"""

import asyncio
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, date
import google.generativeai as genai
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, func
from ..database import SessionLocal
from ..models import (
    AgentState, AgentMemory, AgentFinding, MarketIndicator, 
    MarketSentimentAnalysis, EconomicIndicator, MarketArticle,
    MarketNewsSummary, GeminiApiCallLog
)
from ..config import settings
from loguru import logger
import uuid


class AgentMemorySystem:
    """Multi-layered memory system for agents"""
    
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
    
    async def get_short_term_memory(self, days_back: int = 5) -> Dict:
        """Get recent findings and context (last 5 trading days)"""
        try:
            db = SessionLocal()
            cutoff_date = datetime.utcnow() - timedelta(days=days_back)
            
            # Get recent findings from this agent
            recent_findings = db.query(AgentFinding).filter(
                and_(
                    AgentFinding.agent_id == self.agent_id,
                    AgentFinding.created_at >= cutoff_date
                )
            ).order_by(desc(AgentFinding.created_at)).limit(50).all()
            
            # Get recent market data context
            recent_indicators = db.query(MarketIndicator).filter(
                MarketIndicator.timestamp >= cutoff_date
            ).order_by(desc(MarketIndicator.timestamp)).limit(100).all()
            
            return {
                'recent_findings': [
                    {
                        'finding_type': f.finding_type,
                        'subject': f.subject,
                        'confidence': f.confidence_score,
                        'data': f.finding_data,
                        'date': f.created_at.isoformat()
                    } for f in recent_findings
                ],
                'recent_market_data': [
                    {
                        'indicator': i.indicator_type,
                        'value': i.value,
                        'change_pct': i.change_pct,
                        'date': i.timestamp.isoformat()
                    } for i in recent_indicators
                ]
            }
        except Exception as e:
            logger.error(f"Error getting short-term memory: {e}")
            return {'recent_findings': [], 'recent_market_data': []}
        finally:
            db.close()
    
    async def get_medium_term_memory(self, weeks_back: int = 4) -> Dict:
        """Get weekly summaries and patterns (last month)"""
        try:
            db = SessionLocal()
            cutoff_date = datetime.utcnow() - timedelta(weeks=weeks_back)
            
            # Get weekly summaries from sentiment analysis
            weekly_summaries = db.query(MarketSentimentAnalysis).filter(
                MarketSentimentAnalysis.analysis_date >= cutoff_date
            ).order_by(desc(MarketSentimentAnalysis.analysis_date)).limit(20).all()
            
            # Get significant economic releases
            economic_releases = db.query(EconomicIndicator).filter(
                EconomicIndicator.release_date >= cutoff_date.date()
            ).order_by(desc(EconomicIndicator.release_date)).limit(30).all()
            
            return {
                'weekly_sentiment_summaries': [
                    {
                        'date': s.analysis_date.isoformat(),
                        'sentiment_score': s.sentiment_score,
                        'sentiment_label': s.sentiment_label,
                        'key_factors': s.key_factors,
                        'trend_analysis': s.trend_analysis,
                        'market_outlook': s.market_outlook
                    } for s in weekly_summaries
                ],
                'economic_releases': [
                    {
                        'indicator': e.indicator_name,
                        'category': e.category,
                        'value': e.value,
                        'previous_value': e.previous_value,
                        'release_date': e.release_date.isoformat(),
                        'reference_date': e.reference_date.isoformat()
                    } for e in economic_releases
                ]
            }
        except Exception as e:
            logger.error(f"Error getting medium-term memory: {e}")
            return {'weekly_sentiment_summaries': [], 'economic_releases': []}
        finally:
            db.close()
    
    async def get_long_term_memory(self, months_back: int = 6) -> Dict:
        """Get compressed long-term patterns and major events"""
        try:
            db = SessionLocal()
            cutoff_date = datetime.utcnow() - timedelta(days=months_back * 30)
            
            # Get major market events and patterns
            major_findings = db.query(AgentFinding).filter(
                and_(
                    AgentFinding.created_at >= cutoff_date,
                    AgentFinding.confidence_score >= 0.8  # High confidence findings only
                )
            ).order_by(desc(AgentFinding.confidence_score)).limit(100).all()
            
            # Get quarterly economic trends
            quarterly_data = db.query(EconomicIndicator).filter(
                and_(
                    EconomicIndicator.release_date >= cutoff_date.date(),
                    EconomicIndicator.period_type == 'quarterly'
                )
            ).order_by(desc(EconomicIndicator.release_date)).limit(50).all()
            
            return {
                'major_historical_findings': [
                    {
                        'agent': f.agent_id,
                        'finding_type': f.finding_type,
                        'subject': f.subject,
                        'confidence': f.confidence_score,
                        'summary': f.finding_data.get('summary', ''),
                        'date': f.created_at.isoformat()
                    } for f in major_findings
                ],
                'quarterly_economic_trends': [
                    {
                        'indicator': q.indicator_name,
                        'category': q.category,
                        'value': q.value,
                        'quarter': q.reference_date.isoformat(),
                        'trend': 'up' if q.value > q.previous_value else 'down' if q.previous_value else 'neutral'
                    } for q in quarterly_data if q.previous_value
                ]
            }
        except Exception as e:
            logger.error(f"Error getting long-term memory: {e}")
            return {'major_historical_findings': [], 'quarterly_economic_trends': []}
        finally:
            db.close()
    
    async def get_contextual_memory(self, context_type: str, subject: str = None) -> Dict:
        """Get relevant historical context for similar situations"""
        try:
            db = SessionLocal()
            
            # Get similar market conditions from the past
            if context_type == 'similar_sentiment':
                # Find periods with similar sentiment scores
                current_sentiment = db.query(MarketSentimentAnalysis).order_by(
                    desc(MarketSentimentAnalysis.analysis_date)
                ).first()
                
                if current_sentiment:
                    similar_periods = db.query(MarketSentimentAnalysis).filter(
                        and_(
                            MarketSentimentAnalysis.sentiment_score.between(
                                current_sentiment.sentiment_score - 1.0,
                                current_sentiment.sentiment_score + 1.0
                            ),
                            MarketSentimentAnalysis.analysis_date < datetime.utcnow() - timedelta(days=30)
                        )
                    ).order_by(desc(MarketSentimentAnalysis.analysis_date)).limit(10).all()
                    
                    return {
                        'similar_sentiment_periods': [
                            {
                                'date': p.analysis_date.isoformat(),
                                'sentiment_score': p.sentiment_score,
                                'market_outlook': p.market_outlook,
                                'trend_analysis': p.trend_analysis
                            } for p in similar_periods
                        ]
                    }
            
            elif context_type == 'stock_history' and subject:
                # Get historical analysis for specific stock
                stock_findings = db.query(AgentFinding).filter(
                    and_(
                        AgentFinding.subject == subject,
                        AgentFinding.finding_type.in_(['stock_analysis', 'recommendation', 'alert'])
                    )
                ).order_by(desc(AgentFinding.created_at)).limit(20).all()
                
                return {
                    'stock_historical_analysis': [
                        {
                            'date': f.created_at.isoformat(),
                            'finding_type': f.finding_type,
                            'confidence': f.confidence_score,
                            'data': f.finding_data
                        } for f in stock_findings
                    ]
                }
            
            return {}
        except Exception as e:
            logger.error(f"Error getting contextual memory: {e}")
            return {}
        finally:
            db.close()


class BaseAgent:
    """Base class for all AI agents with Gemini integration and memory"""
    
    def __init__(self, agent_id: str, agent_type: str, specialized_prompt: str):
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.specialized_prompt = specialized_prompt
        
        # Initialize Gemini model
        genai.configure(api_key=settings.google_api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        
        # Initialize memory system
        self.memory = AgentMemorySystem(agent_id)
        
        # Agent state
        self.state = {}
        self.last_run = None
    
    async def get_contextual_prompt(self, task_data: Dict) -> str:
        """Build contextual prompt with intelligent memory and smart token limits"""
        
        # Get memory with reasonable limits for token efficiency
        short_term = await self.memory.get_short_term_memory(3)  # 3 days instead of 5
        medium_term = await self.memory.get_medium_term_memory(2)  # 2 weeks instead of 4
        
        # Build intelligent context sections with token limits
        context_sections = []
        
        # Recent agent findings (last 3 days, max 5 findings)
        if short_term['recent_findings']:
            recent_findings = short_term['recent_findings'][:5]  # Limit to 5 most recent
            intelligent_findings = []
            for finding in recent_findings:
                # Keep essential intelligence but limit content size
                intelligent = {
                    'date': finding.get('timestamp', '')[:10],
                    'type': finding.get('finding_type', ''),
                    'confidence': finding.get('confidence', 0),
                    'summary': str(finding.get('finding_summary', ''))[:200]  # 200 chars max
                }
                intelligent_findings.append(intelligent)
            
            context_sections.append(f"""
RECENT AGENT FINDINGS (Last 3 days):
{json.dumps(intelligent_findings, indent=1)}
""")
        
        # Recent market intelligence (concise summary)
        if short_term['recent_market_data']:
            market_summary = short_term['recent_market_data'][:10]  # Last 10 data points
            context_sections.append(f"""
RECENT MARKET INTELLIGENCE:
{json.dumps(market_summary, indent=1)}
""")
        
        # Weekly patterns (last 2 weeks, summarized)
        if medium_term['weekly_sentiment_summaries']:
            weekly_summaries = medium_term['weekly_sentiment_summaries'][:2]  # Last 2 weeks
            context_sections.append(f"""
WEEKLY PATTERNS (Last 2 weeks):
{json.dumps(weekly_summaries, indent=1)}
""")
        
        # Current task data with intelligent summarization
        current_data_intelligent = {}
        if isinstance(task_data, dict):
            for key, value in task_data.items():
                if key == 'current_indicators' and isinstance(value, dict):
                    # Include indicator data but limit detail
                    current_data_intelligent[key] = {
                        name: {
                            'value': data.get('value'),
                            'unit': data.get('unit'),
                            'category': data.get('category')
                        } for name, data in value.items()
                    }
                elif key == 'market_agent_intelligence' and isinstance(value, dict):
                    # Include agent intelligence (this is key for multi-agent system)
                    current_data_intelligent[key] = value
                elif key == 'historical_context' and isinstance(value, dict):
                    # Limit historical context size
                    limited_context = {}
                    if 'previous_analyses' in value:
                        limited_context['previous_analyses'] = value['previous_analyses'][:3]  # Last 3 analyses
                    if 'economic_timeseries' in value:
                        # Limit timeseries to 30 entries max per indicator
                        limited_timeseries = {}
                        for indicator, series in value['economic_timeseries'].items():
                            if isinstance(series, list):
                                limited_timeseries[indicator] = series[-30:]  # Last 30 data points max
                            else:
                                limited_timeseries[indicator] = series
                        limited_context['economic_timeseries'] = limited_timeseries
                    current_data_intelligent[key] = limited_context
                elif key == 'recent_articles' and isinstance(value, list):
                    # CRITICAL: Pass full article list to LLM (don't truncate!)
                    # Each article should have title, summary, source, etc.
                    current_data_intelligent[key] = value  # Full list, not truncated
                else:
                    # Include other data with size limits
                    str_value = str(value)
                    current_data_intelligent[key] = str_value[:100] + "..." if len(str_value) > 100 else str_value
        
        # Build intelligent prompt with proper context
        full_prompt = f"""
{self.specialized_prompt}

INTELLIGENT AGENT CONTEXT:
{''.join(context_sections)}

CURRENT TASK DATA:
{json.dumps(current_data_intelligent, indent=1)}

Based on the intelligent context above and current data, provide your analysis. Reference relevant patterns and agent intelligence from the multi-layer memory system.
"""
        
        return full_prompt
    
    async def analyze_with_context(self, task_data: Dict, task_description: str) -> Dict:
        """Perform analysis with full historical context"""
        try:
            # Build contextual prompt
            prompt = await self.get_contextual_prompt(task_data)
            
            # Add specific task instruction
            full_prompt = f"{prompt}\n\nSPECIFIC TASK: {task_description}"
            
            # Log prompt details for debugging
            logger.info(f"[{self.agent_id}] Prompt length: {len(full_prompt)} characters")
            logger.info(f"[{self.agent_id}] Making LLM call to {self.model._model_name}")
            
            # Generate response with timeout protection
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(self.model.generate_content, full_prompt),
                    timeout=90.0  # 90 second timeout for LLM calls (long for complex master analysis)
                )
            except asyncio.TimeoutError:
                logger.error(f"[{self.agent_id}] LLM call timed out after 90 seconds")
                return {
                    'error': 'LLM analysis timed out after 45 seconds',
                    'error_type': 'TimeoutError',
                    'confidence': 0.0
                }
            
            # Log API call
            await self._log_gemini_call(full_prompt, 'contextual_analysis')
            
            if response and response.text:
                logger.info(f"[{self.agent_id}] LLM response received, length: {len(response.text)} characters")
                
                # Parse response
                analysis = self._parse_agent_response(response.text)
                
                # Store finding if significant
                if analysis.get('confidence', 0) >= 0.7:
                    await self._store_finding(analysis, task_data)
                
                return analysis
            
            logger.warning(f"[{self.agent_id}] Empty response from LLM")
            return {'error': 'No response from LLM'}
            
        except Exception as e:
            logger.error(f"[{self.agent_id}] Error in agent analysis: {e}")
            return {'error': str(e)}
    
    async def _store_finding(self, analysis: Dict, task_data: Dict):
        """Store significant finding in agent memory"""
        try:
            db = SessionLocal()
            
            finding = AgentFinding(
                agent_id=self.agent_id,
                finding_type=analysis.get('finding_type', 'general_analysis'),
                subject=analysis.get('subject', 'market'),
                confidence_score=analysis.get('confidence', 0.0),
                finding_data={
                    'analysis': analysis,
                    'task_data': task_data,
                    'agent_type': self.agent_type
                },
                expires_at=datetime.utcnow() + timedelta(days=30)  # Keep for 30 days
            )
            
            db.add(finding)
            db.commit()
            
            logger.info(f"Stored finding from {self.agent_id}: {analysis.get('finding_type', 'analysis')}")
            
        except Exception as e:
            logger.error(f"Error storing finding: {e}")
        finally:
            db.close()
    
    async def _log_gemini_call(self, prompt: str, purpose: str):
        """Log Gemini API call for debugging"""
        try:
            db = SessionLocal()
            
            log_entry = GeminiApiCallLog(
                timestamp=datetime.utcnow(),
                purpose=f"{self.agent_type}_{purpose}",
                prompt=prompt[:5000]  # Truncate very long prompts
            )
            
            db.add(log_entry)
            db.commit()
            
        except Exception as e:
            logger.warning(f"Failed to log Gemini call: {e}")
        finally:
            db.close()
    
    def _parse_agent_response(self, response_text: str) -> Dict:
        """Parse agent response - override in subclasses for specialized parsing"""
        try:
            # Strip markdown code blocks if present (same fix as Market Sentiment Agent)
            cleaned_text = response_text.strip()
            if cleaned_text.startswith('```json'):
                cleaned_text = cleaned_text[7:]  # Remove ```json
            if cleaned_text.startswith('```'):
                cleaned_text = cleaned_text[3:]  # Remove ```
            if cleaned_text.endswith('```'):
                cleaned_text = cleaned_text[:-3]  # Remove trailing ```
            
            cleaned_text = cleaned_text.strip()
            
            # Try direct JSON parsing first
            try:
                return json.loads(cleaned_text)
            except json.JSONDecodeError:
                pass
            
            # Try to extract JSON using regex as fallback
            import re
            json_match = re.search(r'\{.*\}', cleaned_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            
            # Fallback to text analysis
            return {
                'analysis': response_text,
                'confidence': 0.5,
                'finding_type': 'text_analysis'
            }
            
        except Exception as e:
            logger.warning(f"Error parsing agent response: {e}")
            logger.warning(f"Response text: {response_text[:200]}...")
            return {
                'analysis': response_text,
                'confidence': 0.3,
                'finding_type': 'unparsed_text'
            }
    
    async def run_cycle(self):
        """Main agent cycle - override in subclasses"""
        raise NotImplementedError
    
    async def get_agent_state(self) -> Dict:
        """Get current agent state"""
        try:
            db = SessionLocal()
            
            state_record = db.query(AgentState).filter(
                AgentState.agent_id == self.agent_id
            ).first()
            
            if state_record:
                return state_record.state_data
            
            return {}
            
        except Exception as e:
            logger.error(f"Error getting agent state: {e}")
            return {}
        finally:
            db.close()
    
    async def update_agent_state(self, new_state: Dict):
        """Update agent state"""
        try:
            db = SessionLocal()
            
            state_record = db.query(AgentState).filter(
                AgentState.agent_id == self.agent_id
            ).first()
            
            if state_record:
                state_record.state_data = new_state
                state_record.last_action_at = datetime.utcnow()
            else:
                state_record = AgentState(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    state_data=new_state,
                    last_action_at=datetime.utcnow(),
                    is_active=True
                )
                db.add(state_record)
            
            db.commit()
            self.state = new_state
            
        except Exception as e:
            logger.error(f"Error updating agent state: {e}")
        finally:
            db.close() 