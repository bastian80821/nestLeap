'use client';

import React, { useState } from 'react';
import { AlertCircle } from 'lucide-react';
import { stockAPI } from '@/lib/api';
import { StockAnalysis } from '@/types';
import StockCard from '@/components/StockCard';
import SearchBar from '@/components/SearchBar';
import MarketNews from '@/components/MarketNews';
import MarketSentiment from '@/components/MarketSentiment';
import Fundamentals from '@/components/Fundamentals';
import DebugGeminiCalls from '@/components/DebugGeminiCalls';
import Dashboards from '@/components/Dashboards';
import { ThemeToggle } from '@/components/ThemeToggle';
import { toast } from 'react-hot-toast';

// Check if running in admin mode
const ADMIN_MODE = process.env.NEXT_PUBLIC_ADMIN_MODE === 'true';

export default function HomePage() {
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<StockAnalysis | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [showSearch, setShowSearch] = useState(false);
  const [activeTab, setActiveTab] = useState<string>('dashboards');

  const handleSearch = async (ticker: string) => {
    if (!ticker.trim()) {
      toast.error('Please enter a stock ticker');
      return;
    }

    setIsSearching(true);
    setSearchError(null);
    
    try {
      const data = await stockAPI.searchStock(ticker);
      setSearchResults(data);
      toast.success(`Found insights for ${data.ticker}`);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to analyze stock';
      setSearchError(errorMessage);
      setSearchResults(null);
      toast.error(errorMessage);
    } finally {
      setIsSearching(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-neutral-50 to-neutral-100 dark:from-black-900 dark:to-black-800">
      {/* Minimal Header with Expandable Search */}
      <header className="bg-white dark:bg-black-700 shadow-sm border-b border-neutral-200 dark:border-black-500">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex items-center justify-between">
            <div className="flex items-center space-x-6">
              <div className="flex items-center space-x-3">
                <img 
                  src="/logo.png" 
                  alt="NestLeap" 
                  className="w-10 h-10 object-contain rounded-lg"
                />
                <h1 className="text-xl font-bold text-neutral-900 dark:text-neutral-100">
                  NestLeap
                </h1>
              </div>
              
              {/* Navigation Tabs */}
              <nav className="flex space-x-6" aria-label="Tabs">
                {[
                  { id: 'dashboards', label: 'Dashboards' },
                  { id: 'sentiment', label: 'Momentum' },
                  { id: 'news', label: 'News' },
                  { id: 'fundamentals', label: 'Fundamentals' },
                  ...(ADMIN_MODE ? [{ id: 'debug', label: 'Debug' }] : []),
                ].map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`py-2 px-3 rounded-lg font-medium text-sm transition-colors ${
                      activeTab === tab.id
                        ? 'bg-blue-100 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400'
                        : 'text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-black-600'
                    }`}
                  >
                    <span>{tab.label}</span>
                  </button>
                ))}
              </nav>
              </div>
          <div className="flex items-center space-x-3">
            <ThemeToggle />
          </div>
        </div>
      </header>

      {/* Search Section */}
      {showSearch && (
        <div className="bg-white dark:bg-black-700 border-b border-neutral-200 dark:border-black-500 shadow-sm animate-fade-in">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
            <SearchBar
              query={searchQuery}
              onQueryChange={setSearchQuery}
              onSearch={handleSearch}
              isLoading={isSearching}
              placeholder="Enter stock ticker (e.g., AAPL, GOOGL, MSFT) to get AI insights"
            />
          </div>
        </div>
      )}

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Search Results */}
        {searchResults && (
          <div className="mb-8 animate-fade-in">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold text-neutral-900 dark:text-neutral-100">
                Investment Analysis
              </h2>
              <button
                onClick={() => setSearchResults(null)}
                className="text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-300 text-sm"
              >
                Clear Results
              </button>
            </div>
            <StockCard stock={searchResults} />
          </div>
        )}

        {/* Error Display */}
        {searchError && (
          <div className="mb-8 animate-fade-in">
            <div className="bg-danger-50 dark:bg-danger-900/20 border border-danger-200 dark:border-danger-800 rounded-lg p-4">
              <div className="flex items-center">
                <AlertCircle className="w-5 h-5 text-danger-600 dark:text-danger-400 mr-3" />
                <p className="text-danger-700 dark:text-danger-300">{searchError}</p>
              </div>
            </div>
          </div>
        )}

        {/* Tab Content */}
        <div className="min-h-screen">
          {activeTab === 'sentiment' && (
            <div className="animate-fade-in">
              <MarketSentiment />
            </div>
          )}
          {activeTab === 'news' && (
            <div className="animate-fade-in">
              <MarketNews />
            </div>
          )}
          {activeTab === 'fundamentals' && (
            <div className="animate-fade-in">
              <Fundamentals />
            </div>
          )}
          {activeTab === 'dashboards' && (
            <div className="animate-fade-in">
              <Dashboards />
            </div>
          )}
          {ADMIN_MODE && activeTab === 'debug' && (
            <div className="animate-fade-in">
              <DebugGeminiCalls />
            </div>
          )}
        </div>
      </main>
    </div>
  );
} 