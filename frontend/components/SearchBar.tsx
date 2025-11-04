import React, { useState } from 'react';
import { Search, Loader2 } from 'lucide-react';

interface SearchBarProps {
  query: string;
  onQueryChange: (query: string) => void;
  onSearch: (query: string) => void;
  isLoading: boolean;
  placeholder?: string;
}

const SearchBar: React.FC<SearchBarProps> = ({
  query,
  onQueryChange,
  onSearch,
  isLoading,
  placeholder = "Enter stock ticker..."
}) => {
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim() && !isLoading) {
      onSearch(query.trim().toUpperCase());
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value.toUpperCase();
    onQueryChange(value);
  };

  return (
    <div className="max-w-2xl mx-auto">
      <form onSubmit={handleSubmit} className="relative">
        <div className="relative">
          <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
            <Search className="h-5 w-5 text-neutral-400 dark:text-neutral-500" />
          </div>
          
          <input
            type="text"
            value={query}
            onChange={handleInputChange}
            placeholder={placeholder}
            disabled={isLoading}
            className="block w-full pl-12 pr-16 py-4 text-lg border border-neutral-300 dark:border-black-500 rounded-xl 
                     focus:ring-2 focus:ring-primary-500 focus:border-transparent 
                     placeholder-neutral-400 dark:placeholder-neutral-500 
                     bg-white dark:bg-black-700 text-neutral-900 dark:text-neutral-100 shadow-sm
                     disabled:bg-neutral-50 dark:disabled:bg-black-600 disabled:text-neutral-500 dark:disabled:text-neutral-400
                     transition-colors"
            autoComplete="off"
            spellCheck="false"
          />
          
          <div className="absolute inset-y-0 right-0 flex items-center pr-2">
            <button
              type="submit"
              disabled={!query.trim() || isLoading}
              className="inline-flex items-center px-4 py-2 border border-transparent 
                       text-sm font-medium rounded-lg text-white bg-primary-600 
                       hover:bg-primary-700 focus:outline-none focus:ring-2 
                       focus:ring-offset-2 focus:ring-primary-500 
                       disabled:opacity-50 disabled:cursor-not-allowed
                       transition-colors duration-200"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Analyzing...
                </>
              ) : (
                <>
                  <Search className="w-4 h-4 mr-2" />
                  Analyze
                </>
              )}
            </button>
          </div>
        </div>
      </form>
      
      <div className="mt-4 text-center">
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Try popular stocks: 
          <button 
            onClick={() => onSearch('AAPL')}
            className="ml-2 text-primary-600 dark:text-primary-400 hover:text-primary-700 dark:hover:text-primary-300 font-medium transition-colors"
          >
            AAPL
          </button>
          <span className="mx-1 text-neutral-400 dark:text-neutral-500">•</span>
          <button 
            onClick={() => onSearch('GOOGL')}
            className="text-primary-600 dark:text-primary-400 hover:text-primary-700 dark:hover:text-primary-300 font-medium transition-colors"
          >
            GOOGL
          </button>
          <span className="mx-1 text-neutral-400 dark:text-neutral-500">•</span>
          <button 
            onClick={() => onSearch('MSFT')}
            className="text-primary-600 dark:text-primary-400 hover:text-primary-700 dark:hover:text-primary-300 font-medium transition-colors"
          >
            MSFT
          </button>
          <span className="mx-1 text-neutral-400 dark:text-neutral-500">•</span>
          <button 
            onClick={() => onSearch('TSLA')}
            className="text-primary-600 dark:text-primary-400 hover:text-primary-700 dark:hover:text-primary-300 font-medium transition-colors"
          >
            TSLA
          </button>
        </p>
      </div>
    </div>
  );
};

export default SearchBar; 