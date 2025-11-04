-- Migration: Add tables for S&P 500 tracking and opportunities

-- Table: sp500_stocks - List of S&P 500 stocks
CREATE TABLE IF NOT EXISTS sp500_stocks (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) UNIQUE NOT NULL,
    company_name VARCHAR(255),
    sector VARCHAR(100),
    is_active BOOLEAN DEFAULT true,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_analyzed_at TIMESTAMP,
    analysis_status VARCHAR(50) DEFAULT 'pending' -- pending, analyzing, completed, failed
);

CREATE INDEX idx_sp500_ticker ON sp500_stocks(ticker);
CREATE INDEX idx_sp500_status ON sp500_stocks(analysis_status);
CREATE INDEX idx_sp500_last_analyzed ON sp500_stocks(last_analyzed_at);

-- Table: stock_opportunities - Daily scan results
CREATE TABLE IF NOT EXISTS stock_opportunities (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    scan_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    current_price FLOAT NOT NULL,
    fair_value_price FLOAT,
    buy_below FLOAT,
    sell_above FLOAT,
    
    -- Opportunity metrics
    buy_opportunity_pct FLOAT, -- (buy_below - current_price) / current_price * 100
    sell_urgency_pct FLOAT, -- (current_price - sell_above) / sell_above * 100
    distance_from_fair_pct FLOAT, -- (current_price - fair_value) / fair_value * 100
    
    -- Movement metrics
    price_change_1d FLOAT,
    price_change_1w FLOAT,
    volume_vs_avg FLOAT,
    
    -- Classification
    opportunity_type VARCHAR(50), -- strong_buy, buy, hold, sell, strong_sell
    is_best_buy BOOLEAN DEFAULT false,
    is_urgent_sell BOOLEAN DEFAULT false,
    is_big_mover BOOLEAN DEFAULT false,
    
    valuation_assessment VARCHAR(50),
    overall_rating VARCHAR(50),
    
    UNIQUE(ticker, scan_date)
);

CREATE INDEX idx_opportunities_ticker ON stock_opportunities(ticker);
CREATE INDEX idx_opportunities_scan_date ON stock_opportunities(scan_date);
CREATE INDEX idx_opportunities_best_buy ON stock_opportunities(is_best_buy) WHERE is_best_buy = true;
CREATE INDEX idx_opportunities_urgent_sell ON stock_opportunities(is_urgent_sell) WHERE is_urgent_sell = true;
CREATE INDEX idx_opportunities_mover ON stock_opportunities(is_big_mover) WHERE is_big_mover = true;
CREATE INDEX idx_opportunities_type ON stock_opportunities(opportunity_type);

-- Table: batch_analysis_jobs - Track batch analysis progress
CREATE TABLE IF NOT EXISTS batch_analysis_jobs (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(50) UNIQUE NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    total_stocks INTEGER NOT NULL,
    completed_stocks INTEGER DEFAULT 0,
    failed_stocks INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'running', -- running, completed, failed, cancelled
    error_message TEXT,
    initiated_by VARCHAR(100) -- user, scheduler, etc.
);

CREATE INDEX idx_batch_jobs_id ON batch_analysis_jobs(job_id);
CREATE INDEX idx_batch_jobs_status ON batch_analysis_jobs(status);

