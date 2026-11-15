/**
 * Mocked tests for AuthContext (context/AuthContext.tsx).
 *
 * Covers: session restore, login, logout, refresh success/failure,
 * expired session handling, and role-based capability checks.
 *
 * These tests mock `fetch` and sessionStorage. They do NOT contact a live
 * backend. Live integration evidence is documented in
 * PHASE_5_1_FRONTEND_IMPLEMENTATION_REPORT.md Section 8.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import '@testing-library/jest-dom';
import { AuthProvider, useAuth } from './AuthContext';

const mockTokens = {
  access_token: 'access-token-123',
  refresh_token: 'refresh-token-456',
  token_type: 'bearer',
  expires_in: 1800,
};

const mockAdminUser = { id: 'u1', email: 'admin@securedapp.io', name: 'Admin', role: 'admin', active: true };
const mockViewerUser = { id: 'u3', email: 'viewer@securedapp.io', name: 'Viewer', role: 'viewer', active: true };

const mockLoginResponse = { ...mockTokens, user: mockAdminUser };

function mockFetch(response: any, status = 200) {
  return vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => response,
  })) as unknown as typeof fetch & { mock: { calls: unknown[] } };
}

// Harness: renders a consumer component that captures the auth instance.
function renderWithAuth(ui: (auth: ReturnType<typeof useAuth>) => React.ReactNode) {
  let authRef: ReturnType<typeof useAuth> | null = null;
  const Consumer = () => {
    authRef = useAuth();
    return ui(authRef);
  };
  const result = render(
    <AuthProvider>
      <Consumer />
    </AuthProvider>,
  );
  return { getAuth: () => authRef!, ...result };
}

describe('AuthContext — mocked', () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it('restores session from sessionStorage via /me on mount', async () => {
    sessionStorage.setItem('securedapp_auth_tokens', JSON.stringify(mockTokens));
    sessionStorage.setItem('securedapp_auth_user', JSON.stringify(mockAdminUser));

    const fetchMock = mockFetch(mockAdminUser, 200);
    vi.stubGlobal('fetch', fetchMock);

    renderWithAuth((auth) => <div data-testid="restored">{auth.isAuthenticated ? 'yes' : 'no'}</div>);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/me', expect.any(Object));
    });
  });

  it('clears session when /me returns 401 and no refresh token exists', async () => {
    sessionStorage.setItem('securedapp_auth_tokens', JSON.stringify(mockTokens));
    sessionStorage.setItem('securedapp_auth_user', JSON.stringify(mockAdminUser));

    const fetchMock = mockFetch({ detail: 'Unauthorized' }, 401);
    vi.stubGlobal('fetch', fetchMock);

    renderWithAuth((auth) => <div data-testid="user">{auth.isAuthenticated ? 'yes' : 'no'}</div>);

    await waitFor(() => {
      expect(sessionStorage.getItem('securedapp_auth_tokens')).toBeNull();
      expect(sessionStorage.getItem('securedapp_auth_user')).toBeNull();
    });
  });

  it('refreshes access token when /me fails with 401 but refresh token exists', async () => {
    sessionStorage.setItem('securedapp_auth_tokens', JSON.stringify(mockTokens));
    sessionStorage.setItem('securedapp_auth_user', JSON.stringify(mockAdminUser));

    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('/me')) {
        return { ok: false, status: 401, headers: new Headers(), json: async () => ({ detail: 'Token expired' }) };
      }
      if (url.endsWith('/refresh')) {
        return {
          ok: true, status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: async () => ({ access_token: 'new-access-token', token_type: 'bearer', expires_in: 1800 }),
        };
      }
      return { ok: true, status: 200, headers: new Headers(), json: async () => mockAdminUser };
    }) as unknown as typeof fetch;
    vi.stubGlobal('fetch', fetchMock);

    renderWithAuth((auth) => <div data-testid="user">{auth.isAuthenticated ? 'yes' : 'no'}</div>);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/refresh', expect.any(Object));
    });
  });

  it('login stores tokens and sets user', async () => {
    const fetchMock = mockFetch(mockLoginResponse, 200);
    vi.stubGlobal('fetch', fetchMock);

    const { getAuth } = renderWithAuth((auth) => (
      <button onClick={() => auth.login({ email: 'a@b.c', password: 'p' })}>login</button>
    ));

    fireEvent.click(screen.getByRole('button', { name: 'login' }));

    await waitFor(() => {
      expect(sessionStorage.getItem('securedapp_auth_tokens')).not.toBeNull();
      expect(sessionStorage.getItem('securedapp_auth_user')).not.toBeNull();
    });
  });

  it('logout clears user and storage', async () => {
    sessionStorage.setItem('securedapp_auth_tokens', JSON.stringify(mockTokens));
    sessionStorage.setItem('securedapp_auth_user', JSON.stringify(mockAdminUser));

    // /me must return a valid user so session restore stores the right thing.
    vi.stubGlobal('fetch', mockFetch(mockAdminUser, 200));

    // Mount to complete session restore, then unmount.
    const { unmount } = renderWithAuth((auth) => <div data-testid="user">{auth.isAuthenticated ? 'yes' : 'no'}</div>);

    await waitFor(() => {
      expect(sessionStorage.getItem('securedapp_auth_tokens')).not.toBeNull();
    });
    unmount();

    // Clear storage so the second mount's session-restore does not call /me.
    sessionStorage.clear();

    // Replace fetch so /logout returns success, then mount fresh for logout.
    vi.stubGlobal('fetch', mockFetch({ detail: 'Logged out' }, 200));

    const { getAuth } = renderWithAuth((auth) => (
      <button onClick={() => auth.logout()}>logout</button>
    ));

    // First log in via the context so there's a session to log out from.
    await act(async () => {
      await getAuth().login({ email: 'admin@securedapp.io', password: 'SecurePass123!' });
    });

    fireEvent.click(screen.getByRole('button', { name: 'logout' }));

    await waitFor(() => {
      expect(sessionStorage.getItem('securedapp_auth_tokens')).toBeNull();
      expect(sessionStorage.getItem('securedapp_auth_user')).toBeNull();
    });
  });

  it('role capabilities: ADMIN can write products, manage sources, manage users, run matching', async () => {
    const fetchMock = mockFetch(mockLoginResponse, 200);
    vi.stubGlobal('fetch', fetchMock);

    const { getAuth } = renderWithAuth(() => null);

    await act(async () => {
      await getAuth().login({ email: 'admin@securedapp.io', password: 'SecurePass123!' });
    });

    expect(getAuth().canWriteProducts()).toBe(true);
    expect(getAuth().canManageSources()).toBe(true);
    expect(getAuth().canManageUsers()).toBe(true);
    expect(getAuth().canRunMatching()).toBe(true);
    expect(getAuth().isAuthenticated).toBe(true);
    expect(getAuth().user?.role).toBe('admin');
  });

  it('role capabilities: VIEWER cannot write products, manage sources/users, or run matching', async () => {
    const viewerTokens = { ...mockTokens };
    const viewerUser = { ...mockAdminUser, role: 'viewer' as const };
    const viewerLoginResponse = { ...viewerTokens, user: viewerUser };

    const fetchMock = mockFetch(viewerLoginResponse, 200);
    vi.stubGlobal('fetch', fetchMock);

    const { getAuth } = renderWithAuth(() => null);

    await act(async () => {
      await getAuth().login({ email: 'viewer@securedapp.io', password: 'SecurePass123!' });
    });

    expect(getAuth().canWriteProducts()).toBe(false);
    expect(getAuth().canManageSources()).toBe(false);
    expect(getAuth().canManageUsers()).toBe(false);
    expect(getAuth().canRunMatching()).toBe(false);
    expect(getAuth().user?.role).toBe('viewer');
  });
});