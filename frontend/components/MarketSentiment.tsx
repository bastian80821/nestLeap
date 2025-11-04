'use client';

import React, { useEffect, useState } from 'react';
import { TrendingUp, TrendingDown, Minus, Brain, Clock, AlertTriangle, AlertCircle } from 'lucide-react';

interface MarketIndicator {
  value: number;
  change_pct: number;
  timestamp: string;
  data_source: string;
}

interface FearGreedIndex {
  value: number;
  label: string;
  source: string;
  timestamp: string;
}

interface AgentAnalysis {
  analysis_date: string;
  sentiment_assessment: string;
  sentiment_score: number;  // 1-10 scale
  explanation: string;
  outlook: string;
  volatility_environment: string;
  agent_id: string;
}

interface MarketSentimentData {
  current_indicators: {
    sp500?: MarketIndicator;
    nasdaq?: MarketIndicator;
    vix?: MarketIndicator;
  };
  fear_greed_index?: FearGreedIndex;
  agent_analysis: AgentAnalysis;
  timestamp: string;
  data_sources: Record<string, string>;
}

const MarketSentiment: React.FC = () => {
  const [sentimentData, setSentimentData] = useState<MarketSentimentData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [errorDetails, setErrorDetails] = useState<any>(null);

  useEffect(() => {
    fetchSentimentData();
    const interval = setInterval(fetchSentimentData, 60000); // Update every 60s
    return () => clearInterval(interval);
  }, []);

  const fetchSentimentData = async () => {
    try {
      setLoading(true);
      setError(null);
      setErrorDetails(null);
      
      const response = await fetch('/api/market-sentiment/enhanced');
      const data = await response.json();
      
      if (!response.ok) {
        throw new Error(data.detail || 'Failed to fetch market sentiment data');
      }
      
      // Check if the response indicates an error from the agent
      if (data.success === false) {
        setError(data.error || 'Market sentiment analysis failed');
        setErrorDetails({
          error_type: data.error_type,
          message: data.message,
          timestamp: data.timestamp,
          agent_id: data.agent_id
        });
        return;
      }
      
      setSentimentData(data);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'An unexpected error occurred';
      setError(errorMessage);
      console.error('Error fetching sentiment data:', err);
    } finally {
      setLoading(false);
    }
  };

  const getSentimentColor = (score: number) => {
    if (score >= 8) return 'text-green-700 dark:text-green-400';      // 8-10: Extremely Bullish
    if (score >= 7) return 'text-green-600 dark:text-green-500';      // 7-8: Bullish  
    if (score >= 6) return 'text-green-500 dark:text-green-600';      // 6-7: Mildly Bullish
    if (score >= 5) return 'text-yellow-600 dark:text-yellow-400';    // 5-6: Neutral
    if (score >= 4) return 'text-orange-600 dark:text-orange-500';    // 4-5: Mildly Bearish
    if (score >= 3) return 'text-red-600 dark:text-red-500';          // 3-4: Bearish
    return 'text-red-700 dark:text-red-400';                          // 1-3: Extremely Bearish
  };

  const getSentimentBgColor = (score: number) => {
    if (score >= 8) return 'bg-green-100 dark:bg-green-900/20';
    if (score >= 7) return 'bg-green-50 dark:bg-green-900/10';
    if (score >= 6) return 'bg-green-25 dark:bg-green-900/5';
    if (score >= 5) return 'bg-yellow-50 dark:bg-yellow-900/10';
    if (score >= 4) return 'bg-orange-50 dark:bg-orange-900/10';
    if (score >= 3) return 'bg-red-50 dark:bg-red-900/10';
    return 'bg-red-100 dark:bg-red-900/20';
  };

  const getSentimentIcon = (score: number) => {
    if (score >= 7) return <TrendingUp className="w-6 h-6" />;
    if (score >= 5) return null; // No icon for neutral sentiment
    return <TrendingDown className="w-6 h-6" />;
  };

  const getSentimentLabel = (score: number) => {
    if (score >= 8.5) return 'Extremely Bullish';
    if (score >= 7.5) return 'Bullish';
    if (score >= 6.5) return 'Mildly Bullish';
    if (score >= 5.5) return 'Neutral';
    if (score >= 4.5) return 'Mildly Bearish';
    if (score >= 2.5) return 'Bearish';
    return 'Extremely Bearish';
  };

  const getFearGreedColor = (value: number) => {
    if (value < 25) return 'text-red-600 dark:text-red-400';
    if (value < 45) return 'text-orange-600 dark:text-orange-400';
    if (value < 55) return 'text-yellow-600 dark:text-yellow-400';
    if (value < 75) return 'text-green-600 dark:text-green-400';
    return 'text-green-700 dark:text-green-300';
  };

  if (loading) return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow-lg">
      <div className="animate-pulse">
        <div className="h-6 bg-gray-200 dark:bg-gray-700 rounded w-1/3 mb-4"></div>
        <div className="h-16 bg-gray-200 dark:bg-gray-700 rounded mb-4"></div>
        <div className="h-32 bg-gray-200 dark:bg-gray-700 rounded mb-4"></div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="h-20 bg-gray-200 dark:bg-gray-700 rounded"></div>
          <div className="h-20 bg-gray-200 dark:bg-gray-700 rounded"></div>
          <div className="h-20 bg-gray-200 dark:bg-gray-700 rounded"></div>
          <div className="h-20 bg-gray-200 dark:bg-gray-700 rounded"></div>
        </div>
      </div>
    </div>
  );

  if (error) {
      return (
          <div className="bg-white dark:bg-gray-800 p-6 rounded-xl shadow-sm">
              <div className="flex items-center justify-between mb-4">
                  <h2 className="text-xl font-bold text-gray-800 dark:text-white">Momentum</h2>
                  <button
                      onClick={fetchSentimentData}
                      disabled={loading}
                      className="px-3 py-1 text-xs bg-blue-100 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 rounded-lg hover:bg-blue-200 dark:hover:bg-blue-900/40 transition-colors disabled:opacity-50 flex items-center gap-1"
                  >
                      {loading ? 'Retrying...' : 'Retry'}
                  </button>
              </div>
              
              <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-2">
                      <AlertCircle className="w-5 h-5 text-red-500" />
                      <h3 className="font-semibold text-red-700 dark:text-red-400">
                          Market Sentiment Analysis Error
                      </h3>
                  </div>
                  
                  <p className="text-red-600 dark:text-red-300 mb-3">
                      {error}
                  </p>
                  
                  {errorDetails && (
                      <details className="mt-3">
                          <summary className="cursor-pointer text-sm text-red-500 hover:text-red-600">
                              Technical Details
                          </summary>
                          <div className="mt-2 p-3 bg-red-100 dark:bg-red-900/30 rounded text-xs font-mono">
                              <div><strong>Error Type:</strong> {errorDetails.error_type}</div>
                              <div><strong>Agent ID:</strong> {errorDetails.agent_id}</div>
                              <div><strong>Timestamp:</strong> {errorDetails.timestamp}</div>
                              {errorDetails.message && (
                                  <div><strong>Message:</strong> {errorDetails.message}</div>
                              )}
                              {errorDetails.data_collection && (
                                  <div className="mt-2">
                                      <strong>Data Collection:</strong>
                                      <pre className="mt-1 whitespace-pre-wrap">
                                          {JSON.stringify(errorDetails.data_collection, null, 2)}
                                      </pre>
                                  </div>
                              )}
                          </div>
                      </details>
                  )}
              </div>
          </div>
      );
  }

  if (!sentimentData || !sentimentData.agent_analysis) return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow-lg">
      <div className="text-center py-8">
        <h3 className="text-lg font-medium text-gray-700 dark:text-gray-300">
          No market sentiment analysis available
        </h3>
      </div>
    </div>
  );

  const { agent_analysis, current_indicators, fear_greed_index } = sentimentData;
  const hasAnalysisError = agent_analysis.explanation === "No agent analysis available" || !agent_analysis.explanation;

  return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow-lg">
      {/* Header */}
      <div className="mb-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
          MOMENTUM
        </h2>
      </div>

      {/* Main Sentiment Display with 1-10 Score */}
      {!hasAnalysisError && (
        <div className={`${getSentimentBgColor(agent_analysis.sentiment_score)} p-6 rounded-lg mb-6`}>
          <div className="text-center">
            <div className={`text-4xl font-bold ${getSentimentColor(agent_analysis.sentiment_score)} flex items-center justify-center gap-3`}>
              {getSentimentIcon(agent_analysis.sentiment_score)}
              <span className="text-5xl">{agent_analysis.sentiment_score.toFixed(1)}</span>
              <span className="text-lg self-end">/10</span>
            </div>
            <div className={`text-xl font-medium ${getSentimentColor(agent_analysis.sentiment_score)} mt-2`}>
              {getSentimentLabel(agent_analysis.sentiment_score)}
            </div>
          </div>
        </div>
      )}

      {/* Market Indicators Grid - 4 Equal Boxes */}
      <div className="mb-6">
        <h4 className="font-semibold text-gray-700 dark:text-gray-300 mb-3">Market Indicators</h4>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          
          {/* S&P 500 */}
          {current_indicators.sp500 && (
            <div className="bg-gray-50 dark:bg-gray-700 p-4 rounded-lg">
              <div className="text-xs text-gray-600 dark:text-gray-400 mb-1">S&P 500 5d</div>
              <div className="text-lg font-bold text-gray-800 dark:text-white">
                {current_indicators.sp500.value.toFixed(2)}
              </div>
              <div className={`text-xs ${current_indicators.sp500.change_pct >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                {current_indicators.sp500.change_pct >= 0 ? '+' : ''}{Math.abs(current_indicators.sp500.change_pct).toFixed(2)}%
              </div>
            </div>
          )}

          {/* NASDAQ */}
          {current_indicators.nasdaq && (
            <div className="bg-gray-50 dark:bg-gray-700 p-4 rounded-lg">
              <div className="text-xs text-gray-600 dark:text-gray-400 mb-1">NASDAQ 5d</div>
              <div className="text-lg font-bold text-gray-800 dark:text-white">
                {current_indicators.nasdaq.value.toFixed(2)}
              </div>
              <div className={`text-xs ${current_indicators.nasdaq.change_pct >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                {current_indicators.nasdaq.change_pct >= 0 ? '+' : ''}{Math.abs(current_indicators.nasdaq.change_pct).toFixed(2)}%
              </div>
            </div>
          )}

          {/* VIX */}
          {current_indicators.vix && (
            <div className="bg-gray-50 dark:bg-gray-700 p-4 rounded-lg">
              <div className="text-xs text-gray-600 dark:text-gray-400 mb-1">VIX 5d</div>
              <div className="text-lg font-bold text-gray-800 dark:text-white">
                {current_indicators.vix.value.toFixed(2)}
              </div>
              <div className={`text-xs ${current_indicators.vix.change_pct >= 0 ? 'text-red-600' : 'text-green-600'}`}>
                {current_indicators.vix.change_pct >= 0 ? '+' : ''}{Math.abs(current_indicators.vix.change_pct).toFixed(2)}%
              </div>
            </div>
          )}

          {/* Fear & Greed Index */}
          {fear_greed_index && (
            <div className="bg-gray-50 dark:bg-gray-700 p-4 rounded-lg">
              <div className="text-xs text-gray-600 dark:text-gray-400 mb-1">Fear & Greed</div>
              <div className={`text-lg font-bold ${getFearGreedColor(fear_greed_index.value)}`}>
                {fear_greed_index.value}
              </div>
              <div className={`text-xs ${getFearGreedColor(fear_greed_index.value)}`}>
                {fear_greed_index.label}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Agent Analysis */}
      {!hasAnalysisError ? (
        <>
          {/* Market Analysis */}
          {agent_analysis.explanation && (
            <div className="mb-6">
              <h4 className="font-semibold text-gray-700 dark:text-gray-300 mb-3">Market Analysis</h4>
              <div className="p-4 bg-gray-50 dark:bg-gray-700 rounded-lg">
                <p className="text-gray-700 dark:text-gray-300 text-sm leading-relaxed">
                  {agent_analysis.explanation}
                </p>
              </div>
            </div>
          )}

          {/* Outlook */}
          {agent_analysis.outlook && (
            <div className="mb-6">
              <h4 className="font-semibold text-gray-700 dark:text-gray-300 mb-3">Outlook</h4>
              <div className="p-4 bg-gray-50 dark:bg-gray-700 rounded-lg">
                <p className="text-gray-700 dark:text-gray-300 text-sm leading-relaxed">
                  {agent_analysis.outlook}
                </p>
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="mb-6 p-4 bg-orange-50 dark:bg-orange-900/20 rounded-lg">
          <h4 className="font-semibold text-orange-700 dark:text-orange-300 mb-2">Analysis Not Available</h4>
          <p className="text-orange-600 dark:text-orange-400 text-sm">
            Market sentiment analysis is not available. Data will be updated automatically.
          </p>
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between pt-4 border-t dark:border-gray-600">
        <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
          <Clock className="w-3 h-3" />
          <span>Updated: {new Date(sentimentData.timestamp).toLocaleString()}</span>
        </div>
      </div>
    </div>
  );
};

export default MarketSentiment; 