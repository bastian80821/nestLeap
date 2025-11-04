-- Add sector and company_name to stock_opportunities table
ALTER TABLE stock_opportunities
ADD COLUMN IF NOT EXISTS company_name VARCHAR(255),
ADD COLUMN IF NOT EXISTS sector VARCHAR(100);

-- Create index on sector for faster queries
CREATE INDEX IF NOT EXISTS idx_stock_opportunities_sector ON stock_opportunities(sector);

-- Backfill sector data from sp500_stocks
UPDATE stock_opportunities so
SET 
    sector = sp.sector,
    company_name = sp.company_name
FROM sp500_stocks sp
WHERE so.ticker = sp.ticker;

