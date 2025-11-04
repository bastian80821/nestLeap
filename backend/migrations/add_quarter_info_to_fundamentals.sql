-- Add quarter information fields to stock_fundamentals_analysis table
-- This tracks which quarter the growth metrics are from

ALTER TABLE stock_fundamentals_analysis 
ADD COLUMN IF NOT EXISTS latest_quarter_date VARCHAR(20),
ADD COLUMN IF NOT EXISTS latest_quarter_label VARCHAR(10),
ADD COLUMN IF NOT EXISTS latest_eps FLOAT;

-- Add comment explaining the fields
COMMENT ON COLUMN stock_fundamentals_analysis.latest_quarter_date IS 'Date of the latest quarter data (YYYY-MM-DD)';
COMMENT ON COLUMN stock_fundamentals_analysis.latest_quarter_label IS 'Quarter label (Q1, Q2, Q3, Q4)';
COMMENT ON COLUMN stock_fundamentals_analysis.latest_eps IS 'EPS from the latest quarter';

