'use client';

import React, { useEffect, useState } from 'react';
import { Clock, TrendingUp, TrendingDown, AlertCircle, Newspaper, Brain } from 'lucide-react';
import toast from 'react-hot-toast';

interface NewsArticle {
  title: string;
  summary: string;
  source: string;
  published_at: string;
  url: string;
  market_signal: string;
  key_points: string[];
}

interface MarketNewsData {
  articles: NewsArticle[];
  summary: string;
  sentiment_breakdown: {
    positive: number;
    negative: number;
    neutral: number;
  };
  agent_intelligence?: {
    has_ai_analysis: boolean;
    last_updated: string;
    analysis_quality: string;
  };
}

const MarketNews: React.FC = () => {
  const [newsData, setNewsData] = useState<MarketNewsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 300000); // Update every 5 minutes
    return () => clearInterval(interval);
  }, []);

  const formatRelativeTime = (dateString: string): string => {
    const now = new Date();
    const publishedDate = new Date(dateString);
    const diffInMs = now.getTime() - publishedDate.getTime();
    
    const diffInMinutes = Math.floor(diffInMs / (1000 * 60));
    const diffInHours = Math.floor(diffInMs / (1000 * 60 * 60));
    const diffInDays = Math.floor(diffInMs / (1000 * 60 * 60 * 24));
    
    if (diffInMinutes < 60) {
      return `${diffInMinutes} minutes ago`;
    } else if (diffInHours < 24) {
      return `${diffInHours} hours ago`;
    } else if (diffInDays < 7) {
      return `${diffInDays} days ago`;
    } else {
      return publishedDate.toLocaleDateString();
    }
  };

  const fetchData = async () => {
    try {
      setError(null);
      const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const response = await fetch(`${API_URL}/api/market-news/enhanced`);
      const data = await response.json();
      
      if (data.error) {
        setError(data.error);
      } else {
        setNewsData(data);
      }
      setLoading(false);
    } catch (error) {
      console.error('Error fetching news data:', error);
      setError('Failed to fetch market news data');
      setLoading(false);
    }
  };

  if (loading) return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow-lg">
      <div className="animate-pulse">
        <div className="h-6 bg-gray-200 dark:bg-gray-700 rounded w-1/3 mb-4"></div>
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-24 bg-gray-200 dark:bg-gray-700 rounded"></div>
          ))}
        </div>
      </div>
    </div>
  );

  if (error) return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow-lg">
      <div className="text-center py-8">
        <AlertCircle className="w-12 h-12 text-red-500 mx-auto mb-3" />
        <h3 className="text-lg font-medium text-gray-700 dark:text-gray-300 mb-2">
          Unable to Load Market News
        </h3>
        <p className="text-gray-600 dark:text-gray-400 mb-4">{error}</p>
        <button
          onClick={fetchData}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          Try Again
        </button>
      </div>
    </div>
  );

  if (!newsData) return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow-lg">
      <div className="text-center py-8">
        <h3 className="text-lg font-medium text-gray-700 dark:text-gray-300">
          No market news data available
        </h3>
      </div>
    </div>
  );

  const getSignalIcon = (signal: string) => {
    switch (signal) {
      case 'bullish': return <TrendingUp className="w-4 h-4 text-green-500" />;
      case 'bearish': return <TrendingDown className="w-4 h-4 text-red-500" />;
      default: return <div className="w-4 h-4 rounded-full bg-gray-400"></div>;
    }
  };

  const getSignalColor = (signal: string) => {
    switch (signal) {
      case 'bullish': return 'text-green-600 dark:text-green-400 bg-green-100 dark:bg-green-900/20';
      case 'bearish': return 'text-red-600 dark:text-red-400 bg-red-100 dark:bg-red-900/20';
      default: return 'text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-700';
    }
  };

  const getImpactColor = (level: string) => {
    switch (level) {
      case 'high': return 'bg-orange-100 text-orange-800 dark:bg-orange-900/20 dark:text-orange-400';
      case 'medium': return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/20 dark:text-yellow-400';
      case 'low': return 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-400';
      default: return 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-400';
    }
  };

    return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow-lg">

      {/* Market Summary */}
      {newsData.summary && (
        <div className="border border-gray-200 dark:border-gray-600 rounded-lg p-4 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors mb-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              SUMMARY
            </h3>
          </div>
          <p className="text-gray-700 dark:text-gray-300 leading-relaxed">
            {newsData.summary}
          </p>
          
          {newsData.sentiment_breakdown && (
            <div className="mt-4 flex flex-wrap gap-2 text-sm">
              <span className="px-2 py-1 bg-green-100 dark:bg-green-900/20 text-green-700 dark:text-green-300 rounded">
                {newsData.sentiment_breakdown.positive} Bullish
              </span>
              <span className="px-2 py-1 bg-red-100 dark:bg-red-900/20 text-red-700 dark:text-red-300 rounded">
                {newsData.sentiment_breakdown.negative} Bearish
              </span>
              <span className="px-2 py-1 bg-gray-100 dark:bg-gray-700/20 text-gray-700 dark:text-gray-300 rounded">
                {newsData.sentiment_breakdown.neutral} Neutral
              </span>
            </div>
          )}
        </div>
      )}

      {/* News Articles */}
      <div className="space-y-4">
        {newsData.articles.map((article, index) => (
          <div key={index} className="border border-gray-200 dark:border-gray-600 rounded-lg p-4 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
            {/* Article Header */}
            <div className="flex items-start justify-between mb-3">
              <div className="flex-1">
                <h4 className="font-semibold text-gray-800 dark:text-white mb-1 line-clamp-2">
                  <a 
                    href={article.url} 
                    target="_blank" 
                    rel="noopener noreferrer" 
                    className="hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
                  >
                    {article.title}
                  </a>
                </h4>
                <div className="flex items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
                  <span>{article.source}</span>
                  <span>•</span>
                  <span>{formatRelativeTime(article.published_at)}</span>
                </div>
              </div>
              
              {/* Single Market Signal Indicator */}
              <div className="ml-4">
                <div className={`flex items-center gap-1 px-2 py-1 rounded ${getSignalColor(article.market_signal)}`}>
                  {getSignalIcon(article.market_signal)}
                  <span className="text-xs font-medium capitalize">{article.market_signal}</span>
                </div>
              </div>
            </div>
              
            {/* Article Body - Combines summary and key points without repeating headline */}
            <div className="text-gray-600 dark:text-gray-400 text-sm leading-relaxed">
              {/* Main summary */}
              <p className="mb-2">
                {article.summary}
              </p>
              
              {/* Integrated key points as bullet points */}
              {article.key_points && article.key_points.length > 0 && (
                <ul className="list-disc list-inside space-y-1 ml-2">
                  {article.key_points.map((point, pointIndex) => (
                    <li key={pointIndex} className="text-sm">
                      {point}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        ))}
      </div>
      
      {/* Footer */}
      <div className="flex items-center justify-between pt-4 mt-6 border-t dark:border-gray-600">
        <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
          <Clock className="w-3 h-3" />
          <span>Recently updated</span>
        </div>
      </div>
    </div>
  );
};

export default MarketNews; 