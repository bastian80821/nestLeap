/**
 * Admin API helper functions with authentication
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const ADMIN_API_KEY = process.env.NEXT_PUBLIC_ADMIN_API_KEY || '';

/**
 * Make an authenticated admin API request
 */
export async function adminFetch(
  endpoint: string,
  options: RequestInit = {}
): Promise<Response> {
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  // Add admin API key if available
  if (ADMIN_API_KEY) {
    headers['X-Admin-API-Key'] = ADMIN_API_KEY;
  }

  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`;

  const response = await fetch(url, {
    ...options,
    headers,
  });

  return response;
}

/**
 * Make an authenticated admin GET request
 */
export async function adminGet<T = any>(endpoint: string): Promise<T> {
  const response = await adminFetch(endpoint);
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }
  
  return response.json();
}

/**
 * Make an authenticated admin POST request
 */
export async function adminPost<T = any>(
  endpoint: string,
  data?: any
): Promise<T> {
  const response = await adminFetch(endpoint, {
    method: 'POST',
    body: data ? JSON.stringify(data) : undefined,
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }
  
  return response.json();
}

/**
 * Check if admin mode is enabled
 */
export function isAdminMode(): boolean {
  return process.env.NEXT_PUBLIC_ADMIN_MODE === 'true';
}

/**
 * Check if admin API key is configured
 */
export function hasAdminKey(): boolean {
  return !!ADMIN_API_KEY;
}

