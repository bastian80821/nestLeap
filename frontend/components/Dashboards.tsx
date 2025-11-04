'use client';

import React, { useState, useEffect } from 'react';
import { Search, TrendingUp, TrendingDown, Star, Brain, AlertTriangle, Target, Clock, BarChart3, Lightbulb } from 'lucide-react';

interface StockAnalysis {
  ticker: string;
  has_analysis: boolean;
  analysis_date?: string;
  current_price?: number;
  overall_rating?: string;
  confidence_score?: number;
  target_price?: number;
  upside_potential?: number;
  valuation_assessment?: string;
  key_insights?: string[];
  risk_factors?: string[];
  catalysts?: string[];
  why_current_price?: string;
  future_outlook?: string;
  comparison_to_market?: string;
  technical_rating?: string;
  support_level?: number;
  resistance_level?: number;
  agent_confidence?: number;
  
  // News Summary
  company_summary?: string;
  recent_developments?: string;
  outlook?: string;
  latest_earnings?: {
    date?: string;
    result?: string;
    summary?: string;
    eps_actual?: number;
    eps_expected?: number;
  };
  
  // Fundamental Metrics
  pe_ratio?: number;
  forward_pe?: number;
  peg_ratio?: number;
  market_cap?: number;
  revenue_growth?: number;
  earnings_growth?: number;
  profit_margins?: number;
  debt_to_equity?: number;
  return_on_equity?: number;
  valuation_conclusion?: string;
  articles_analyzed?: number;
}

interface Opportunity {
  ticker: string;
  company_name?: string;
  sector?: string;
  current_price: number;
  fair_value_price?: number;
  buy_below?: number;
  sell_above?: number;
  buy_opportunity_pct?: number;
  sell_urgency_pct?: number;
  price_change_1d: number;
  price_change_1w?: number;
  opportunity_type: string;
  valuation_assessment?: string;
}

interface Sector {
  name: string;
  count: number;
}

const Dashboards: React.FC = () => {
  const [ticker, setTicker] = useState('');
  const [analysis, setAnalysis] = useState<StockAnalysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Opportunities state
  const [showOpportunities, setShowOpportunities] = useState(true);
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [selectedSector, setSelectedSector] = useState<string>('');
  const [bestBuys, setBestBuys] = useState<Opportunity[]>([]);
  const [urgentSells, setUrgentSells] = useState<Opportunity[]>([]);
  const [bigMovers, setBigMovers] = useState<Opportunity[]>([]);
  const [opportunitiesLoading, setOpportunitiesLoading] = useState(false);

  const fetchStockAnalysis = async (symbol: string) => {
    try {
      setLoading(true);
      setError(null);
      
      const response = await fetch(`http://localhost:8000/api/stock/${symbol.toUpperCase()}/analysis`);
      const data = await response.json();
      
      console.log('Stock analysis response:', data);
      
      if (data.error) {
        // Show error message (e.g., "Not in S&P 500" or "No analysis available")
        setError(data.error);
      } else if (!data.has_analysis) {
        // No analysis available - don't auto-trigger, just show message
        setError(`No analysis available for ${symbol.toUpperCase()}. Run a batch analysis from the Debug tab to analyze all S&P 500 stocks.`);
      } else {
        setAnalysis(data);
      }
    } catch (err) {
      setError('Failed to fetch stock analysis');
      console.error('Error fetching analysis:', err);
    } finally {
      setLoading(false);
    }
  };

  const triggerAnalysis = async (symbol: string) => {
    try {
      setAnalyzing(true);
      setError(null);
      
      const response = await fetch(`http://localhost:8000/api/stock/${symbol.toUpperCase()}/analyze`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      });
      
      const result = await response.json();
      console.log('Trigger analysis response:', result);
      
      // Check for validation errors (invalid ticker)
      if (result.status === 'error') {
        setError(result.error || 'Failed to trigger analysis');
        setAnalyzing(false);
        return;
      }
      
      if (result.status === 'success' || result.message) {
        // Poll for results every 3 seconds for up to 2 minutes
        let attempts = 0;
        const maxAttempts = 40; // 2 minutes
        
        const pollForResults = async () => {
          attempts++;
          
          if (attempts > maxAttempts) {
            setError('Analysis is taking longer than expected. Please try again later.');
            setAnalyzing(false);
            return;
          }
          
          try {
            const checkResponse = await fetch(`http://localhost:8000/api/stock/${symbol.toUpperCase()}/analysis`);
            const checkData = await checkResponse.json();
            
            // Check if we have actual analysis data (not just an error)
            if (checkData && !checkData.error && checkData.ticker) {
              setAnalysis(checkData);
              setAnalyzing(false);
              setLastRefresh(new Date());
            } else {
              // Continue polling
              setTimeout(pollForResults, 3000);
            }
          } catch (pollError) {
            console.error('Error polling for results:', pollError);
            setTimeout(pollForResults, 3000);
          }
        };
        
        // Start polling after a short delay
        setTimeout(pollForResults, 5000);
      } else {
        setError('Failed to trigger analysis');
        setAnalyzing(false);
      }
    } catch (err) {
      setError('Failed to trigger analysis');
      console.error('Error triggering analysis:', err);
      setAnalyzing(false);
    }
  };

  const fetchSectors = async () => {
    try {
      const response = await fetch('http://localhost:8000/api/stocks/opportunities/sectors');
      const data = await response.json();
      
      if (data.sectors && data.sectors.length > 0) {
        // Sort by stock count and take top 5
        const topSectors = data.sectors.sort((a: Sector, b: Sector) => b.count - a.count).slice(0, 5);
        setSectors(topSectors);
        const firstSector = topSectors[0]?.name || '';
        setSelectedSector(firstSector);
        
        // Fetch opportunities for the first sector immediately
        if (firstSector) {
          fetchOpportunities(firstSector);
        }
      }
    } catch (err) {
      console.error('Error fetching sectors:', err);
    }
  };

  const fetchOpportunities = async (sector?: string) => {
    setOpportunitiesLoading(true);
    try {
      let buysUrl, sellsUrl, moversUrl;
      
      if (sector) {
        // Fetch by sector
        buysUrl = `http://localhost:8000/api/stocks/opportunities/best-buys-by-sector?sector=${encodeURIComponent(sector)}&limit=5`;
        sellsUrl = `http://localhost:8000/api/stocks/opportunities/urgent-sells-by-sector?sector=${encodeURIComponent(sector)}&limit=5`;
        moversUrl = 'http://localhost:8000/api/stocks/opportunities/big-movers?limit=10'; // Global
      } else {
        // Fetch overall
        buysUrl = 'http://localhost:8000/api/stocks/opportunities/best-buys?limit=10';
        sellsUrl = 'http://localhost:8000/api/stocks/opportunities/urgent-sells?limit=10';
        moversUrl = 'http://localhost:8000/api/stocks/opportunities/big-movers?limit=10';
      }
      
      const [buysRes, sellsRes, moversRes] = await Promise.all([
        fetch(buysUrl),
        fetch(sellsUrl),
        fetch(moversUrl)
      ]);
      
      const buys = await buysRes.json();
      const sells = await sellsRes.json();
      const movers = await moversRes.json();
      
      setBestBuys(buys.best_buys || []);
      setUrgentSells(sells.urgent_sells || []);
      setBigMovers(movers.big_movers || []);
    } catch (err) {
      console.error('Error fetching opportunities:', err);
    } finally {
      setOpportunitiesLoading(false);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (ticker.trim()) {
      setShowOpportunities(false);
      fetchStockAnalysis(ticker.trim());
    }
  };
  
  const handleBackToOpportunities = () => {
    setShowOpportunities(true);
    setAnalysis(null);
    setTicker('');
    fetchOpportunities();
  };

  useEffect(() => {
    // Load sectors (which will also load opportunities for the first sector)
    fetchSectors();
    
    // Refresh opportunities every 5 minutes
    const interval = setInterval(() => {
      if (selectedSector) {
        fetchOpportunities(selectedSector);
      }
    }, 300000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    // Fetch opportunities when sector changes
    if (selectedSector) {
      fetchOpportunities(selectedSector);
    }
  }, [selectedSector]);

  const getTechnicalIcon = (rating: string) => {
    switch (rating) {
      case 'Bullish': return <TrendingUp className="w-4 h-4 text-green-500" />;
      case 'Bearish': return <TrendingDown className="w-4 h-4 text-red-500" />;
      default: return <BarChart3 className="w-4 h-4 text-gray-500" />;
    }
  };

    return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow-lg">
      {/* Header with Search */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-gray-800 dark:text-white">Dashboard</h2>
        </div>
        
        {/* Ticker Search */}
        <form onSubmit={handleSearch} className="flex gap-3">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              placeholder="Enter ticker symbol (e.g., MSFT, AAPL, GOOGL)"
              className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg 
                         bg-white dark:bg-gray-700 text-gray-900 dark:text-white
                         focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
            <button
            type="submit"
            disabled={loading || analyzing}
            className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 
                       disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
            {loading ? 'Loading...' : analyzing ? 'Analyzing...' : 'Analyze'}
            </button>
        </form>
      </div>

      {/* Error State */}
      {error && (
        <div className="mb-4 p-4 bg-red-100 dark:bg-red-900/20 border border-red-300 dark:border-red-800 rounded-lg">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 text-red-500" />
            <p className="text-red-700 dark:text-red-400">{error}</p>
          </div>
        </div>
      )}
      
      {/* Opportunities Dashboard (Default View) */}
      {showOpportunities && !analysis && !loading && !analyzing && (
        <div className="space-y-6">
          {/* Sector Tabs */}
          {sectors.length > 0 && (
            <div className="bg-white dark:bg-gray-800 p-4 rounded-lg shadow-md">
              <h3 className="text-lg font-bold text-gray-900 dark:text-white mb-4">Select Sector</h3>
              <div className="flex flex-wrap gap-2">
                {sectors.map((sector) => (
                  <button
                    key={sector.name}
                    onClick={() => setSelectedSector(sector.name)}
                    className={`px-4 py-2 rounded-lg font-medium transition-all ${
                      selectedSector === sector.name
                        ? 'bg-blue-600 text-white shadow-md'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                    }`}
                  >
                    {sector.name}
                    <span className="ml-2 text-xs opacity-75">({sector.count})</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {opportunitiesLoading ? (
            <div className="text-center py-12">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
              <p className="mt-4 text-gray-600 dark:text-gray-400">Loading opportunities...</p>
            </div>
          ) : (
            <>
              {/* Best Buy Opportunities */}
              <div className="bg-green-50 dark:bg-green-900/10 p-6 rounded-lg border border-green-200 dark:border-green-800">
                <h3 className="text-xl font-bold text-green-800 dark:text-green-200 mb-4 flex items-center gap-2">
                  <TrendingUp className="w-6 h-6" />
                  Best Buy Opportunities {selectedSector && `- ${selectedSector}`}
                </h3>
                {bestBuys.length > 0 ? (
                  <div className="space-y-3">
                    {bestBuys.slice(0, 5).map((opp) => (
                      <div
                        key={opp.ticker}
                        onClick={() => {
                          setTicker(opp.ticker);
                          setShowOpportunities(false);
                          fetchStockAnalysis(opp.ticker);
                        }}
                        className="bg-white dark:bg-gray-800 p-4 rounded-lg cursor-pointer hover:shadow-md transition-shadow"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex-1">
                            <div className="font-bold text-lg text-gray-900 dark:text-white">{opp.ticker}</div>
                            <div className="text-sm text-gray-600 dark:text-gray-400">
                              Current: ${opp.current_price?.toFixed(2)} | Strong Buy Below: ${opp.buy_below?.toFixed(2)}
                            </div>
                            {opp.buy_opportunity_pct && (
                              <div className="text-sm font-semibold text-green-600 dark:text-green-400">
                                {opp.buy_opportunity_pct.toFixed(1)}% below buy threshold
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-gray-600 dark:text-gray-400">No opportunities found. Run batch analysis in Debug tab first.</p>
                )}
              </div>

              {/* Urgent Sell Signals */}
              <div className="bg-red-50 dark:bg-red-900/10 p-6 rounded-lg border border-red-200 dark:border-red-800">
                <h3 className="text-xl font-bold text-red-800 dark:text-red-200 mb-4 flex items-center gap-2">
                  <TrendingDown className="w-6 h-6" />
                  Urgent Sell Signals {selectedSector && `- ${selectedSector}`}
                </h3>
                {urgentSells.length > 0 ? (
                  <div className="space-y-3">
                    {urgentSells.slice(0, 5).map((opp) => (
                      <div
                        key={opp.ticker}
                        onClick={() => {
                          setTicker(opp.ticker);
                          setShowOpportunities(false);
                          fetchStockAnalysis(opp.ticker);
                        }}
                        className="bg-white dark:bg-gray-800 p-4 rounded-lg cursor-pointer hover:shadow-md transition-shadow"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex-1">
                            <div className="font-bold text-lg text-gray-900 dark:text-white">{opp.ticker}</div>
                            <div className="text-sm text-gray-600 dark:text-gray-400">
                              Current: ${opp.current_price?.toFixed(2)} | Strong Sell Above: ${opp.sell_above?.toFixed(2)}
                            </div>
                            {opp.sell_urgency_pct && (
                              <div className="text-sm font-semibold text-red-600 dark:text-red-400">
                                {opp.sell_urgency_pct.toFixed(1)}% above sell threshold
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-gray-600 dark:text-gray-400">No urgent sell signals found.</p>
                )}
              </div>

              {/* Biggest Movers */}
              <div className="bg-blue-50 dark:bg-blue-900/10 p-6 rounded-lg border border-blue-200 dark:border-blue-800">
                <h3 className="text-xl font-bold text-blue-800 dark:text-blue-200 mb-4 flex items-center gap-2">
                  <BarChart3 className="w-6 h-6" />
                  Biggest Movers
                </h3>
                {bigMovers.length > 0 ? (
                  <div className="space-y-3">
                    {bigMovers.slice(0, 5).map((opp) => (
                      <div
                        key={opp.ticker}
                        onClick={() => {
                          setTicker(opp.ticker);
                          setShowOpportunities(false);
                          fetchStockAnalysis(opp.ticker);
                        }}
                        className="bg-white dark:bg-gray-800 p-4 rounded-lg cursor-pointer hover:shadow-md transition-shadow"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex-1">
                            <div className="font-bold text-lg text-gray-900 dark:text-white">{opp.ticker}</div>
                            <div className="text-sm text-gray-600 dark:text-gray-400">
                              Current: ${opp.current_price?.toFixed(2)}
                            </div>
                            <div className={`text-sm font-semibold ${opp.price_change_1d >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                              {opp.price_change_1d >= 0 ? '+' : ''}{opp.price_change_1d.toFixed(2)}% today
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-gray-600 dark:text-gray-400">No big movers found.</p>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {/* Loading State */}
      {(loading || analyzing) && (
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full"></div>
          <span className="ml-3 text-gray-600 dark:text-gray-400">
            {analyzing ? 'AI agents analyzing stock... This may take 1-2 minutes.' : 'Loading analysis...'}
          </span>
        </div>
      )}

      {/* No Analysis Available */}
      {!loading && !analyzing && analysis && !analysis.has_analysis && (
        <div className="text-center py-12">
          <Brain className="w-16 h-16 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-700 dark:text-gray-300 mb-2">
            No Analysis Available
          </h3>
          <p className="text-gray-600 dark:text-gray-400 mb-4">
            AI analysis for {analysis.ticker} is not yet available. Our agents will analyze fundamentals, sentiment, news, and market context.
          </p>
          <button
            onClick={() => triggerAnalysis(analysis.ticker)}
            disabled={analyzing}
            className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            Trigger AI Analysis
          </button>
        </div>
      )}

      {/* Analysis Results */}
      {!loading && !analyzing && analysis && analysis.has_analysis && (
        <div className="space-y-6">
          {/* Summary Header */}
          <div className="bg-gray-50 dark:bg-gray-700 p-6 rounded-lg">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-2xl font-bold text-gray-800 dark:text-white">
                  {analysis.ticker}
                </h3>
                <p className="text-gray-600 dark:text-gray-400">
                  ${analysis.current_price?.toFixed(2) || 'N/A'}
                </p>
      </div>
                  </div>

            {/* Key Metrics */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="text-center">
                <div className="text-sm text-gray-600 dark:text-gray-400">Fair Value</div>
                <div className="font-bold text-lg text-gray-800 dark:text-white">
                  ${(analysis.fair_value_price || analysis.target_price)?.toFixed(2) || 'N/A'}
                </div>
              </div>
              
              <div className="text-center">
                <div className="text-sm text-gray-600 dark:text-gray-400">Strong Buy Below</div>
                <div className="font-bold text-lg text-green-600 dark:text-green-400">
                  {analysis.buy_below 
                    ? `$${analysis.buy_below.toFixed(2)}`
                    : 'N/A'}
                </div>
              </div>
              
              <div className="text-center">
                <div className="text-sm text-gray-600 dark:text-gray-400">Strong Sell Above</div>
                <div className="font-bold text-lg text-red-600 dark:text-red-400">
                  {analysis.sell_above 
                    ? `$${analysis.sell_above.toFixed(2)}`
                    : 'N/A'}
                </div>
              </div>
              
              <div className="text-center">
                <div className="text-sm text-gray-600 dark:text-gray-400">Valuation</div>
                <div className={`font-bold text-lg ${
                  analysis.valuation_assessment === 'Undervalued' ? 'text-green-600 dark:text-green-400' :
                  analysis.valuation_assessment === 'Overvalued' ? 'text-red-600 dark:text-red-400' :
                  'text-gray-800 dark:text-white'
                }`}>
                  {analysis.valuation_assessment || 'N/A'}
                </div>
              </div>
            </div>
              </div>
              
          {/* 2. Company Description */}
          {analysis.company_description && (
            <div className="bg-gray-50 dark:bg-gray-700/30 p-6 rounded-lg">
              <h4 className="font-bold text-gray-800 dark:text-white mb-3">
                Company Description
              </h4>
              <p className="text-gray-700 dark:text-gray-300 leading-relaxed">
                {analysis.company_description}
              </p>
            </div>
          )}
          
          {/* 3. Analysis (combines thesis + developments + current price) */}
          {analysis.analysis && (
            <div className="bg-blue-50 dark:bg-blue-900/20 p-6 rounded-lg">
              <h4 className="font-bold text-gray-800 dark:text-white mb-3">
                Analysis
              </h4>
              <p className="text-gray-700 dark:text-gray-300 leading-relaxed">
                {analysis.analysis}
              </p>
            </div>
          )}
          
          {/* 4. Forward Outlook */}
          {analysis.forward_outlook && (
            <div className="bg-green-50 dark:bg-green-900/20 p-6 rounded-lg">
              <h4 className="font-bold text-gray-800 dark:text-white mb-3">
                Forward Outlook
              </h4>
              <p className="text-gray-700 dark:text-gray-300 leading-relaxed">
                {analysis.forward_outlook}
              </p>
            </div>
          )}
          
          {/* 5. Fundamental Indicators */}
          {(analysis.pe_ratio || analysis.revenue_growth || analysis.profit_margins) && (
            <div className="bg-indigo-50 dark:bg-indigo-900/20 p-6 rounded-lg">
              <h4 className="font-bold text-gray-800 dark:text-white mb-4">
                Fundamental Indicators
              </h4>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                {analysis.pe_ratio && (
                  <div className="text-center p-3 bg-white dark:bg-gray-800 rounded-lg">
                    <div className="text-xs text-gray-600 dark:text-gray-400 mb-1">P/E Ratio</div>
                    <div className="font-bold text-xl text-gray-800 dark:text-white">
                      {analysis.pe_ratio.toFixed(1)}
                    </div>
                  </div>
                )}
                {analysis.forward_pe && (
                  <div className="text-center p-3 bg-white dark:bg-gray-800 rounded-lg">
                    <div className="text-xs text-gray-600 dark:text-gray-400 mb-1">Forward P/E</div>
                    <div className="font-bold text-xl text-gray-800 dark:text-white">
                      {analysis.forward_pe.toFixed(1)}
                    </div>
                  </div>
                )}
                {analysis.profit_margins && (
                  <div className="text-center p-3 bg-white dark:bg-gray-800 rounded-lg">
                    <div className="text-xs text-gray-600 dark:text-gray-400 mb-1">Profit Margin</div>
                    <div className="font-bold text-xl text-gray-800 dark:text-white">
                      {analysis.profit_margins.toFixed(1)}%
                    </div>
                  </div>
                )}
                {analysis.revenue_growth && (
                  <div className="text-center p-3 bg-white dark:bg-gray-800 rounded-lg">
                    <div className="text-xs text-gray-600 dark:text-gray-400 mb-1">
                      Revenue Growth {analysis.latest_quarter_label && `(${analysis.latest_quarter_label})`}
                    </div>
                    <div className={`font-bold text-xl ${analysis.revenue_growth > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                      {analysis.revenue_growth.toFixed(1)}%
                    </div>
                  </div>
                )}
                {analysis.earnings_growth && (
                  <div className="text-center p-3 bg-white dark:bg-gray-800 rounded-lg">
                    <div className="text-xs text-gray-600 dark:text-gray-400 mb-1">
                      Earnings Growth {analysis.latest_quarter_label && `(${analysis.latest_quarter_label})`}
                    </div>
                    <div className={`font-bold text-xl ${analysis.earnings_growth > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                      {analysis.earnings_growth.toFixed(1)}%
                    </div>
                  </div>
                )}
                {analysis.debt_to_equity && (
                  <div className="text-center p-3 bg-white dark:bg-gray-800 rounded-lg">
                    <div className="text-xs text-gray-600 dark:text-gray-400 mb-1">Debt/Equity</div>
                    <div className="font-bold text-xl text-gray-800 dark:text-white">
                      {analysis.debt_to_equity.toFixed(1)}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* 6. Risk Factors & Catalysts */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Risk Factors */}
            {analysis.risk_factors && analysis.risk_factors.length > 0 && (
              <div className="bg-yellow-50 dark:bg-yellow-900/20 p-6 rounded-lg">
                <h4 className="font-bold text-gray-800 dark:text-white mb-3 flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5 text-yellow-500" />
                  Risk Factors
                </h4>
                  <ul className="space-y-2">
                  {analysis.risk_factors.map((risk, index) => (
                    <li key={index} className="flex items-start gap-2 text-gray-700 dark:text-gray-300">
                      <span className="w-2 h-2 bg-yellow-500 rounded-full mt-2 flex-shrink-0"></span>
                      {risk}
                      </li>
                    ))}
                  </ul>
                </div>
            )}

            {/* Catalysts */}
            {analysis.catalysts && analysis.catalysts.length > 0 && (
              <div className="bg-green-50 dark:bg-green-900/20 p-6 rounded-lg">
                <h4 className="font-bold text-gray-800 dark:text-white mb-3 flex items-center gap-2">
                  <Star className="w-5 h-5 text-green-500" />
                  Catalysts
                </h4>
                <ul className="space-y-2">
                  {analysis.catalysts.map((catalyst, index) => (
                    <li key={index} className="flex items-start gap-2 text-gray-700 dark:text-gray-300">
                      <span className="w-2 h-2 bg-green-500 rounded-full mt-2 flex-shrink-0"></span>
                      {catalyst}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* 7. Market Comparison */}
          {(analysis.market_comparison || analysis.comparison_to_market) && (
            <div className="bg-purple-50 dark:bg-purple-900/20 p-6 rounded-lg">
              <h4 className="font-bold text-gray-800 dark:text-white mb-3">
                Market Comparison
              </h4>
              <p className="text-gray-700 dark:text-gray-300 leading-relaxed">
                {analysis.market_comparison || analysis.comparison_to_market}
              </p>
            </div>
          )}

          {/* Analysis Timestamp */}
          {analysis.analysis_date && (
            <div className="flex items-center justify-center text-xs text-gray-500 dark:text-gray-400 pt-4 border-t dark:border-gray-600">
              <Clock className="w-3 h-3 mr-1" />
              Analysis updated: {new Date(analysis.analysis_date).toLocaleString()}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default Dashboards; 