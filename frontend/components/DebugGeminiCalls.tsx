import React, { useEffect, useState } from 'react';
import { PlayCircle, Loader, CheckCircle, XCircle, RefreshCw, Clock } from 'lucide-react';

interface GeminiCallLog {
  timestamp: string;
  purpose: string;
}

interface BatchStatus {
  job_id: string;
  status: string;
  total_stocks: number;
  completed_stocks: number;
  failed_stocks: number;
  progress_pct: number;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
}

interface FailedAnalysis {
  ticker: string;
  company_name?: string;
  sector?: string;
  last_analyzed_at?: string;
  error_count: number;
  errors: string[];
}

const DebugGeminiCalls: React.FC = () => {
  const [logs, setLogs] = useState<GeminiCallLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  
  // Batch analysis state
  const [batchStatus, setBatchStatus] = useState<BatchStatus | null>(null);
  const [batchLoading, setBatchLoading] = useState(false);
  const [batchError, setBatchError] = useState<string | null>(null);
  const [pollingInterval, setPollingInterval] = useState<NodeJS.Timeout | null>(null);
  const [recentCompletions, setRecentCompletions] = useState<string[]>([]);
  
  // Failed analyses state
  const [failedAnalyses, setFailedAnalyses] = useState<FailedAnalysis[]>([]);
  const [failedLoading, setFailedLoading] = useState(false);
  
  // Force refresh state
  const [refreshing, setRefreshing] = useState<Record<string, boolean>>({});

  const fetchLogs = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('http://localhost:8000/api/debug/gemini-calls');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setLogs(data.logs || data); // support both {logs, total} and array
      setTotal(data.total || (Array.isArray(data) ? data.length : null));
    } catch (err) {
      setError('Failed to fetch Gemini API call logs');
    } finally {
      setLoading(false);
    }
  };
  
  const checkForRunningBatch = async () => {
    // ALWAYS check backend for currently running batch (don't rely on localStorage)
    try {
      const response = await fetch('http://localhost:8000/api/stocks/current-batch');
      if (response.ok) {
        const data = await response.json();
        
        if (data.job_id && data.status === 'running') {
          // Found running batch - start polling
          localStorage.setItem('batch_job_id', data.job_id);
          setBatchStatus(data);
          setBatchLoading(true);
          pollBatchStatus(data.job_id);
        } else if (data.job_id) {
          // Batch exists but completed/failed
          setBatchStatus(data);
          setBatchLoading(false);
          localStorage.removeItem('batch_job_id');
        }
      }
    } catch (err) {
      console.error('Error checking for running batch:', err);
      // Fallback: clear localStorage if backend query fails
      localStorage.removeItem('batch_job_id');
    }
  };

  useEffect(() => {
    fetchLogs();
    checkForRunningBatch();
    fetchFailedAnalyses();
    
    // Cleanup polling on unmount
    return () => {
      if (pollingInterval) {
        clearInterval(pollingInterval);
      }
    };
  }, []);
  
  const startBatchAnalysis = async () => {
    setBatchLoading(true);
    setBatchError(null);
    setRecentCompletions([]);
    
    try {
      const response = await fetch('http://localhost:8000/api/stocks/batch-analyze', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      });
      
      const data = await response.json();
      
      if (data.status === 'error') {
        setBatchError(data.error || 'Failed to start batch analysis');
        setBatchLoading(false);
        return;
      }
      
      // Store job_id in localStorage and start polling
      if (data.job_id) {
        localStorage.setItem('batch_job_id', data.job_id);
        pollBatchStatus(data.job_id);
      }
      
    } catch (err) {
      setBatchError('Failed to start batch analysis');
      setBatchLoading(false);
    }
  };

  const startFailedOnlyAnalysis = async () => {
    setBatchLoading(true);
    setBatchError(null);
    setRecentCompletions([]);
    
    try {
      const response = await fetch('http://localhost:8000/api/stocks/batch-analyze-failed', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      });
      
      const data = await response.json();
      
      if (data.status === 'error') {
        setBatchError(data.error || 'Failed to start failed-only analysis');
        setBatchLoading(false);
        return;
      }
      
      if (data.total_stocks === 0) {
        setBatchError('No failed analyses to re-analyze!');
        setBatchLoading(false);
        return;
      }
      
      // Store job_id in localStorage and start polling
      if (data.job_id) {
        localStorage.setItem('batch_job_id', data.job_id);
        pollBatchStatus(data.job_id);
      }
      
    } catch (err) {
      setBatchError('Failed to start failed-only analysis');
      setBatchLoading(false);
    }
  };
  
  const pollBatchStatus = async (jobId: string) => {
    // Clear any existing polling interval first
    if (pollingInterval) {
      clearInterval(pollingInterval);
      setPollingInterval(null);
    }
    
    let previousCompleted = 0;
    
    const poll = async () => {
      try {
        const response = await fetch(`http://localhost:8000/api/stocks/batch-status/${jobId}`);
        const data = await response.json();
        
        // Track new completions
        if (data.completed_stocks > previousCompleted) {
          const newCompletions = data.completed_stocks - previousCompleted;
          // Fetch recently completed stocks
          fetchRecentCompletions();
          previousCompleted = data.completed_stocks;
        }
        
        setBatchStatus(data);
        setBatchLoading(data.status === 'running');
        
        if (data.status === 'completed' || data.status === 'failed' || data.status === 'cancelled') {
          if (pollingInterval) {
            clearInterval(pollingInterval);
            setPollingInterval(null);
          }
          localStorage.removeItem('batch_job_id');
        }
      } catch (err) {
        console.error('Error polling batch status:', err);
      }
    };
    
    // Poll immediately
    await poll();
    
    // Then poll every 2 seconds (faster updates)
    const interval = setInterval(poll, 2000);
    setPollingInterval(interval);
  };
  
  const fetchRecentCompletions = async () => {
    try {
      const response = await fetch('http://localhost:8000/api/stocks/recent-completions?limit=10');
      if (response.ok) {
        const data = await response.json();
        setRecentCompletions(data.tickers || []);
      }
    } catch (err) {
      console.error('Error fetching recent completions:', err);
    }
  };

  const fetchFailedAnalyses = async () => {
    setFailedLoading(true);
    try {
      const response = await fetch('http://localhost:8000/api/stocks/failed-analyses');
      if (response.ok) {
        const data = await response.json();
        setFailedAnalyses(data.failed_analyses || []);
      }
    } catch (err) {
      console.error('Error fetching failed analyses:', err);
    } finally {
      setFailedLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Batch Analysis Section */}
      <div className="bg-white dark:bg-black-700 rounded-xl shadow-sm border border-neutral-200 dark:border-black-500 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-neutral-900 dark:text-neutral-100">S&P 500 Batch Analysis</h2>
          <div className="flex gap-2">
            <button
              onClick={startBatchAnalysis}
              className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
              disabled={batchLoading}
            >
              {batchLoading ? (
                <>
                  <Loader className="w-4 h-4 animate-spin" />
                  Analyzing...
                </>
              ) : (
                <>
                  <PlayCircle className="w-4 h-4" />
                  All Stocks ({failedAnalyses.length > 0 ? `471` : '471'})
                </>
              )}
            </button>
            {failedAnalyses.length > 0 && (
              <button
                onClick={startFailedOnlyAnalysis}
                className="flex items-center gap-2 px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
                disabled={batchLoading}
              >
                <PlayCircle className="w-4 h-4" />
                Failed Only ({failedAnalyses.length})
              </button>
            )}
          </div>
        </div>
        
        {batchError && (
          <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-800 dark:text-red-200">
            {batchError}
          </div>
        )}
        
        {batchStatus && (
          <div className="space-y-4">
            {/* Progress Bar */}
            <div>
              <div className="flex justify-between items-center mb-2">
                <span className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
                  Progress: {batchStatus.completed_stocks + batchStatus.failed_stocks}/{batchStatus.total_stocks} stocks
                </span>
                <span className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
                  {batchStatus.progress_pct}%
                </span>
              </div>
              <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-4">
                <div
                  className={`h-4 rounded-full transition-all duration-300 ${
                    batchStatus.status === 'completed' ? 'bg-green-600' :
                    batchStatus.status === 'failed' ? 'bg-red-600' :
                    'bg-blue-600'
                  }`}
                  style={{ width: `${batchStatus.progress_pct}%` }}
                />
              </div>
            </div>
            
            {/* Status Cards */}
            <div className="grid grid-cols-3 gap-4">
              <div className="bg-green-50 dark:bg-green-900/20 p-4 rounded-lg border border-green-200 dark:border-green-800">
                <div className="flex items-center gap-2 mb-1">
                  <CheckCircle className="w-5 h-5 text-green-600 dark:text-green-400" />
                  <span className="text-sm font-medium text-green-800 dark:text-green-200">Completed</span>
                </div>
                <div className="text-2xl font-bold text-green-900 dark:text-green-100">
                  {batchStatus.completed_stocks}
                </div>
              </div>
              
              <div className="bg-red-50 dark:bg-red-900/20 p-4 rounded-lg border border-red-200 dark:border-red-800">
                <div className="flex items-center gap-2 mb-1">
                  <XCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
                  <span className="text-sm font-medium text-red-800 dark:text-red-200">Failed</span>
                </div>
                <div className="text-2xl font-bold text-red-900 dark:text-red-100">
                  {batchStatus.failed_stocks}
                </div>
              </div>
              
              <div className="bg-blue-50 dark:bg-blue-900/20 p-4 rounded-lg border border-blue-200 dark:border-blue-800">
                <div className="flex items-center gap-2 mb-1">
                  <Loader className={`w-5 h-5 text-blue-600 dark:text-blue-400 ${batchStatus.status === 'running' ? 'animate-spin' : ''}`} />
                  <span className="text-sm font-medium text-blue-800 dark:text-blue-200">Status</span>
                </div>
                <div className="text-lg font-bold text-blue-900 dark:text-blue-100 capitalize">
                  {batchStatus.status}
                </div>
              </div>
            </div>
            
            {/* Job Info */}
            <div className="text-xs text-neutral-600 dark:text-neutral-400 space-y-1">
              <div>Job ID: {batchStatus.job_id}</div>
              {batchStatus.started_at && <div>Started: {new Date(batchStatus.started_at).toLocaleString()}</div>}
              {batchStatus.completed_at && <div>Completed: {new Date(batchStatus.completed_at).toLocaleString()}</div>}
              {batchStatus.error_message && (
                <div className="text-red-600 dark:text-red-400">Error: {batchStatus.error_message}</div>
              )}
            </div>
            
            {/* Recent Completions */}
            {recentCompletions.length > 0 && batchStatus.status === 'running' && (
              <div className="mt-4 p-4 bg-green-50 dark:bg-green-900/20 rounded-lg border border-green-200 dark:border-green-800">
                <div className="font-medium text-green-800 dark:text-green-200 mb-2">
                  ✓ Recently Completed ({recentCompletions.length})
                </div>
                <div className="flex flex-wrap gap-2">
                  {recentCompletions.map((ticker, idx) => (
                    <span
                      key={idx}
                      className="px-2 py-1 bg-green-100 dark:bg-green-900/40 text-green-800 dark:text-green-200 rounded text-xs font-medium"
                    >
                      {ticker}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
        
        {!batchStatus && !batchLoading && (
          <div className="text-center py-8 text-neutral-500 dark:text-neutral-400">
            Click "Start Batch Analysis" to analyze all S&P 500 stocks.
            <div className="text-sm mt-2">This will take approximately 50 minutes.</div>
          </div>
        )}
      </div>
      
      {/* Failed Analyses Section */}
      <div className="bg-white dark:bg-black-700 rounded-xl shadow-sm border border-neutral-200 dark:border-black-500 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-neutral-900 dark:text-neutral-100">
            Incomplete / Failed Analyses
          </h2>
          <button
            onClick={fetchFailedAnalyses}
            className="px-3 py-1 bg-orange-600 text-white rounded-lg hover:bg-orange-700 text-sm"
            disabled={failedLoading}
          >
            {failedLoading ? 'Updating...' : 'Refresh'}
          </button>
        </div>
        
        {failedAnalyses.length > 0 ? (
          <div>
            <div className="mb-4 p-4 bg-orange-50 dark:bg-orange-900/20 rounded-lg border border-orange-200 dark:border-orange-800">
              <div className="font-medium text-orange-800 dark:text-orange-200">
                ⚠️ Found {failedAnalyses.length} stocks with incomplete analyses
              </div>
              <div className="text-sm text-orange-700 dark:text-orange-300 mt-1">
                These stocks are missing required fields and may need re-analysis.
              </div>
            </div>
            
            <div className="overflow-x-auto max-h-96 overflow-y-auto">
              <table className="min-w-full text-sm text-neutral-900 dark:text-neutral-100">
                <thead className="sticky top-0 bg-neutral-100 dark:bg-black-600">
                  <tr>
                    <th className="px-3 py-2 text-left font-semibold">Ticker</th>
                    <th className="px-3 py-2 text-left font-semibold">Company</th>
                    <th className="px-3 py-2 text-left font-semibold">Sector</th>
                    <th className="px-3 py-2 text-left font-semibold">Errors</th>
                    <th className="px-3 py-2 text-left font-semibold">Last Analyzed</th>
                  </tr>
                </thead>
                <tbody>
                  {failedAnalyses.map((analysis, idx) => (
                    <tr key={idx} className="border-b border-neutral-200 dark:border-black-500 hover:bg-neutral-50 dark:hover:bg-black-600">
                      <td className="px-3 py-2 font-bold">{analysis.ticker}</td>
                      <td className="px-3 py-2">{analysis.company_name || 'N/A'}</td>
                      <td className="px-3 py-2">{analysis.sector || 'N/A'}</td>
                      <td className="px-3 py-2">
                        <div className="text-xs space-y-1">
                          {analysis.errors.map((err, i) => (
                            <div key={i} className="text-red-600 dark:text-red-400">• {err}</div>
                          ))}
                        </div>
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap text-xs">
                        {analysis.last_analyzed_at 
                          ? new Date(analysis.last_analyzed_at).toLocaleString()
                          : 'Never'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div className="text-center py-8 text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20 rounded-lg border border-green-200 dark:border-green-800">
            <CheckCircle className="w-12 h-12 mx-auto mb-2" />
            <div className="font-medium">✓ All analyses are complete!</div>
            <div className="text-sm mt-1">No incomplete or failed analyses found.</div>
          </div>
        )}
      </div>
      
      {/* Force Refresh Section */}
      <div className="bg-white dark:bg-black-700 rounded-xl shadow-sm border border-neutral-200 dark:border-black-500 p-6">
        <h2 className="text-xl font-bold text-neutral-900 dark:text-neutral-100 mb-4">
          Manual Force Refresh
        </h2>
        
        {/* Update Schedule Info */}
        <div className="mb-6 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
          <h3 className="font-semibold text-blue-800 dark:text-blue-200 mb-2 flex items-center gap-2">
            <Clock className="w-4 h-4" />
            Automated Update Schedule
          </h3>
          <div className="space-y-2 text-sm text-blue-700 dark:text-blue-300">
            <div>
              <strong>Hourly:</strong> Market news, stock prices, opportunities
            </div>
            <div>
              <strong>Daily:</strong> Stock fundamentals, market sentiment, momentum, economic indicators
            </div>
          </div>
        </div>
        
        {/* Force Refresh Buttons */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <button
            onClick={async () => {
              setRefreshing(prev => ({ ...prev, sentiment: true }));
              try {
                const res = await fetch('http://localhost:8000/api/market-sentiment/force-refresh', { method: 'POST' });
                const data = await res.json();
                alert(data.success ? 'Sentiment refreshed!' : `Error: ${data.error}`);
              } catch (err) {
                alert('Failed to refresh sentiment');
              } finally {
                setRefreshing(prev => ({ ...prev, sentiment: false }));
              }
            }}
            disabled={refreshing['sentiment']}
            className="flex items-center justify-center gap-2 px-4 py-3 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 transition-colors"
          >
            {refreshing['sentiment'] ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                Refreshing...
              </>
            ) : (
              <>
                <RefreshCw className="w-4 h-4" />
                Market Sentiment & Momentum
              </>
            )}
          </button>
          
          <button
            onClick={async () => {
              setRefreshing(prev => ({ ...prev, fundamentals: true }));
              try {
                const res = await fetch('http://localhost:8000/api/economic-fundamentals/force-refresh', { method: 'POST' });
                const data = await res.json();
                alert(data.status === 'success' ? 'Fundamentals refreshed!' : `Error: ${data.error}`);
              } catch (err) {
                alert('Failed to refresh fundamentals');
              } finally {
                setRefreshing(prev => ({ ...prev, fundamentals: false }));
              }
            }}
            disabled={refreshing['fundamentals']}
            className="flex items-center justify-center gap-2 px-4 py-3 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {refreshing['fundamentals'] ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                Refreshing...
              </>
            ) : (
              <>
                <RefreshCw className="w-4 h-4" />
                Economic Fundamentals
              </>
            )}
          </button>
          
          <button
            onClick={async () => {
              setRefreshing(prev => ({ ...prev, news: true }));
              try {
                const res = await fetch('http://localhost:8000/api/market-news/force-refresh', { method: 'POST' });
                const data = await res.json();
                alert(data.status === 'success' ? 'News refreshed!' : `Error: ${data.error}`);
              } catch (err) {
                alert('Failed to refresh news');
              } finally {
                setRefreshing(prev => ({ ...prev, news: false }));
              }
            }}
            disabled={refreshing['news']}
            className="flex items-center justify-center gap-2 px-4 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 transition-colors"
          >
            {refreshing['news'] ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                Refreshing...
              </>
            ) : (
              <>
                <RefreshCw className="w-4 h-4" />
                Market News
              </>
            )}
          </button>
          
          <button
            onClick={async () => {
              setRefreshing(prev => ({ ...prev, opportunities: true }));
              try {
                const res = await fetch('http://localhost:8000/api/stocks/scan-opportunities', { method: 'POST' });
                const data = await res.json();
                alert(data.scan_completed ? 'Opportunities scanned!' : `Error: ${data.error}`);
              } catch (err) {
                alert('Failed to scan opportunities');
              } finally {
                setRefreshing(prev => ({ ...prev, opportunities: false }));
              }
            }}
            disabled={refreshing['opportunities']}
            className="flex items-center justify-center gap-2 px-4 py-3 bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50 transition-colors"
          >
            {refreshing['opportunities'] ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                Scanning...
              </>
            ) : (
              <>
                <RefreshCw className="w-4 h-4" />
                Scan Opportunities
              </>
            )}
          </button>
        </div>
      </div>
      
      {/* Gemini API Log Section */}
      <div className="bg-white dark:bg-black-700 rounded-xl shadow-sm border border-neutral-200 dark:border-black-500 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-neutral-900 dark:text-neutral-100">Gemini API Call Debug Log</h2>
          <button
            onClick={fetchLogs}
            className="px-3 py-1 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm"
            disabled={loading}
          >
            {loading ? 'Updating...' : 'Update'}
          </button>
        </div>
      <div className="mb-2 text-neutral-800 dark:text-neutral-200 font-medium">
        Total Gemini API calls: {total !== null ? total : logs.length}
      </div>
      {error && <div className="text-red-600 dark:text-red-400 mb-4">{error}</div>}
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm text-neutral-900 dark:text-neutral-100">
          <thead>
            <tr className="bg-neutral-100 dark:bg-black-600">
              <th className="px-3 py-2 text-left font-semibold">Timestamp</th>
              <th className="px-3 py-2 text-left font-semibold">Purpose</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((log, idx) => (
              <tr key={idx} className="border-b border-neutral-200 dark:border-black-500">
                <td className="px-3 py-2 whitespace-nowrap">{new Date(log.timestamp).toLocaleString()}</td>
                <td className="px-3 py-2 whitespace-nowrap">{log.purpose}</td>
              </tr>
            ))}
            {logs.length === 0 && !loading && (
              <tr>
                <td colSpan={2} className="px-3 py-4 text-center text-neutral-500 dark:text-neutral-400">No Gemini API calls logged yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      </div>
    </div>
  );
};

export default DebugGeminiCalls; 