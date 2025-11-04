-- Migration: Add comprehensive company news tables
-- Date: 2025-11-02
-- Description: Adds CompanyNewsSummary, StockArticle tables and new fields to StockNewsAnalysis

-- Create CompanyNewsSummary table
CREATE TABLE IF NOT EXISTS company_news_summaries (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL UNIQUE,
    
    -- Company Overview
    company_name VARCHAR(255),
    sector VARCHAR(100),
    
    -- Latest Earnings
    latest_earnings_date DATE,
    latest_earnings_result VARCHAR(50),
    latest_earnings_summary TEXT,
    eps_actual FLOAT,
    eps_expected FLOAT,
    revenue_actual FLOAT,
    revenue_expected FLOAT,
    guidance TEXT,
    
    -- Persistent Company Profile
    key_risks JSONB,
    key_opportunities JSONB,
    recent_product_developments JSONB,
    management_changes JSONB,
    regulatory_issues JSONB,
    competitive_position TEXT,
    
    -- News Metadata
    total_articles_processed INTEGER DEFAULT 0,
    last_significant_update TIMESTAMP,
    last_article_processed TIMESTAMP,
    articles_since_update INTEGER DEFAULT 0,
    
    -- Summary Text
    company_summary TEXT,
    recent_developments_summary TEXT,
    outlook TEXT,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_company_news_summaries_ticker ON company_news_summaries(ticker);

-- Create StockArticle table
CREATE TABLE IF NOT EXISTS stock_articles (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    
    -- Article Info
    url VARCHAR(500) NOT NULL UNIQUE,
    title VARCHAR(500) NOT NULL,
    source VARCHAR(100),
    published_at TIMESTAMP NOT NULL,
    
    -- Content
    full_text TEXT,
    summary TEXT,
    
    -- LLM Analysis
    is_significant BOOLEAN DEFAULT FALSE,
    significance_score FLOAT,
    article_type VARCHAR(50),
    key_points JSONB,
    sentiment_score FLOAT,
    
    -- Processing
    was_used_in_summary_update BOOLEAN DEFAULT FALSE,
    processed_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_stock_articles_ticker ON stock_articles(ticker);
CREATE INDEX idx_stock_articles_published_at ON stock_articles(published_at);
CREATE INDEX idx_stock_articles_url ON stock_articles(url);

-- Add new columns to stock_news_analysis
ALTER TABLE stock_news_analysis ADD COLUMN IF NOT EXISTS company_summary TEXT;
ALTER TABLE stock_news_analysis ADD COLUMN IF NOT EXISTS recent_developments_summary TEXT;
ALTER TABLE stock_news_analysis ADD COLUMN IF NOT EXISTS outlook TEXT;

ALTER TABLE stock_news_analysis ADD COLUMN IF NOT EXISTS latest_earnings_date DATE;
ALTER TABLE stock_news_analysis ADD COLUMN IF NOT EXISTS latest_earnings_result VARCHAR(50);
ALTER TABLE stock_news_analysis ADD COLUMN IF NOT EXISTS latest_earnings_summary TEXT;
ALTER TABLE stock_news_analysis ADD COLUMN IF NOT EXISTS eps_actual FLOAT;
ALTER TABLE stock_news_analysis ADD COLUMN IF NOT EXISTS eps_expected FLOAT;

ALTER TABLE stock_news_analysis ADD COLUMN IF NOT EXISTS key_risks JSONB;
ALTER TABLE stock_news_analysis ADD COLUMN IF NOT EXISTS key_opportunities JSONB;
ALTER TABLE stock_news_analysis ADD COLUMN IF NOT EXISTS recent_product_developments JSONB;
ALTER TABLE stock_news_analysis ADD COLUMN IF NOT EXISTS management_changes JSONB;
ALTER TABLE stock_news_analysis ADD COLUMN IF NOT EXISTS regulatory_issues JSONB;
ALTER TABLE stock_news_analysis ADD COLUMN IF NOT EXISTS competitive_position TEXT;

ALTER TABLE stock_news_analysis ADD COLUMN IF NOT EXISTS last_significant_update TIMESTAMP;

-- Add comment
COMMENT ON TABLE company_news_summaries IS 'Persistent company news summaries - maintained incrementally like market news';
COMMENT ON TABLE stock_articles IS 'Individual stock news articles with full content and LLM analysis';

