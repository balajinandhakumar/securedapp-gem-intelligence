/**
 * Authentication service for the SecuredApp GeM Bid Intelligence Platform.
 *
 * Implements the backend auth contract defined in PHASE_5_0_AUTH_API_CONTRACT.md.
 *
 * Token storage strategy (per contract Section 9):
 *   - access_token and refresh_token are held in sessionStorage so they survive
 *     a page refresh, but are not persisted across browser restarts (reduces
 *     long-term XSS exposure vs localStorage).
 *   - Tokens are never logged.
 *   - No HttpOnly cookies are used (the backend issues Bearer tokens).
 *   - No CSRF tokens are required by the contract.
 */

import {
  AuthTokens,
  AuthUser,
  LoginRequest,
  LoginResponse,
  RefreshRequest,
  RefreshResponse,
  UserRole,
} from '../types';

const API_BASE = '/api/v1/auth';

/* -------------------------------------------------------------------------- */
/* Token storage (sessionStorage)                                             */
/* -------------------------------------------------------------------------- */

const TOKEN_KEY = 'securedapp_auth_tokens';
const USER_KEY = 'securedapp_auth_user';

export function getStoredTokens(): AuthTokens | null {
  try {
    const raw = sessionStorage.getItem(TOKEN_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as AuthTokens;
  } catch {
    return null;
  }
}

export function setStoredTokens(tokens: AuthTokens): void {
  sessionStorage.setItem(TOKEN_KEY, JSON.stringify(tokens));
}

export function clearStoredTokens(): void {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
}

export function getStoredUser(): AuthUser | null {
  try {
    const raw = sessionStorage.getItem(USER_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function setStoredUser(user: AuthUser): void {
  sessionStorage.setItem(USER_KEY, JSON.stringify(user));
}

/* -------------------------------------------------------------------------- */
/* Token expiry helpers                                                       */
/* -------------------------------------------------------------------------- */

/**
 * Returns true when the access token is within the refresh window (last 5 min
 * of its 30-minute life). The backend contract recommends refreshing at ~25 min.
 */
export function isTokenNearExpiry(tokens: AuthTokens, refreshWindowSec = 300): boolean {
  // We don't decode the JWT on the frontend (no JWT library dependency), so we
  // track expiry via the expires_in value returned by /login and /refresh,
  // stored against a capture timestamp.
  const capture = sessionStorage.getItem('securedapp_auth_captured_at');
  if (!capture) return true;
  const elapsedSec = (Date.now() - parseInt(capture, 10)) / 1000;
  return elapsedSec >= tokens.expires_in - refreshWindowSec;
}

export function markTokensCaptured(): void {
  sessionStorage.setItem('securedapp_auth_captured_at', Date.now().toString());
}

/* -------------------------------------------------------------------------- */
/* Auth API calls                                                             */
/* -------------------------------------------------------------------------- */

/**
 * Read the error detail from a Response, falling back to a default message.
 */
async function readErrorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data?.detail === 'string') return data.detail;
  } catch {
    /* no JSON body */
  }
  return fallback;
}

/**
 * Authenticate with email + password. Returns the token pair and user profile.
 * Throws on 401 (invalid credentials / locked account) or 422 (validation).
 */
export async function login(req: LoginRequest): Promise<LoginResponse> {
  const res = await fetch(`${API_BASE}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    const detail = await readErrorDetail(res, 'Login failed.');
    if (res.status === 401) {
      const err: any = new Error(detail);
      err.status = 401;
      err.code = 'INVALID_CREDENTIALS';
      throw err;
    }
    if (res.status === 422) {
      const err: any = new Error(detail);
      err.status = 422;
      err.code = 'VALIDATION_ERROR';
      throw err;
    }
    throw new Error(detail);
  }

  const data: LoginResponse = await res.json();

  // Persist tokens and user profile for session restoration.
  setStoredTokens(data);
  setStoredUser(data.user);
  markTokensCaptured();

  return data;
}

/**
 * Revoke the current access token and the refresh token, then clear local
 * storage. Does not throw if the network call fails — local state is always
 * cleared so the user can log in again.
 */
export async function logout(): Promise<void> {
  const tokens = getStoredTokens();

  try {
    if (tokens) {
      await fetch(`${API_BASE}/logout`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens.access_token}`,
        },
        body: JSON.stringify({ refresh_token: tokens.refresh_token }),
      });
    }
  } catch {
    // Best-effort revocation. Local state is cleared regardless.
  } finally {
    clearStoredTokens();
  }
}

/**
 * Fetch the current user profile using the stored access token.
 * Throws on 401 (missing / expired / revoked token).
 */
export async function getCurrentUser(tokens: AuthTokens): Promise<AuthUser> {
  const res = await fetch(`${API_BASE}/me`, {
    method: 'GET',
    headers: {
      Authorization: `Bearer ${tokens.access_token}`,
    },
  });

  if (!res.ok) {
    if (res.status === 401) {
      const err: any = new Error('Session expired. Please log in again.');
      err.status = 401;
      err.code = 'SESSION_EXPIRED';
      throw err;
    }
    const detail = await readErrorDetail(res, 'Failed to load user profile.');
    throw new Error(detail);
  }

  const user: AuthUser = await res.json();
  setStoredUser(user);
  return user;
}

/**
 * Exchange a valid refresh token for a new access token.
 * Throws on 401 (invalid / revoked / expired refresh token).
 */
export async function refreshAccessToken(
  refreshToken: string,
): Promise<RefreshResponse> {
  const req: RefreshRequest = { refresh_token: refreshToken };
  const res = await fetch(`${API_BASE}/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    if (res.status === 401) {
      const err: any = new Error('Refresh failed. Please log in again.');
      err.status = 401;
      err.code = 'REFRESH_FAILED';
      throw err;
    }
    const detail = await readErrorDetail(res, 'Token refresh failed.');
    throw new Error(detail);
  }

  const data: RefreshResponse = await res.json();

  // Update the stored access token while keeping the same refresh token.
  const current = getStoredTokens();
  if (current) {
    const updated: AuthTokens = {
      ...current,
      access_token: data.access_token,
      expires_in: data.expires_in,
    };
    setStoredTokens(updated);
    markTokensCaptured();
  }

  return data;
}

/**
 * Check whether the user has a stored (potentially valid) session.
 * Does not validate the token with the backend — use getCurrentUser() for that.
 */
export function hasStoredSession(): boolean {
  return !!getStoredTokens() && !!getStoredUser();
}

/**
 * Get the stored user role, or null if no session exists.
 */
export function getStoredRole(): UserRole | null {
  const user = getStoredUser();
  return user ? user.role : null;
}
