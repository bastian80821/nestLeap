'use client';

import React, { useEffect, useState } from 'react';
import { TrendingUp, TrendingDown, DollarSign, Building, AlertCircle, Brain, Clock } from 'lucide-react';
import toast from 'react-hot-toast';

interface EconomicIndicator {
  indicator_name: string;
  value: number;
  reference_date: string;
  unit: string;
  category: string;
  period_type: string;
  market_impact: string;
  period_change_pct: number | null;
  period_desc: string;
  period_change?: number | null;
  period_change_display?: number | null;
  change_type?: string;
}

interface FundamentalsData {
  indicators: EconomicIndicator[];
  summary: string;
  economic_cycle: string;
  monetary_policy: string;
  inflation_trend: string;
  growth_outlook: string;
  market_implications: {
    equities: string;
    bonds: string;
    commodities: string;
    dollar: string;
  };
  agent_intelligence: {
    has_ai_analysis: boolean;
    last_updated: string;
  };
}

const Fundamentals: React.FC = () => {
  const [fundamentalsData, setFundamentalsData] = useState<FundamentalsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 300000); // Update every 5 minutes  
    return () => clearInterval(interval);
  }, []);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await fetch('/api/fundamentals/enhanced');
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      setFundamentalsData(data);
    } catch (err) {
      console.error('Error fetching fundamentals data:', err);
      setError(`Failed to load fundamentals data: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setLoading(false);
    }
  };

  if (loading) return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow-lg">
      <div className="animate-pulse">
        <div className="h-6 bg-gray-200 dark:bg-gray-700 rounded w-1/3 mb-4"></div>
        <div className="grid grid-cols-2 gap-4 mb-6">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-24 bg-gray-200 dark:bg-gray-700 rounded"></div>
          ))}
        </div>
        <div className="h-32 bg-gray-200 dark:bg-gray-700 rounded"></div>
      </div>
    </div>
  );

  if (error) return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow-lg">
      <div className="text-center py-8">
        <AlertCircle className="w-12 h-12 text-red-500 mx-auto mb-3" />
        <h3 className="text-lg font-medium text-gray-700 dark:text-gray-300 mb-2">
          Unable to Load Economic Fundamentals
        </h3>
        <p className="text-gray-600 dark:text-gray-400">{error}</p>
      </div>
    </div>
  );

  if (!fundamentalsData) return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow-lg">
      <div className="text-center py-8">
        <h3 className="text-lg font-medium text-gray-700 dark:text-gray-300">
          No economic fundamentals data available
        </h3>
      </div>
    </div>
  );

  const getImplicationIcon = (implication: string) => {
    switch (implication) {
      case 'positive':
      case 'strong':
        return <TrendingUp className="w-4 h-4 text-green-500" />;
      case 'negative':
      case 'weak':
        return <TrendingDown className="w-4 h-4 text-red-500" />;
      default:
        return <div className="w-4 h-4 rounded-full bg-gray-400"></div>;
    }
  };

  const getTrendIcon = (change: number | null) => {
    if (change === null || change === undefined) return null;
    
    if (change > 0.05) {
      return <span className="text-green-500 text-sm">↗</span>;
    } else if (change < -0.05) {
      return <span className="text-red-500 text-sm">↘</span>;
    } else {
      return <span className="text-gray-400 text-sm">→</span>;
    }
  };

  const getTrendColor = (change: number | null) => {
    if (change === null || change === undefined) return 'text-gray-400';
    
    if (change > 0.05) {
      return 'text-green-600 dark:text-green-400';
    } else if (change < -0.05) {
      return 'text-red-600 dark:text-red-400';
    } else {
      return 'text-gray-500 dark:text-gray-400';
    }
  };

  const formatIndicatorValue = (indicator: EconomicIndicator) => {
    // Round treasury yields, industrial production, and inflation to 2 decimal places
    const needsTwoDecimals = [
      '10-Year Treasury Yield',
      'Industrial Production',
      'Inflation (CPI)'
    ];
    
    if (needsTwoDecimals.includes(indicator.indicator_name)) {
      return indicator.value.toFixed(2);
    }
    
    // Default formatting for other indicators
    return indicator.value.toFixed(1);
  };

  const formatTrendDisplay = (indicator: EconomicIndicator) => {
    if (indicator.period_change_display === null || indicator.period_change_display === undefined) {
      return null;
    }

    const value = Math.abs(indicator.period_change_display);
    const sign = indicator.period_change_display >= 0 ? '+' : '-';
    
    if (indicator.change_type === 'percentage_points') {
      return `${sign}${value.toFixed(2)}pp`;
    } else {
      return `${sign}${value.toFixed(2)}%`;
    }
  };

  const getDataRangeInfo = () => {
    if (!fundamentalsData?.indicators?.length) return '';
    
    const dates = fundamentalsData.indicators.map(ind => new Date(ind.reference_date));
    const earliestDate = new Date(Math.min(...dates.map(d => d.getTime())));
    const latestDate = new Date(Math.max(...dates.map(d => d.getTime())));
    
    const yearSpan = latestDate.getFullYear() - earliestDate.getFullYear();
    
    if (yearSpan >= 50) {
      return `${yearSpan}+ years of historical data`;
    } else if (yearSpan >= 10) {
      return `${yearSpan} years of historical data`;
    } else {
      return `data from ${earliestDate.getFullYear()}-${latestDate.getFullYear()}`;
    }
  };

  const getImpactColor = (impact: string) => {
    switch (impact) {
      case 'bullish': return 'bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400';
      case 'bearish': return 'bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400';
      case 'neutral': return 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-400';
      default: return 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-400';
    }
  };

  return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow-lg">

      {/* Analysis Overview */}
      {fundamentalsData.summary && (
        <div className="border border-gray-200 dark:border-gray-600 rounded-lg p-4 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors mb-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              SUMMARY
            </h3>
          </div>
          <p className="text-gray-700 dark:text-gray-300 mb-4 leading-relaxed">
            {fundamentalsData.summary}
          </p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div className="text-center">
              <p className="text-gray-500 dark:text-gray-400">Economic Cycle</p>
              <p className="font-semibold text-gray-900 dark:text-white capitalize">
                {fundamentalsData.economic_cycle?.replace('_', ' ')}
              </p>
            </div>
            <div className="text-center">
              <p className="text-gray-500 dark:text-gray-400">Monetary Policy</p>
              <p className="font-semibold text-gray-900 dark:text-white capitalize">
                {fundamentalsData.monetary_policy}
              </p>
            </div>
            <div className="text-center">
              <p className="text-gray-500 dark:text-gray-400">Inflation Trend</p>
              <p className="font-semibold text-gray-900 dark:text-white capitalize">
                {fundamentalsData.inflation_trend}
              </p>
            </div>
            <div className="text-center">
              <p className="text-gray-500 dark:text-gray-400">Growth Outlook</p>
              <p className="font-semibold text-gray-900 dark:text-white capitalize">
                {fundamentalsData.growth_outlook}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Key Economic Indicators */}
      <div className="mb-6">
        <h4 className="font-semibold text-gray-700 dark:text-gray-300 mb-3">Key Economic Indicators</h4>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {fundamentalsData.indicators.map((indicator, index) => (
            <div key={index} className="border border-gray-200 dark:border-gray-600 rounded-lg p-4">
              <div className="flex items-center justify-between mb-2">
                <h5 className="font-medium text-gray-800 dark:text-white">{indicator.indicator_name}</h5>
                <span className={`px-2 py-1 rounded text-xs font-medium ${getImpactColor(indicator.market_impact)}`}>
                  {indicator.market_impact.toUpperCase()}
                </span>
              </div>
              
              <div className="flex items-baseline gap-2 mb-2">
                <span className="text-2xl font-bold text-gray-800 dark:text-white">
                  {formatIndicatorValue(indicator)}
                </span>
                <span className="text-sm text-gray-500 dark:text-gray-400">
                  {indicator.unit}
                </span>
                {indicator.period_change_display !== null && indicator.period_change_display !== undefined && (
                  <div className="flex items-center gap-1 ml-2">
                    {getTrendIcon(indicator.period_change_display)}
                    <span className={`text-xs font-medium ${getTrendColor(indicator.period_change_display)}`}>
                      {formatTrendDisplay(indicator)}
                    </span>
                  </div>
                )}
              </div>
              
              <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
                <span>Updated {new Date(indicator.reference_date).toLocaleDateString()}</span>
                <div className="text-right">
                  {indicator.period_change_display !== null && indicator.period_change_display !== undefined && (
                    <div className="text-xs text-gray-400 dark:text-gray-500">
                      {indicator.period_desc}
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between pt-4 border-t dark:border-gray-600">
        <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
          <Clock className="w-3 h-3" />
          <span>Updated: {new Date(fundamentalsData.agent_intelligence.last_updated).toLocaleDateString()}</span>
        </div>
      </div>
    </div>
  );
};

export default Fundamentals; 