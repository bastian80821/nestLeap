import React from 'react';
import { TrendingUp, TrendingDown, Minus, AlertTriangle, Shield, Clock, DollarSign } from 'lucide-react';
import { StockAnalysis } from '@/types';
import { formatDistanceToNow } from 'date-fns';

interface StockCardProps {
  stock: StockAnalysis;
}

const StockCard: React.FC<StockCardProps> = ({ stock }) => {
  const recommendation = stock.recommendation;
  
  if (!recommendation) {
    return (
      <div className="bg-white dark:bg-black-700 rounded-xl shadow-sm border border-neutral-200 dark:border-black-500 p-6">
        <div className="text-center py-8">
          <AlertTriangle className="w-12 h-12 text-neutral-400 dark:text-neutral-500 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-neutral-600 dark:text-neutral-300">No Recommendation Available</h3>
          <p className="text-neutral-500 dark:text-neutral-400">Unable to generate analysis for this stock.</p>
        </div>
      </div>
    );
  }

  const getActionColor = (action: string) => {
    switch (action) {
      case 'BUY':
        return {
          bg: 'bg-success-50 dark:bg-success-900/20',
          border: 'border-success-200 dark:border-success-800',
          text: 'text-success-700 dark:text-success-400',
          icon: TrendingUp,
          badge: 'badge-buy'
        };
      case 'SELL':
        return {
          bg: 'bg-danger-50 dark:bg-danger-900/20',
          border: 'border-danger-200 dark:border-danger-800',
          text: 'text-danger-700 dark:text-danger-400',
          icon: TrendingDown,
          badge: 'badge-sell'
        };
      default: // HOLD
        return {
          bg: 'bg-warning-50 dark:bg-warning-900/20',
          border: 'border-warning-200 dark:border-warning-800',
          text: 'text-warning-700 dark:text-warning-400',
          icon: Minus,
          badge: 'badge-hold'
        };
    }
  };

  const getRiskColor = (risk: string) => {
    switch (risk) {
      case 'low':
        return 'text-success-600 dark:text-success-400';
      case 'high':
        return 'text-danger-600 dark:text-danger-400';
      default:
        return 'text-warning-600 dark:text-warning-400';
    }
  };

  const formatPrice = (price?: number) => {
    if (!price) return 'N/A';
    return `$${price.toFixed(2)}`;
  };

  const formatPercentage = (value?: number) => {
    if (value === undefined || value === null) return 'N/A';
    const sign = value >= 0 ? '+' : '';
    return `${sign}${(value * 100).toFixed(1)}%`;
  };

  const actionConfig = getActionColor(recommendation.action);
  const ActionIcon = actionConfig.icon;

  return (
    <div className="bg-white dark:bg-black-700 rounded-xl shadow-sm border border-neutral-200 dark:border-black-500 overflow-hidden">
      {/* Header */}
      <div className={`p-6 ${actionConfig.bg} ${actionConfig.border} border-b dark:border-black-500`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <div className="flex items-center space-x-2">
              <h2 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">{stock.ticker}</h2>
              <span className={`px-3 py-1 rounded-full text-sm font-medium ${actionConfig.badge}`}>
                <ActionIcon className="w-4 h-4 inline mr-1" />
                {recommendation.action}
              </span>
            </div>
          </div>
          
          <div className="text-right">
            <div className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">
              {Math.round(recommendation.confidence_score * 100)}%
            </div>
            <div className="text-sm text-neutral-600 dark:text-neutral-400">Confidence</div>
          </div>
        </div>
        
        <div className="mt-4">
          <h3 className="text-lg font-medium text-neutral-800 dark:text-neutral-200 mb-1">{stock.company_name}</h3>
          <p className={`text-sm ${actionConfig.text} font-medium`}>
            {recommendation.reasoning}
          </p>
        </div>
      </div>

      {/* Content */}
      <div className="p-6">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Price Ranges */}
          <div className="space-y-4">
            <h4 className="font-semibold text-neutral-900 dark:text-neutral-100 flex items-center">
              <DollarSign className="w-4 h-4 mr-2 text-neutral-600 dark:text-neutral-400" />
              Price Ranges
            </h4>
            
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-sm text-neutral-600 dark:text-neutral-400">Current Price</span>
                <span className="font-medium text-neutral-900 dark:text-neutral-100">{formatPrice(stock.current_price)}</span>
              </div>
              
              <div className="flex justify-between items-center p-3 bg-success-50 dark:bg-success-900/20 rounded-lg">
                <span className="text-sm font-medium text-success-800 dark:text-success-400">Buy Range</span>
                <span className="text-sm font-bold text-success-900 dark:text-success-300">
                  {formatPrice(recommendation.buy_range_low)} - {formatPrice(recommendation.buy_range_high)}
                </span>
              </div>
              
              <div className="flex justify-between items-center p-3 bg-danger-50 dark:bg-danger-900/20 rounded-lg">
                <span className="text-sm font-medium text-danger-800 dark:text-danger-400">Sell Range</span>
                <span className="text-sm font-bold text-danger-900 dark:text-danger-300">
                  {formatPrice(recommendation.sell_range_low)} - {formatPrice(recommendation.sell_range_high)}
                </span>
              </div>
              </div>
            </div>

            {/* Risk Assessment */}
          <div className="space-y-4">
            <h4 className="font-semibold text-neutral-900 dark:text-neutral-100 flex items-center">
              <Shield className="w-4 h-4 mr-2 text-neutral-600 dark:text-neutral-400" />
              Risk Assessment
            </h4>
            
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-sm text-neutral-600 dark:text-neutral-400">Risk Level</span>
                <span className={`font-medium capitalize ${getRiskColor(recommendation.risk_level)}`}>
                  {recommendation.risk_level}
                </span>
              </div>
              
              <div className="flex justify-between items-center">
                <span className="text-sm text-neutral-600 dark:text-neutral-400">Volatility</span>
                <span className="font-medium text-neutral-900 dark:text-neutral-100">
                  {Math.round(recommendation.volatility_score * 100)}%
                </span>
              </div>
              
              <div className="flex justify-between items-center">
                <span className="text-sm text-neutral-600 dark:text-neutral-400">Confidence</span>
                <span className="font-medium text-neutral-900 dark:text-neutral-100">
                  {Math.round(recommendation.confidence_score * 100)}%
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Analysis Signals */}
        <div className="mt-6">
          <h4 className="font-semibold text-neutral-900 dark:text-neutral-100 mb-4">Analysis Signals</h4>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="flex justify-between items-center">
              <span className="text-sm text-neutral-600 dark:text-neutral-400">Valuation</span>
                <div className="flex items-center space-x-2">
                <div className={`w-16 h-2 rounded-full bg-neutral-200 dark:bg-black-600 overflow-hidden`}>
                    <div 
                      className={`h-full ${recommendation.valuation_signal >= 0 ? 'bg-success-500' : 'bg-danger-500'}`}
                      style={{ width: `${Math.abs(recommendation.valuation_signal) * 50 + 50}%` }}
                    />
                  </div>
                <span className="text-sm font-medium text-neutral-900 dark:text-neutral-100">
                    {formatPercentage(recommendation.valuation_signal)}
                  </span>
                </div>
              </div>
              
              <div className="flex justify-between items-center">
              <span className="text-sm text-neutral-600 dark:text-neutral-400">Technical</span>
                <div className="flex items-center space-x-2">
                <div className={`w-16 h-2 rounded-full bg-neutral-200 dark:bg-black-600 overflow-hidden`}>
                    <div 
                      className={`h-full ${recommendation.technical_signal >= 0 ? 'bg-success-500' : 'bg-danger-500'}`}
                      style={{ width: `${Math.abs(recommendation.technical_signal) * 50 + 50}%` }}
                    />
                  </div>
                <span className="text-sm font-medium text-neutral-900 dark:text-neutral-100">
                    {formatPercentage(recommendation.technical_signal)}
                  </span>
                </div>
              </div>
              
              <div className="flex justify-between items-center">
              <span className="text-sm text-neutral-600 dark:text-neutral-400">News Sentiment</span>
                <div className="flex items-center space-x-2">
                <div className={`w-16 h-2 rounded-full bg-neutral-200 dark:bg-black-600 overflow-hidden`}>
                    <div 
                      className={`h-full ${recommendation.news_sentiment_signal >= 0 ? 'bg-success-500' : 'bg-danger-500'}`}
                      style={{ width: `${Math.abs(recommendation.news_sentiment_signal) * 50 + 50}%` }}
                    />
                  </div>
                <span className="text-sm font-medium text-neutral-900 dark:text-neutral-100">
                    {formatPercentage(recommendation.news_sentiment_signal)}
                  </span>
              </div>
            </div>
          </div>
        </div>

        {/* Key Factors */}
        {recommendation.key_factors && recommendation.key_factors.length > 0 && (
          <div className="mt-6">
            <h4 className="font-semibold text-neutral-900 dark:text-neutral-100 mb-4">Key Factors</h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {recommendation.key_factors.map((factor, index) => (
                <div key={index} className="flex items-start space-x-2">
                  <div className="w-2 h-2 rounded-full bg-primary-500 mt-2 flex-shrink-0"></div>
                  <span className="text-sm text-neutral-700 dark:text-neutral-300">{factor}</span>
                </div>
            ))}
          </div>
        </div>
        )}

        {/* Recent News */}
        {stock.recent_news.length > 0 && (
          <div className="mt-6">
            <h4 className="font-semibold text-neutral-900 dark:text-neutral-100 mb-4 flex items-center">
              <Clock className="w-4 h-4 mr-2 text-neutral-600 dark:text-neutral-400" />
              Recent News
            </h4>
            <div className="space-y-3">
              {stock.recent_news.slice(0, 3).map((article, index) => (
                <div key={index} className="flex items-start space-x-3 p-3 bg-neutral-50 dark:bg-black-600 rounded-lg">
                  <div className="flex-1">
                    <h5 className="text-sm font-medium text-neutral-900 dark:text-neutral-100 line-clamp-2">
                      {article.title}
                    </h5>
                    <div className="flex items-center space-x-2 mt-1">
                      <span className="text-xs text-neutral-500 dark:text-neutral-400">{article.source}</span>
                      {article.sentiment_label && (
                        <span className={`text-xs px-2 py-0.5 rounded-full ${
                          article.sentiment_label === 'positive' ? 'bg-success-100 dark:bg-success-900 text-success-700 dark:text-success-400' :
                          article.sentiment_label === 'negative' ? 'bg-danger-100 dark:bg-danger-900 text-danger-700 dark:text-danger-400' :
                          'bg-neutral-100 dark:bg-black-500 text-neutral-700 dark:text-neutral-300'
                        }`}>
                          {article.sentiment_label}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Analysis Date */}
        <div className="mt-6 pt-4 border-t border-neutral-200 dark:border-black-500">
          <div className="flex items-center text-sm text-neutral-500 dark:text-neutral-400">
            <Clock className="w-4 h-4 mr-2" />
            Analysis updated {formatDistanceToNow(new Date(recommendation.created_at), { addSuffix: true })}
          </div>
        </div>
      </div>
    </div>
  );
};

export default StockCard; 