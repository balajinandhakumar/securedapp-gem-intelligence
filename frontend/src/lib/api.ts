/**
 * Shared frontend API client.
 *
 * Provides a consistent, typed wrapper around native `fetch` for all backend
 * API calls. Features:
 *   - Base API URL from VITE_BACKEND_URL (dev proxy) or relative path
 *   - Request timeout (default 30 seconds) via AbortController
 *   - Request cancellation via signal passthrough
 *   - HTTP error handling (distinguishes HTTP errors from network errors)
 *   - JSON parsing with safe fallback
 *   - Typed responses via generic parameter
 *   - Stale-response prevention via request token/sequence tracking
 *   - Automatic Bearer token injection from sessionStorage
 *   - Automatic access-token refresh on 401 (single in-flight refresh)
 *   - 401/403 error classification
 *
 * No external HTTP dependency (no Axios) — uses native fetch only.
 */

import {
  getStoredTokens,
  isTokenNearExpiry,
  markTokensCaptured,
  refreshAccessToken,
} from './auth';

const DEFAULT_TIMEOUT_MS = 30_000;

/**
 * Auth-aware fetch wrapper. Injects the Bearer access token on every request,
 * handles 401/403 responses, and performs automatic token refresh on 401.
 *
 * A single in-flight refresh is allowed at a time; concurrent 401s wait for
 * the refresh to complete and then retry with the new access token. If refresh
 * fails, the caller receives a 401 ApiError with code SESSION_EXPIRED.
 */
let refreshInProgress: Promise<string | null> | null = null;

export function setRefreshInProgress(p: Promise<string | null> | null): void {
  refreshInProgress = refreshInProgress ?? p;
}

/**
 * Perform a single in-flight token refresh. Concurrent callers share the same
 * promise so only one refresh request hits the backend. Returns the new access
 * token, or null if refresh is not needed / not possible.
 */
async function performRefresh(refreshToken: string): Promise<string | null> {
  // If a refresh is already in flight, wait for it.
  if (refreshInProgress) {
    return refreshInProgress;
  }

  const refreshPromise = (async () => {
    try {
      const data = await refreshAccessToken(refreshToken);
      return data.access_token;
    } catch {
      return null;
    }
  })();

  refreshInProgress = refreshPromise;
  try {
    return await refreshPromise;
  } finally {
    refreshInProgress = null;
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number | null,
    public readonly isNetworkError: boolean,
    public readonly isTimeout: boolean,
    public readonly code?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/**
 * Options for {@link apiRequest}.
 */
export interface ApiRequestOptions {
  method?: string;
  headers?: Record<string, string>;
  body?: unknown;
  timeoutMs?: number;
  signal?: AbortSignal;
}

/**
 * Perform a typed JSON API request.
 *
 * @param path — API path, e.g. `/api/v1/products`. Relative paths are used as-is
 *   (they are proxied by Vite in dev and served from the same origin in prod).
 * @param options — HTTP method, headers, body, timeout, abort signal.
 * @returns Parsed JSON response body of type `T`.
 * @throws {ApiError} on HTTP errors, network failures, or timeouts.
 */
export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const {
    method = 'GET',
    headers = {},
    body,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    signal: externalSignal,
  } = options;

  // Build an AbortController for the timeout. If an external signal is provided
  // (e.g. from a component unmount), we abort on either timeout or external
  // cancellation.
  const controller = new AbortController();
  const abort = () => controller.abort();

  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  if (timeoutMs > 0) {
    timeoutId = setTimeout(abort, timeoutMs);
  }

  // Combine external signal with our internal controller.
  if (externalSignal) {
    const onExternalAbort = () => abort();
    externalSignal.addEventListener('abort', onExternalAbort, { once: true });
  }

  const fetchOptions: RequestInit = {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...headers,
    },
    signal: controller.signal,
  };

  // Inject Bearer token from sessionStorage for all non-auth endpoints.
  // Auth endpoints (login, refresh) do not carry a token yet.
  const isAuthEndpoint = path.startsWith('/api/v1/auth/');
  if (!isAuthEndpoint) {
    const tokens = getStoredTokens();
    if (tokens?.access_token) {
      fetchOptions.headers = {
        ...fetchOptions.headers,
        Authorization: `Bearer ${tokens.access_token}`,
      };
    }
  }

  if (body !== undefined && (method === 'POST' || method === 'PUT' || method === 'PATCH' || method === 'DELETE')) {
    fetchOptions.body = JSON.stringify(body);
  }

  try {
    const res = await fetch(path, fetchOptions);

    // Clear the timeout now that we have a response.
    if (timeoutId) clearTimeout(timeoutId);

    // Handle 401 with automatic token refresh (single in-flight refresh).
    if (res.status === 401 && !isAuthEndpoint) {
      const tokens = getStoredTokens();
      if (tokens?.refresh_token) {
        try {
          const newAccessToken = await performRefresh(tokens.refresh_token);
          if (newAccessToken) {
            // Retry the original request with the new access token.
            const retryOptions: RequestInit = {
              ...fetchOptions,
              headers: {
                ...fetchOptions.headers,
                Authorization: `Bearer ${newAccessToken}`,
              },
            };
            const res2 = await fetch(path, retryOptions);
            if (res2.ok) {
              const contentType = res2.headers.get('content-type') ?? '';
              if (res2.status === 204 || !contentType.includes('application/json')) {
                return null as unknown as T;
              }
              const data = await res2.json();
              return data as T;
            }
            // If retry still fails with 401, the refresh token is invalid.
            let detail: string | null = null;
            try {
              const data = await res2.json();
              if (typeof data?.detail === 'string') detail = data.detail;
            } catch {
              /* no JSON body */
            }
            throw new ApiError(
              detail || 'Session expired. Please log in again.',
              res2.status,
              false,
              false,
              'SESSION_EXPIRED',
            );
          } else {
            // Refresh failed — no new access token obtained.
            throw new ApiError(
              'Session expired. Please log in again.',
              401,
              false,
              false,
              'SESSION_EXPIRED',
            );
          }
        } catch (err) {
          if (err instanceof ApiError) throw err;
          throw new ApiError(
            'Session expired. Please log in again.',
            401,
            false,
            false,
            'SESSION_EXPIRED',
          );
        }
      } else {
        throw new ApiError(
          'Authentication required. Please log in.',
          401,
          false,
          false,
          'SESSION_EXPIRED',
        );
      }
    }

    if (res.status === 403) {
      let detail: string | null = null;
      try {
        const data = await res.json();
        if (typeof data?.detail === 'string') {
          detail = data.detail;
        }
      } catch {
        /* no JSON body */
      }
      throw new ApiError(
        detail || 'Insufficient permissions for this action.',
        403,
        false,
        false,
        'FORBIDDEN',
      );
    }

    if (!res.ok) {
      let detail: string | null = null;
      try {
        const data = await res.json();
        if (typeof data?.detail === 'string') {
          detail = data.detail;
        } else if (Array.isArray(data?.detail)) {
          detail = data.detail
            .map((d: { loc?: string[]; msg?: string }) => `${d.loc?.slice(1).join('.') ?? ''} ${d.msg ?? ''}`.trim())
            .join('; ');
        } else if (typeof data?.detail === 'object') {
          detail = JSON.stringify(data.detail);
        }
      } catch {
        /* response had no JSON body */
      }
      throw new ApiError(detail || `HTTP ${res.status}`, res.status, false, false);
    }

    // For 204 No Content or empty responses, return null cast as T.
    const contentType = res.headers.get('content-type') ?? '';
    if (res.status === 204 || !contentType.includes('application/json')) {
      return null as unknown as T;
    }

    const data = await res.json();
    return data as T;
  } catch (err) {
    // Clear timeout if still pending.
    if (timeoutId) clearTimeout(timeoutId);

    if (err instanceof ApiError) throw err;

    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError(
        'The request was cancelled or timed out.',
        null,
        true,
        true,
      );
    }

    if (err instanceof TypeError && (err.message as string).includes('fetch')) {
      throw new ApiError(
        'Unable to connect to the backend API server. Verify the backend is running.',
        null,
        true,
        false,
      );
    }

    throw new ApiError(
      err instanceof Error ? err.message : 'An unknown error occurred.',
      null,
      true,
      false,
    );
  } finally {
    if (externalSignal) {
      externalSignal.removeEventListener('abort', () => abort());
    }
  }
}

/**
 * Convenience wrappers for common HTTP methods.
 */
export const api = {
  get: <T>(path: string, options?: Omit<ApiRequestOptions, 'method'>) =>
    apiRequest<T>(path, { ...options, method: 'GET' }),

  post: <T>(path: string, body?: unknown, options?: Omit<ApiRequestOptions, 'method' | 'body'>) =>
    apiRequest<T>(path, { ...options, method: 'POST', body }),

  put: <T>(path: string, body?: unknown, options?: Omit<ApiRequestOptions, 'method' | 'body'>) =>
    apiRequest<T>(path, { ...options, method: 'PUT', body }),

  delete: <T>(path: string, options?: Omit<ApiRequestOptions, 'method'>) =>
    apiRequest<T>(path, { ...options, method: 'DELETE' }),
};

/**
 * Create an AbortController with an optional timeout.
 * Returns `{ controller, signal }`.
 */
export function createAbortSignal(timeoutMs?: number): { controller: AbortController; signal: AbortSignal } {
  const controller = new AbortController();
  if (timeoutMs && timeoutMs > 0) {
    setTimeout(() => controller.abort(), timeoutMs);
  }
  return { controller, signal: controller.signal };
}

export { DEFAULT_TIMEOUT_MS };
