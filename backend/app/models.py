from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, ForeignKey, JSON, Date
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base
from datetime import datetime


class Stock(Base):
    __tablename__ = "stocks"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), unique=True, index=True, nullable=False)
    company_name = Column(String(255), nullable=False)
    sector = Column(String(100))
    industry = Column(String(100))
    market_cap = Column(Float)
    current_price = Column(Float)
    last_updated = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    metrics = relationship("StockMetrics", back_populates="stock")
    news_articles = relationship("NewsArticle", back_populates="stock")
    recommendations = relationship("Recommendation", back_populates="stock")


class StockMetrics(Base):
    __tablename__ = "stock_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    
    # Valuation Metrics
    pe_ratio = Column(Float)
    forward_pe = Column(Float)
    peg_ratio = Column(Float)
    price_to_book = Column(Float)
    price_to_sales = Column(Float)
    
    # Historical Context
    pe_5_year_median = Column(Float)
    pe_percentile = Column(Float)  # Current PE vs historical range (0-100)
    
    # Financial Health
    debt_to_equity = Column(Float)
    current_ratio = Column(Float)
    quick_ratio = Column(Float)
    return_on_equity = Column(Float)
    return_on_assets = Column(Float)
    
    # Cash Flow
    free_cash_flow_per_share = Column(Float)
    fcf_growth_rate = Column(Float)  # YoY growth rate
    operating_cash_flow = Column(Float)
    
    # Technical Indicators
    sma_50 = Column(Float)
    sma_200 = Column(Float)
    rsi_14 = Column(Float)
    macd_signal = Column(String(10))  # 'bullish', 'bearish', 'neutral'
    bollinger_position = Column(Float)  # -1 to 1, where price sits in bands
    
    # Volume and Momentum
    avg_volume_50 = Column(Float)
    volume_ratio = Column(Float)  # Current volume vs average
    momentum_score = Column(Float)  # Custom momentum calculation
    
    # Calculated Fields
    intrinsic_value_estimate = Column(Float)
    margin_of_safety = Column(Float)  # Percentage below intrinsic value
    quality_score = Column(Float)  # 0-100 composite quality metric
    
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    stock = relationship("Stock", back_populates="metrics")


class NewsArticle(Base):
    __tablename__ = "news_articles"
    
    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    
    title = Column(String(500), nullable=False)
    summary = Column(Text)  # AI-generated summary (max 300 chars)
    url = Column(String(1000))
    source = Column(String(100))
    
    # Sentiment Analysis
    sentiment_score = Column(Float)  # -1 to 1 (negative to positive)
    sentiment_label = Column(String(20))  # 'positive', 'negative', 'neutral'
    confidence_score = Column(Float)  # 0 to 1
    
    # Impact Classification
    impact_level = Column(String(20))  # 'high', 'medium', 'low'
    impact_categories = Column(JSON)  # ['earnings', 'management', 'regulation', etc.]
    
    # Keywords and Signals
    extracted_signals = Column(JSON)  # Key actionable signals
    keywords = Column(JSON)  # Important keywords/entities
    
    published_at = Column(DateTime(timezone=True))
    processed_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    stock = relationship("Stock", back_populates="news_articles")


class Recommendation(Base):
    __tablename__ = "recommendations"
    
    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    
    # Core Recommendation
    action = Column(String(10), nullable=False)  # 'BUY', 'SELL', 'HOLD'
    confidence = Column(Float, nullable=False)  # 0 to 1
    target_price = Column(Float)
    stop_loss = Column(Float)
    
    # Analysis Components
    valuation_signal = Column(Float)  # -1 to 1
    technical_signal = Column(Float)  # -1 to 1
    news_sentiment_signal = Column(Float)  # -1 to 1
    overall_score = Column(Float)  # Combined signal
    
    # Reasoning and Context
    reasoning = Column(Text, nullable=False)
    key_factors = Column(JSON)  # List of key factors
    risk_level = Column(String(20))  # 'low', 'medium', 'high'
    time_horizon = Column(String(20))  # 'short', 'medium', 'long'
    
    # Price Ranges
    support_level = Column(Float)
    resistance_level = Column(Float)
    expected_return = Column(Float)  # Percentage
    max_downside = Column(Float)  # Percentage (negative)
    
    # Metadata
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True))  # When recommendation becomes stale
    model_version = Column(String(50))
    
    # Relationships
    stock = relationship("Stock", back_populates="recommendations")


class MarketIndicator(Base):
    """Historical market indicators (S&P 500, VIX, etc.) for time series analysis."""
    __tablename__ = "market_indicators"
    
    id = Column(Integer, primary_key=True, index=True)
    indicator_type = Column(String(50), nullable=False, index=True)  # 'sp500', 'vix', 'treasury_10y', etc.
    value = Column(Float, nullable=False)
    change_pct = Column(Float, nullable=True)  # 5-day percentage change
    timestamp = Column(DateTime, nullable=False, index=True)
    market_session = Column(String(20))  # 'open', 'closed', 'premarket', 'aftermarket'
    data_source = Column(String(50), nullable=False)  # 'yahoo', 'alpha_vantage', 'fred'
    is_valid = Column(Boolean, default=True)  # For data quality tracking
    
    created_at = Column(DateTime, default=datetime.utcnow)


class NewsSentiment(Base):
    """Daily news sentiment analysis aggregated from multiple sources."""
    __tablename__ = "news_sentiment"
    
    id = Column(Integer, primary_key=True, index=True)
    analysis_date = Column(Date, index=True)  # Date of the analysis
    overall_sentiment = Column(Float)  # -1 to 1 sentiment score
    sentiment_label = Column(String(20))  # 'Positive', 'Negative', 'Neutral'
    confidence_score = Column(Float)  # 0 to 1 confidence
    articles_analyzed = Column(Integer)  # Number of articles analyzed
    source_breakdown = Column(JSON)  # Details by source (reddit, news, etc.)
    data_source = Column(String, default='multi_source')  # Source combination used
    created_at = Column(DateTime, default=datetime.utcnow)


class MarketSentiment(Base):
    """Market sentiment data collection and storage."""
    __tablename__ = "market_sentiment"
    
    id = Column(Integer, primary_key=True, index=True)
    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Index Data
    sp500_price = Column(Float, nullable=True)
    sp500_change_pct = Column(Float, nullable=True)
    dow_price = Column(Float, nullable=True)
    dow_change_pct = Column(Float, nullable=True)
    nasdaq_price = Column(Float, nullable=True)
    nasdaq_change_pct = Column(Float, nullable=True)
    
    # Volatility Data
    vix_value = Column(Float, nullable=True)
    vix_change_pct = Column(Float, nullable=True)
    
    # Options Data
    put_call_ratio = Column(Float, nullable=True)
    
    # Treasury Data
    treasury_10y_yield = Column(Float, nullable=True)
    
    # Dollar Data
    dxy_value = Column(Float, nullable=True)
    dxy_change_pct = Column(Float, nullable=True)
    
    # Market Breadth
    new_highs = Column(Integer, nullable=True)
    new_lows = Column(Integer, nullable=True)
    advance_decline_ratio = Column(Float, nullable=True)
    
    # News Sentiment
    news_sentiment_score = Column(Float, nullable=True)  # -1 to 1
    news_sentiment_label = Column(String(20), nullable=True)  # 'Positive', 'Negative', 'Neutral'
    news_confidence = Column(Float, nullable=True)  # 0 to 1
    
    # Calculated Scores
    momentum_score = Column(Float, nullable=True)
    fear_greed_score = Column(Float, nullable=True)
    breadth_score = Column(Float, nullable=True)
    overall_sentiment_score = Column(Float, nullable=True)
    sentiment_label = Column(String(50), nullable=True)
    
    # Analysis Results
    key_drivers = Column(Text, nullable=True)  # JSON string
    trend_analysis = Column(Text, nullable=True)
    data_completeness = Column(Float, nullable=True)
    
    # 🧠 AGENT INTELLIGENCE FIELDS (NEW)
    agent_sentiment_score = Column(Float, nullable=True)  # 1-10 from Gemini analysis
    agent_sentiment_label = Column(String(50), nullable=True)  # "Extremely Bearish" to "Extremely Bullish"
    agent_confidence = Column(Float, nullable=True)  # Agent's confidence in analysis
    agent_key_insights = Column(JSON, nullable=True)  # ["insight1", "insight2", "insight3"]
    agent_historical_context = Column(Text, nullable=True)  # "Similar to March 2020..."
    agent_risk_factors = Column(JSON, nullable=True)  # ["risk1", "risk2"]
    agent_trend_direction = Column(String(20), nullable=True)  # "bullish|bearish|neutral|mixed"
    agent_volatility_assessment = Column(String(20), nullable=True)  # "low|moderate|high|extreme"
    agent_next_update = Column(DateTime, nullable=True)  # When agent will next analyze
    agent_last_updated = Column(DateTime, nullable=True)  # When agent last provided analysis
    has_agent_analysis = Column(Boolean, default=False, index=True)  # Quick lookup for frontend
    
    created_at = Column(DateTime, default=datetime.utcnow)


class MarketSentimentAnalysis(Base):
    """LLM-generated market sentiment analysis based on historical data."""
    __tablename__ = "market_sentiment_analysis"
    
    id = Column(Integer, primary_key=True, index=True)
    analysis_date = Column(DateTime, default=datetime.utcnow, index=True)
    sentiment_score = Column(Float)  # 1-10 scale from LLM
    sentiment_label = Column(String)  # "Extremely Bearish" to "Extremely Bullish"
    confidence_level = Column(Float)  # LLM's confidence in the analysis
    key_factors = Column(JSON)  # List of key factors driving sentiment
    trend_analysis = Column(Text)  # LLM's detailed trend analysis
    historical_context = Column(Text)  # LLM's comparison to historical patterns
    market_outlook = Column(Text)  # LLM's forward-looking analysis
    data_period_start = Column(DateTime)  # Start of data period analyzed
    data_period_end = Column(DateTime)  # End of data period analyzed
    indicators_analyzed = Column(JSON)  # List of indicators included in analysis
    created_at = Column(DateTime, default=datetime.utcnow)


class UserWatchlist(Base):
    __tablename__ = "user_watchlists"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(100), nullable=False)  # For future user management
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    
    # User Preferences
    alert_threshold = Column(Float)  # Custom confidence threshold for alerts
    notification_enabled = Column(Boolean, default=True)
    
    added_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    stock = relationship("Stock")


class SystemLog(Base):
    __tablename__ = "system_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    service = Column(String(50), nullable=False)  # 'screener', 'news', 'llm'
    action = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False)  # 'success', 'error', 'warning'
    message = Column(Text)
    log_metadata = Column(JSON)
    
    timestamp = Column(DateTime(timezone=True), server_default=func.now()) 


class MarketNewsSummary(Base):
    __tablename__ = "market_news_summaries"

    id = Column(Integer, primary_key=True, index=True)
    summary = Column(Text, nullable=False)  # LLM-generated summary of top 10 articles
    article_ids = Column(JSON, nullable=True)  # List of article IDs included in this summary
    created_at = Column(DateTime(timezone=True), server_default=func.now()) 


class EconomicIndicator(Base):
    """Economic indicators and fundamental data."""
    __tablename__ = "economic_indicators"
    
    id = Column(Integer, primary_key=True, index=True)
    indicator_name = Column(String(100), nullable=False, index=True)  # 'cpi', 'unemployment_rate', 'fed_funds_rate', etc.
    category = Column(String(50), nullable=False, index=True)  # 'inflation', 'employment', 'interest_rates', 'gdp', 'consumer', 'manufacturing'
    value = Column(Float, nullable=False)
    unit = Column(String(50))  # '%', 'index', 'millions', 'basis_points', etc.
    period_type = Column(String(30))  # 'monthly', 'quarterly', 'annual'
    reference_date = Column(Date, nullable=False, index=True)  # The date the indicator refers to
    release_date = Column(Date, nullable=False, index=True)  # When the data was released
    source = Column(String(50), nullable=False)  # 'bls', 'fred', 'bea', etc.
    is_preliminary = Column(Boolean, default=False)  # Whether this is preliminary data
    is_revised = Column(Boolean, default=False)  # Whether this is a revision
    previous_value = Column(Float)  # Previous period value for comparison
    forecast_value = Column(Float)  # Consensus forecast if available
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class EconomicEvent(Base):
    """Upcoming economic events and data releases."""
    __tablename__ = "economic_events"
    
    id = Column(Integer, primary_key=True, index=True)
    event_name = Column(String(200), nullable=False)
    category = Column(String(50), nullable=False, index=True)
    scheduled_date = Column(DateTime(timezone=True), nullable=False, index=True)
    importance = Column(String(10), nullable=False)  # 'high', 'medium', 'low'
    previous_value = Column(Float)
    forecast_value = Column(Float)
    actual_value = Column(Float)  # Filled after release
    currency = Column(String(3), default='USD')
    country = Column(String(3), default='US')
    impact_description = Column(Text)  # Why this event is important
    source = Column(String(50))
    is_released = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FundamentalsAnalysis(Base):
    """LLM-generated analysis of economic fundamentals."""
    __tablename__ = "fundamentals_analysis"
    
    id = Column(Integer, primary_key=True, index=True)
    analysis_date = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    overall_assessment = Column(String(50))  # 'expansionary', 'contractionary', 'neutral', 'mixed'
    economic_cycle_stage = Column(String(30))  # 'early_cycle', 'mid_cycle', 'late_cycle', 'recession'
    inflation_outlook = Column(String(30))  # 'rising', 'falling', 'stable', 'uncertain'
    employment_outlook = Column(String(30))  # 'strong', 'moderate', 'weak', 'deteriorating'
    monetary_policy_stance = Column(String(30))  # 'accommodative', 'neutral', 'restrictive'
    key_insights = Column(JSON)  # List of key insights from the analysis
    market_implications = Column(Text)  # What this means for markets
    sector_impacts = Column(JSON)  # How different sectors might be affected
    risk_factors = Column(JSON)  # Key risks to watch
    data_period_start = Column(Date)  # Start of data period analyzed
    data_period_end = Column(Date)  # End of data period analyzed
    confidence_level = Column(Float)  # LLM's confidence in the analysis (0-1)
    indicators_analyzed = Column(JSON)  # List of indicators included in analysis
    explanation = Column(Text)  # LLM-generated summary explanation for the frontend
    created_at = Column(DateTime(timezone=True), server_default=func.now()) 


class GeminiApiCallLog(Base):
    __tablename__ = "gemini_api_call_logs"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    purpose = Column(String(100), nullable=False)
    prompt = Column(Text, nullable=False) 


# NEW AGENT SYSTEM MODELS

class AgentState(Base):
    """Persistent state for AI agents"""
    __tablename__ = "agent_states"
    
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String(50), unique=True, nullable=False, index=True)
    agent_type = Column(String(50), nullable=False, index=True)
    state_data = Column(JSON, nullable=False)  # Agent's current state and memory
    last_action_at = Column(DateTime, default=datetime.utcnow, index=True)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentFinding(Base):
    """Findings and insights generated by agents"""
    __tablename__ = "agent_findings"
    
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String(50), nullable=False, index=True)
    finding_type = Column(String(50), nullable=False, index=True)  # 'sentiment_shift', 'news_alert', 'pattern_detected', etc.
    subject = Column(String(100), index=True)  # ticker, market, sector, etc.
    confidence_score = Column(Float, nullable=False, index=True)  # 0.0 to 1.0
    finding_data = Column(JSON, nullable=False)  # The actual finding/insight
    expires_at = Column(DateTime, index=True)  # When this finding becomes stale
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class AgentCommunication(Base):
    """Messages between agents"""
    __tablename__ = "agent_communications"
    
    id = Column(Integer, primary_key=True, index=True)
    from_agent_id = Column(String(50), nullable=False, index=True)
    to_agent_id = Column(String(50), index=True)  # NULL for broadcast messages
    message_type = Column(String(50), nullable=False, index=True)  # 'data_request', 'finding_share', 'alert', etc.
    message_data = Column(JSON, nullable=False)
    priority = Column(Integer, default=5, index=True)  # 1=highest, 10=lowest
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    processed_at = Column(DateTime, index=True)


class AgentMemory(Base):
    """Long-term memory storage for agents"""
    __tablename__ = "agent_memory"
    
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String(50), nullable=False, index=True)
    memory_type = Column(String(50), nullable=False, index=True)  # 'pattern', 'correlation', 'lesson_learned', etc.
    memory_key = Column(String(200), nullable=False, index=True)  # searchable key
    memory_data = Column(JSON, nullable=False)
    importance_score = Column(Float, default=0.5, index=True)  # How important this memory is
    access_count = Column(Integer, default=0)  # How often this memory has been accessed
    last_accessed = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class MarketEvent(Base):
    """Significant market events detected by agents"""
    __tablename__ = "market_events"
    
    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(50), nullable=False, index=True)  # 'volatility_spike', 'market_drop', 'news_event', etc.
    severity = Column(String(20), nullable=False, index=True)  # 'low', 'medium', 'high', 'critical'
    detected_by_agent = Column(String(50), nullable=False, index=True)
    event_data = Column(JSON, nullable=False)
    agent_responses = Column(JSON)  # How different agents responded to this event
    is_resolved = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class AgentPerformance(Base):
    """Track agent performance metrics"""
    __tablename__ = "agent_performance"
    
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String(50), nullable=False, index=True)
    metric_name = Column(String(50), nullable=False, index=True)  # 'accuracy', 'prediction_rate', 'response_time', etc.
    metric_value = Column(Float, nullable=False)
    measurement_date = Column(Date, nullable=False, index=True)
    
    # Ensure unique constraint
    __table_args__ = (
        {'mysql_charset': 'utf8mb4'},
    )


class MarketArticle(Base):
    """Market news articles with LLM processing"""
    __tablename__ = "market_articles"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    ai_summary = Column(Text)  # AI-generated brief summary
    content = Column(Text)  # Full article content (if available)
    url = Column(String(1000), nullable=False)
    source = Column(String(100), nullable=False)
    author = Column(String(200))
    
    # AI Analysis
    implication_title = Column(String(500))  # LLM-generated brief headline
    sentiment = Column(String(20))  # 'bullish', 'bearish', 'neutral'
    market_impact = Column(Float)  # 0-1 how significant this news is
    affected_sectors = Column(JSON)  # List of sectors this might affect
    mentioned_tickers = Column(JSON)  # Tickers mentioned in the article
    relevance_score = Column(Float)  # Overall relevance score
    content_hash = Column(String(32))  # For deduplication
    
    # Timestamps
    published_at = Column(DateTime(timezone=True), nullable=False, index=True)
    processed_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now()) 


# STOCK-LEVEL AGENT MODELS

class StockAnalysis(Base):
    """Comprehensive stock analysis from master stock agent"""
    __tablename__ = "stock_analysis"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    analysis_date = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Current Stock Data
    current_price = Column(Float, nullable=False)
    price_change_pct = Column(Float)
    volume = Column(Float)
    market_cap = Column(Float)
    
    # Valuation Analysis
    pe_ratio = Column(Float)
    forward_pe = Column(Float)
    peg_ratio = Column(Float)
    price_to_book = Column(Float)
    price_to_sales = Column(Float)
    
    # 🧠 MASTER AGENT SYNTHESIS
    overall_rating = Column(String(20))  # 'Strong Buy', 'Buy', 'Hold', 'Sell', 'Strong Sell'
    confidence_score = Column(Float)  # 0-1 (nullable since LLM may not always provide it)
    target_price = Column(Float)
    upside_potential = Column(Float)  # Percentage upside to target
    
    # Key Insights
    key_insights = Column(JSON)  # ["insight1", "insight2", "insight3"]
    valuation_assessment = Column(String(50))  # 'Undervalued', 'Fair Value', 'Overvalued'
    risk_factors = Column(JSON)  # ["risk1", "risk2"]
    catalysts = Column(JSON)  # ["catalyst1", "catalyst2"]
    
    # Agent Cross-Communication
    market_context = Column(JSON)  # Input from market agents
    sentiment_signals = Column(JSON)  # From sentiment agents  
    news_impact = Column(JSON)  # From news agents  
    fundamentals_outlook = Column(JSON)  # From fundamentals agents
    
    # Analysis Explanation
    why_current_price = Column(Text)  # "MSFT is trading at $X because..."
    future_outlook = Column(Text)  # "Looking ahead, expect..."
    comparison_to_market = Column(Text)  # "Relative to S&P 500..."
    
    # Technical Analysis
    technical_rating = Column(String(20))  # 'Bullish', 'Bearish', 'Neutral'
    support_level = Column(Float)
    resistance_level = Column(Float)
    trend_direction = Column(String(20))  # 'Uptrend', 'Downtrend', 'Sideways'
    
    # Agent Metadata
    agent_id = Column(String(50), nullable=False, index=True)
    market_agents_consulted = Column(JSON)  # List of market agents consulted
    data_sources_used = Column(JSON)  # List of data sources
    next_update_target = Column(DateTime)
    
    created_at = Column(DateTime, default=datetime.utcnow)


class StockSentimentAnalysis(Base):
    """Stock-specific sentiment analysis"""
    __tablename__ = "stock_sentiment_analysis"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    analysis_date = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Sentiment Scores
    overall_sentiment = Column(Float, nullable=False)  # -1 to 1
    sentiment_label = Column(String(30))  # 'Very Bearish' to 'Very Bullish'
    confidence_level = Column(Float)  # 0-1
    
    # Sentiment Breakdown
    news_sentiment = Column(Float)  # From stock news
    social_sentiment = Column(Float)  # From social media (future)
    analyst_sentiment = Column(Float)  # From analyst ratings
    options_sentiment = Column(Float)  # From options flow (future)
    
    # Context Analysis
    vs_market_sentiment = Column(Float)  # How this stock sentiment compares to market
    vs_sector_sentiment = Column(Float)  # How this compares to sector
    sentiment_trend = Column(String(20))  # 'Improving', 'Deteriorating', 'Stable'
    
    # Key Factors
    positive_factors = Column(JSON)  # ["factor1", "factor2"]
    negative_factors = Column(JSON)  # ["concern1", "concern2"]
    sentiment_drivers = Column(JSON)  # ["driver1", "driver2"]
    
    # Market Context (from market agents)
    market_sentiment_context = Column(JSON)
    
    # Agent Metadata
    agent_id = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class StockNewsAnalysis(Base):
    """Stock-specific news analysis"""
    __tablename__ = "stock_news_analysis"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    analysis_date = Column(DateTime, default=datetime.utcnow, index=True)
    
    # News Impact Assessment
    overall_news_impact = Column(String(20))  # 'Very Positive', 'Positive', 'Neutral', 'Negative', 'Very Negative'
    impact_confidence = Column(Float)  # 0-1
    time_horizon = Column(String(20))  # 'Short-term', 'Medium-term', 'Long-term'
    
    # Key News Events
    major_events = Column(JSON)  # [{"event": "earnings beat", "impact": "positive", "date": "..."}]
    breaking_news = Column(JSON)  # Recent breaking news
    earnings_updates = Column(JSON)  # Earnings-related news
    management_updates = Column(JSON)  # Management changes, guidance, etc.
    
    # News Categorization
    positive_news_count = Column(Integer, default=0)
    negative_news_count = Column(Integer, default=0)
    neutral_news_count = Column(Integer, default=0)
    
    # Sentiment Analysis
    news_sentiment_score = Column(Float)  # -1 to 1
    sentiment_trend = Column(String(20))  # 'Improving', 'Deteriorating', 'Stable'
    
    # Market Context
    sector_news_context = Column(JSON)  # Relevant sector news from market agents
    broader_market_news_impact = Column(JSON)  # How market news affects this stock
    
    # Key Insights
    key_themes = Column(JSON)  # ["growth concerns", "margin expansion", etc.]
    risk_events = Column(JSON)  # ["regulatory review", "competition threat"]
    opportunity_events = Column(JSON)  # ["new product launch", "market expansion"]
    
    # Agent Metadata
    agent_id = Column(String(50), nullable=False, index=True)
    articles_analyzed = Column(Integer, default=0)
    market_news_context = Column(JSON)  # Input from market news agent
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # New comprehensive news fields (from CompanyNewsCollector)
    company_summary = Column(Text)  # Comprehensive company overview
    recent_developments_summary = Column(Text)  # What's new in last 30 days
    outlook = Column(Text)  # Forward-looking outlook
    
    # Earnings Details
    latest_earnings_date = Column(Date)
    latest_earnings_result = Column(String(50))  # 'Beat', 'Miss', 'In-line'
    latest_earnings_summary = Column(Text)
    eps_actual = Column(Float)
    eps_expected = Column(Float)
    
    # Detailed Company Profile
    key_risks = Column(JSON)  # ["risk1", "risk2"]
    key_opportunities = Column(JSON)  # ["opp1", "opp2"]
    recent_product_developments = Column(JSON)  # [{date, product, description}]
    management_changes = Column(JSON)  # [{date, change}]
    regulatory_issues = Column(JSON)  # [{date, issue, status}]
    competitive_position = Column(Text)
    
    # Update metadata
    last_significant_update = Column(DateTime)  # When summary was materially updated


class StockFundamentalsAnalysis(Base):
    """Stock-specific fundamentals analysis"""
    __tablename__ = "stock_fundamentals_analysis"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    analysis_date = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Financial Health
    revenue_growth = Column(Float)  # YoY revenue growth
    earnings_growth = Column(Float)  # YoY earnings growth
    profit_margins = Column(Float)  # Net profit margin
    debt_to_equity = Column(Float)
    return_on_equity = Column(Float)
    free_cash_flow = Column(Float)
    
    # Quarter Information
    latest_quarter_date = Column(String(20))  # Date of latest quarter (YYYY-MM-DD)
    latest_quarter_label = Column(String(10))  # Quarter label (Q1, Q2, Q3, Q4)
    latest_eps = Column(Float)  # EPS from latest quarter
    
    # Valuation Metrics
    current_pe = Column(Float)
    forward_pe = Column(Float)
    historical_pe_avg = Column(Float)  # 5-year average
    pe_vs_industry = Column(Float)  # How PE compares to industry
    pe_vs_market = Column(Float)  # How PE compares to market
    
    # Growth Analysis
    revenue_growth_trend = Column(String(20))  # 'Accelerating', 'Stable', 'Decelerating'
    earnings_consistency = Column(Float)  # 0-1 score for earnings consistency
    guidance_outlook = Column(String(20))  # 'Positive', 'Neutral', 'Negative'
    
    # Competitive Position
    market_share_trend = Column(String(20))  # 'Gaining', 'Stable', 'Losing'
    competitive_advantages = Column(JSON)  # ["moat1", "moat2"]
    competitive_threats = Column(JSON)  # ["threat1", "threat2"]
    
    # Economic Context (from market fundamentals agent)
    economic_impact_assessment = Column(Text)  # How macro environment affects this stock
    sector_fundamentals_context = Column(JSON)  # Sector-specific fundamentals
    interest_rate_sensitivity = Column(String(20))  # 'High', 'Medium', 'Low'
    
    # Key Insights
    fundamental_strengths = Column(JSON)  # ["strength1", "strength2"]
    fundamental_concerns = Column(JSON)  # ["concern1", "concern2"]
    valuation_conclusion = Column(String(30))  # 'Undervalued', 'Fair Value', 'Overvalued'
    
    # Agent Metadata
    agent_id = Column(String(50), nullable=False, index=True)
    market_fundamentals_context = Column(JSON)  # Input from market fundamentals agent
    data_quality_score = Column(Float)  # 0-1
    created_at = Column(DateTime, default=datetime.utcnow)


class StockAgentCommunication(Base):
    """Communication between stock agents and market agents"""
    __tablename__ = "stock_agent_communication"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    from_agent_id = Column(String(50), nullable=False, index=True)
    to_agent_id = Column(String(50), nullable=False, index=True)
    
    # Communication Details
    message_type = Column(String(50), nullable=False)  # 'context_request', 'data_share', 'alert'
    message_data = Column(JSON, nullable=False)
    response_data = Column(JSON)  # Response from target agent
    
    # Context
    request_context = Column(Text)  # Why this communication was initiated
    priority = Column(Integer, default=5)  # 1=urgent, 10=low
    
    # Status
    is_processed = Column(Boolean, default=False)
    processed_at = Column(DateTime)
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class StockWatchlist(Base):
    """User's stock watchlist with agent intelligence"""
    __tablename__ = "stock_watchlist"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(100), nullable=False, index=True)  # For future user management
    ticker = Column(String(10), nullable=False, index=True)
    
    # User Preferences
    alert_threshold = Column(Float, default=0.8)  # Confidence threshold for alerts
    notification_types = Column(JSON)  # ["price_alert", "news_alert", "rating_change"]
    target_price = Column(Float)  # User's target price
    stop_loss = Column(Float)  # User's stop loss
    
    # Agent Intelligence Summary (cached for quick access)
    latest_rating = Column(String(20))
    latest_target_price = Column(Float)
    latest_confidence = Column(Float)
    latest_key_insight = Column(Text)
    last_agent_update = Column(DateTime)
    
    # Settings
    is_active = Column(Boolean, default=True)
    added_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StockTimeSeries(Base):
    """Time series data for individual stocks - similar to economic_indicators but for stocks"""
    __tablename__ = "stock_timeseries"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    
    # Price Data
    open_price = Column(Float)
    high_price = Column(Float)
    low_price = Column(Float)
    close_price = Column(Float)
    adjusted_close = Column(Float)
    volume = Column(Float)
    
    # Valuation Metrics (may not be available daily)
    pe_ratio = Column(Float)
    pb_ratio = Column(Float)
    ps_ratio = Column(Float)
    market_cap = Column(Float)
    enterprise_value = Column(Float)
    
    # Growth Metrics (quarterly/annual data)
    revenue = Column(Float)
    earnings = Column(Float)
    profit_margin = Column(Float)
    
    # Technical Indicators (calculated)
    rsi_14 = Column(Float)  # Relative Strength Index
    macd = Column(Float)  # MACD line
    macd_signal = Column(Float)  # MACD signal line
    sma_20 = Column(Float)  # 20-day simple moving average
    sma_50 = Column(Float)  # 50-day simple moving average
    sma_200 = Column(Float)  # 200-day simple moving average
    bollinger_upper = Column(Float)
    bollinger_lower = Column(Float)
    
    # Volume Analysis
    volume_sma_20 = Column(Float)  # 20-day average volume
    volume_ratio = Column(Float)  # Current volume vs average
    
    # Metadata
    data_source = Column(String(50), default='yfinance')
    data_quality = Column(Float)  # 0-1 completeness score
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Composite unique constraint
    __table_args__ = (
        {'comment': 'Time series data for individual stocks'},
    )


class StockTechnicalAnalysis(Base):
    """AI-powered technical analysis for individual stocks"""
    __tablename__ = "stock_technical_analysis"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    analysis_date = Column(DateTime, nullable=False, index=True)
    
    # Trend Analysis
    trend_direction = Column(String(20))  # 'Bullish', 'Bearish', 'Sideways'
    trend_strength = Column(Float)  # 0-1
    trend_duration_days = Column(Integer)
    trend_reliability = Column(Float)  # 0-1
    
    # Support/Resistance Levels
    support_level_1 = Column(Float)
    support_level_2 = Column(Float)
    resistance_level_1 = Column(Float)
    resistance_level_2 = Column(Float)
    support_strength = Column(Float)  # 0-1
    resistance_strength = Column(Float)  # 0-1
    
    # Momentum Analysis
    momentum_score = Column(Float)  # -1 to 1
    momentum_trend = Column(String(20))  # 'Accelerating', 'Stable', 'Decelerating'
    rsi_assessment = Column(String(20))  # 'Oversold', 'Neutral', 'Overbought'
    macd_signal = Column(String(20))  # 'Bullish', 'Bearish', 'Neutral'
    
    # Volatility Analysis
    volatility_level = Column(String(20))  # 'Low', 'Medium', 'High'
    volatility_percentile = Column(Float)  # vs 1 year history
    bollinger_position = Column(String(20))  # 'Upper', 'Middle', 'Lower'
    
    # Volume Analysis
    volume_trend = Column(String(20))  # 'Increasing', 'Stable', 'Decreasing'
    unusual_volume = Column(Boolean)
    volume_confirmation = Column(Boolean)  # Does volume confirm price trend?
    
    # Pattern Recognition
    chart_pattern = Column(Text)  # Pattern description (can be long)
    pattern_reliability = Column(Float)  # 0-1
    pattern_target = Column(Float)  # Projected price target from pattern
    
    # Market Context
    vs_market_performance = Column(Float)  # % difference from S&P 500
    vs_sector_performance = Column(Float)  # % difference from sector
    relative_strength = Column(Float)  # 0-100 percentile
    correlation_to_market = Column(Float)  # -1 to 1
    
    # Key Levels (for entry/exit)
    entry_points = Column(JSON)  # [{"price": 150.0, "reason": "support bounce", "strength": 0.8}]
    exit_points = Column(JSON)  # [{"price": 165.0, "reason": "resistance", "strength": 0.7}]
    stop_loss_level = Column(Float)
    
    # LLM Generated Insights
    technical_summary = Column(Text)  # AI-generated summary
    key_observations = Column(JSON)  # ["observation1", "observation2"]
    trading_strategy = Column(Text)  # AI recommendation for traders
    risk_assessment = Column(Text)  # Technical risk factors
    
    # Outlook
    short_term_outlook = Column(String(20))  # Next 1-5 days
    medium_term_outlook = Column(String(20))  # Next 1-4 weeks
    
    # Agent Metadata
    agent_id = Column(String(50), nullable=False)
    confidence_score = Column(Float)  # 0-1
    days_analyzed = Column(Integer)  # How many days of data used
    market_context_integrated = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TrackedStock(Base):
    """Stocks that receive daily automated analysis"""
    __tablename__ = "tracked_stocks"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), unique=True, nullable=False, index=True)
    
    # Stock Info
    company_name = Column(String(255))
    sector = Column(String(100))
    exchange = Column(String(20))
    
    # Tracking Settings
    is_active = Column(Boolean, default=True)
    update_frequency = Column(String(20), default='daily')  # 'daily', 'weekly'
    priority = Column(Integer, default=5)  # 1=high, 10=low (for API rate limiting)
    
    # Usage Stats
    analysis_count = Column(Integer, default=0)
    last_analysis_date = Column(DateTime)
    last_data_collection_date = Column(DateTime)
    user_request_count = Column(Integer, default=0)  # How many times users looked at it
    
    # Status
    data_collection_status = Column(String(20), default='active')  # 'active', 'paused', 'error'
    last_error = Column(Text)
    consecutive_errors = Column(Integer, default=0)
    
    # Timestamps
    added_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Metadata
    added_by = Column(String(50), default='system')  # 'system', 'user', 'admin'
    notes = Column(Text)


class CompanyNewsSummary(Base):
    """Persistent company news profile - similar to MarketNewsSummary but for individual companies"""
    __tablename__ = "company_news_summaries"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True, unique=True)
    
    # Company Overview
    company_name = Column(String(255))
    sector = Column(String(100))
    
    # Latest Earnings (Updated when new earnings)
    latest_earnings_date = Column(Date)
    latest_earnings_result = Column(String(50))  # 'Beat', 'Miss', 'In-line'
    latest_earnings_summary = Column(Text)  # What happened in latest earnings
    eps_actual = Column(Float)
    eps_expected = Column(Float)
    revenue_actual = Column(Float)
    revenue_expected = Column(Float)
    guidance = Column(Text)  # Forward guidance provided
    
    # Persistent Company Profile (Updated incrementally)
    key_risks = Column(JSON)  # ["risk1", "risk2", "risk3"]
    key_opportunities = Column(JSON)  # ["opp1", "opp2"]
    recent_product_developments = Column(JSON)  # [{date, product, description}]
    management_changes = Column(JSON)  # [{date, change, description}]
    regulatory_issues = Column(JSON)  # [{date, issue, status}]
    competitive_position = Column(Text)  # Current competitive standing
    
    # News Metadata
    total_articles_processed = Column(Integer, default=0)
    last_significant_update = Column(DateTime)  # When summary was last materially updated
    last_article_processed = Column(DateTime)  # Last time articles were checked
    articles_since_update = Column(Integer, default=0)  # How many articles read since last update
    
    # Summary Text (LLM Generated)
    company_summary = Column(Text)  # Comprehensive company summary
    recent_developments_summary = Column(Text)  # What's new in last 30 days
    outlook = Column(Text)  # Forward-looking outlook
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StockArticle(Base):
    """Individual stock news articles - similar to MarketArticle but for company-specific news"""
    __tablename__ = "stock_articles"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    
    # Article Info
    url = Column(String(500), nullable=False, unique=True)
    title = Column(String(500), nullable=False)
    source = Column(String(100))
    published_at = Column(DateTime, nullable=False, index=True)
    
    # Content
    full_text = Column(Text)  # Full article text from newspaper3k
    summary = Column(Text)  # LLM-generated summary
    
    # LLM Analysis
    is_significant = Column(Boolean, default=False)  # Is this earnings/major news?
    significance_score = Column(Float)  # 0-1
    article_type = Column(String(50))  # 'earnings', 'product', 'management', 'regulatory', 'general'
    key_points = Column(JSON)  # LLM-extracted key points
    sentiment_score = Column(Float)  # -1 to 1
    
    # Processing
    was_used_in_summary_update = Column(Boolean, default=False)  # Did this trigger a summary update?
    processed_at = Column(DateTime)
    
    created_at = Column(DateTime, default=datetime.utcnow)


class SP500Stock(Base):
    """S&P 500 stock list for batch analysis tracking"""
    __tablename__ = "sp500_stocks"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), unique=True, nullable=False, index=True)
    company_name = Column(String(255))
    sector = Column(String(100))
    is_active = Column(Boolean, default=True)
    added_at = Column(DateTime, default=datetime.utcnow)
    last_analyzed_at = Column(DateTime)
    analysis_status = Column(String(50), default='pending', index=True)  # pending, analyzing, completed, failed


class StockOpportunity(Base):
    """Hourly scan results for stock opportunities"""
    __tablename__ = "stock_opportunities"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    company_name = Column(String(255))
    sector = Column(String(100), index=True)
    scan_date = Column(DateTime, default=datetime.utcnow, index=True)
    current_price = Column(Float, nullable=False)
    fair_value_price = Column(Float)
    buy_below = Column(Float)
    sell_above = Column(Float)
    
    # Opportunity metrics
    buy_opportunity_pct = Column(Float)  # (buy_below - current_price) / current_price * 100
    sell_urgency_pct = Column(Float)  # (current_price - sell_above) / sell_above * 100
    distance_from_fair_pct = Column(Float)  # (current_price - fair_value) / fair_value * 100
    
    # Movement metrics
    price_change_1d = Column(Float)
    price_change_1w = Column(Float)
    volume_vs_avg = Column(Float)
    
    # Classification
    opportunity_type = Column(String(50), index=True)  # strong_buy, buy, hold, sell, strong_sell
    is_best_buy = Column(Boolean, default=False, index=True)
    is_urgent_sell = Column(Boolean, default=False, index=True)
    is_big_mover = Column(Boolean, default=False, index=True)
    
    valuation_assessment = Column(String(50))
    overall_rating = Column(String(50))


class BatchAnalysisJob(Base):
    """Track batch analysis progress"""
    __tablename__ = "batch_analysis_jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(50), unique=True, nullable=False, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    total_stocks = Column(Integer, nullable=False)
    completed_stocks = Column(Integer, default=0)
    failed_stocks = Column(Integer, default=0)
    status = Column(String(50), default='running', index=True)  # running, completed, failed, cancelled
    error_message = Column(Text)
    initiated_by = Column(String(100))  # user, scheduler, etc. 