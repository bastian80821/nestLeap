import axios from 'axios';
import { StockAnalysis, StockRecommendation, NewsArticle, TrendingStock } from '@/types';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000, // 30 seconds timeout for stock analysis
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add request interceptor for logging
api.interceptors.request.use(
  (config) => {
    console.log(`API Request: ${config.method?.toUpperCase()} ${config.url}`);
    return config;
  },
  (error) => {
    console.error('API Request Error:', error);
    return Promise.reject(error);
  }
);

// Add response interceptor for error handling
api.interceptors.response.use(
  (response) => {
    return response;
  },
  (error) => {
    console.error('API Response Error:', error.response?.data || error.message);
    throw new Error(error.response?.data?.detail || error.message || 'API request failed');
  }
);

export const stockAPI = {
  // 🎯 NEW STOCK AGENT ENDPOINTS
  
  // Get comprehensive stock analysis from agents
  getStockAnalysis: async (ticker: string): Promise<any> => {
    const response = await api.get(`/api/stock/${ticker.toUpperCase()}/analysis`);
    return response.data;
  },

  // Trigger stock analysis
  triggerStockAnalysis: async (ticker: string): Promise<any> => {
    const response = await api.post(`/api/stock/${ticker.toUpperCase()}/analyze`);
    return response.data;
  },

  // Get price explanation
  getStockPriceExplanation: async (ticker: string, timeframe: string = "1d"): Promise<any> => {
    const response = await api.get(`/api/stock/${ticker.toUpperCase()}/price-explanation?timeframe=${timeframe}`);
    return response.data;
  },

  // Get peer comparison
  getStockPeerComparison: async (ticker: string): Promise<any> => {
    const response = await api.get(`/api/stock/${ticker.toUpperCase()}/peer-comparison`);
    return response.data;
  },

  // Add to watchlist
  addStockToWatchlist: async (ticker: string): Promise<any> => {
    const response = await api.get(`/api/stock/${ticker.toUpperCase()}/watchlist/add`);
    return response.data;
  },

  // Get user watchlist
  getWatchlist: async (): Promise<any> => {
    const response = await api.get('/api/watchlist');
    return response.data;
  },

  // 📊 MARKET AGENT ENDPOINTS

  // Get enhanced market sentiment
  getMarketSentimentEnhanced: async (): Promise<any> => {
    const response = await api.get('/api/market-sentiment/enhanced');
    return response.data;
  },

  // Get market news
  getMarketNews: async (): Promise<any> => {
    const response = await api.get('/api/market-news/enhanced');
    return response.data;
  },

  // Get fundamentals enhanced
  getFundamentalsEnhanced: async (): Promise<any> => {
    const response = await api.get('/api/fundamentals/enhanced');
    return response.data;
  },

  // Trigger market analysis
  triggerMarketAnalysis: async (): Promise<any> => {
    const response = await api.post('/api/agents/market/analyze');
    return response.data;
  },

  // Get agent status
  getAgentStatus: async (): Promise<any> => {
    const response = await api.get('/api/agents/status');
    return response.data;
  },

  // 🔄 LEGACY ENDPOINTS (for backward compatibility)
  
  // Search for stock analysis (maps to new agent endpoint)
  searchStock: async (ticker: string): Promise<StockAnalysis> => {
    // Try to get existing analysis first
    try {
      const response = await api.get(`/api/stock/${ticker.toUpperCase()}/analysis`);
      if (response.data.has_analysis) {
        return {
          ticker: response.data.ticker,
          company_name: response.data.ticker, // Use ticker as company name for now
          current_price: response.data.current_price,
          market_cap: response.data.market_cap,
          pe_ratio: response.data.pe_ratio,
          quality_score: response.data.confidence_score,
          margin_of_safety: response.data.upside_potential,
          recommendation: {
            ticker: response.data.ticker,
            action: response.data.overall_rating === 'Strong Buy' || response.data.overall_rating === 'Buy' ? 'BUY' :
                   response.data.overall_rating === 'Strong Sell' || response.data.overall_rating === 'Sell' ? 'SELL' : 'HOLD',
            confidence_score: response.data.confidence_score || 0.5,
            reasoning: response.data.why_current_price || 'AI analysis available',
            key_factors: response.data.key_insights || [],
            valuation_signal: response.data.confidence_score || 0.5,
            technical_signal: response.data.confidence_score || 0.5,
            news_sentiment_signal: response.data.confidence_score || 0.5,
            risk_level: 'medium' as const,
            volatility_score: 0.5,
            created_at: response.data.analysis_date || new Date().toISOString()
          },
          recent_news: []
        };
      }
    } catch (error) {
      console.log('No existing analysis, triggering new analysis...');
    }

    // If no analysis, trigger new one
    await api.post(`/api/stock/${ticker.toUpperCase()}/analyze`);
    
    // Wait a bit then try again
    await new Promise(resolve => setTimeout(resolve, 3000));
    
    try {
      const response = await api.get(`/api/stock/${ticker.toUpperCase()}/analysis`);
      return {
        ticker: response.data.ticker,
        company_name: response.data.ticker,
        current_price: response.data.current_price,
        market_cap: response.data.market_cap,
        pe_ratio: response.data.pe_ratio,
        quality_score: response.data.confidence_score,
        margin_of_safety: response.data.upside_potential,
        recommendation: {
          ticker: response.data.ticker,
          action: response.data.overall_rating === 'Strong Buy' || response.data.overall_rating === 'Buy' ? 'BUY' :
                 response.data.overall_rating === 'Strong Sell' || response.data.overall_rating === 'Sell' ? 'SELL' : 'HOLD',
          confidence_score: response.data.confidence_score || 0.5,
          reasoning: response.data.why_current_price || 'Analysis in progress...',
          key_factors: response.data.key_insights || [],
          valuation_signal: response.data.confidence_score || 0.5,
          technical_signal: response.data.confidence_score || 0.5,
          news_sentiment_signal: response.data.confidence_score || 0.5,
          risk_level: 'medium' as const,
          volatility_score: 0.5,
          created_at: response.data.analysis_date || new Date().toISOString()
        },
        recent_news: []
      };
    } catch (error) {
      throw new Error('Analysis still in progress. Please try again in a few moments.');
    }
  },

  // Get recommendation for a stock
  getRecommendation: async (ticker: string): Promise<StockRecommendation> => {
    const response = await api.get(`/api/stock/${ticker.toUpperCase()}/analysis`);
    return {
      ticker: response.data.ticker,
      action: response.data.overall_rating === 'Strong Buy' || response.data.overall_rating === 'Buy' ? 'BUY' :
             response.data.overall_rating === 'Strong Sell' || response.data.overall_rating === 'Sell' ? 'SELL' : 'HOLD',
      confidence_score: response.data.confidence_score || 0.5,
      reasoning: response.data.why_current_price || 'AI analysis available',
      key_factors: response.data.key_insights || [],
      valuation_signal: response.data.confidence_score || 0.5,
      technical_signal: response.data.confidence_score || 0.5,
      news_sentiment_signal: response.data.confidence_score || 0.5,
      risk_level: 'medium' as const,
      volatility_score: 0.5,
      created_at: response.data.analysis_date || new Date().toISOString()
    };
  },

  // Get market sentiment (fallback)
  getMarketSentiment: async (): Promise<any> => {
    try {
      const response = await api.get('/api/market-sentiment/enhanced');
      return response.data;
    } catch (error) {
      // Fallback to basic sentiment
    const response = await api.get('/api/market-sentiment');
    return response.data;
    }
  },

  // Get fundamentals data (fallback)
  getFundamentals: async (): Promise<any> => {
    try {
      const response = await api.get('/api/fundamentals/enhanced');
      return response.data;
    } catch (error) {
      // Fallback to basic fundamentals
    const response = await api.get('/api/fundamentals');
      return response.data;
    }
  },

  // Get trending stocks (mock data for now)
  getTrending: async (): Promise<{ trending: TrendingStock[], updated_at: string }> => {
    return {
      trending: [
        { ticker: 'MSFT', score: 8.5, sentiment: 'bullish' },
        { ticker: 'AAPL', score: 7.2, sentiment: 'neutral' },
        { ticker: 'GOOGL', score: 8.1, sentiment: 'bullish' },
        { ticker: 'AMZN', score: 6.8, sentiment: 'neutral' },
        { ticker: 'TSLA', score: 9.2, sentiment: 'very_bullish' }
      ],
      updated_at: new Date().toISOString()
    };
  },

  // Health check
  healthCheck: async (): Promise<{ status: string, timestamp: string, services: any }> => {
    const response = await api.get('/health');
    return response.data;
  },

  // Collect fresh fundamentals data (incremental - only new dates)
  collectFundamentals: async (): Promise<any> => {
    const response = await api.post('/api/fundamentals/collect');
    return response.data;
  },

  // Backfill historical fundamentals data
  backfillFundamentals: async (daysBack: number = 730): Promise<any> => {
    const response = await api.post(`/api/fundamentals/backfill?days_back=${daysBack}`);
    return response.data;
  },

  // Get fundamentals database statistics
  getFundamentalsStats: async (): Promise<any> => {
    const response = await api.get('/api/fundamentals/stats');
    return response.data;
  },

  // Get upcoming economic events
  getEconomicEvents: async (): Promise<any> => {
    const response = await api.get('/api/fundamentals/events');
    return response.data;
  },
};

export default api; 