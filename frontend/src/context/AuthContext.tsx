/**
 * Authentication context provider for the SecuredApp frontend.
 *
 * Manages the session lifecycle:
 *   - Restores tokens and user profile from sessionStorage on mount.
 *   - Validates the session via GET /me (or refreshes the access token).
 *   - Provides login(), logout(), and refreshSession() to consumers.
 *   - Tracks auth loading state so the shell can show a login gate.
 *
 * Contract: PHASE_5_0_AUTH_API_CONTRACT.md (Session 1 handoff).
 */

import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  useRef,
  ReactNode,
} from 'react';
import {
  AuthUser,
  LoginRequest,
  LoginResponse,
  UserRole,
} from '../types';
import {
  clearStoredTokens,
  getStoredTokens,
  getStoredUser,
  hasStoredSession,
  login as authLogin,
  logout as authLogout,
  getCurrentUser,
  refreshAccessToken,
  setStoredTokens,
  setStoredUser,
} from '../lib/auth';

interface AuthContextType {
  user: AuthUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (req: LoginRequest) => Promise<LoginResponse>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<void>;
  hasRole: (role: UserRole) => boolean;
  canWriteProducts: () => boolean;
  canManageSources: () => boolean;
  canManageUsers: () => boolean;
  canRunMatching: () => boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

/**
 * Role hierarchy index — higher = more privileged.
 */
const ROLE_RANK: Record<UserRole, number> = {
  viewer: 1,
  operator: 2,
  admin: 3,
};

function roleAtLeast(userRole: UserRole | null, required: UserRole): boolean {
  if (!userRole) return false;
  return ROLE_RANK[userRole] >= ROLE_RANK[required];
}

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const refreshMutex = useRef<Promise<void> | null>(null);

  const hasAuthenticated = user !== null;

  const login = useCallback(
    async (req: LoginRequest): Promise<LoginResponse> => {
      const response = await authLogin(req);
      setUser(response.user);
      return response;
    },
    [],
  );

  const logout = useCallback(async (): Promise<void> => {
    await authLogout();
    setUser(null);
    setIsLoading(false);
  }, []);

  const refreshSession = useCallback(async (): Promise<void> => {
    // Serialize refresh attempts — only one at a time.
    if (refreshMutex.current) {
      await refreshMutex.current;
      return;
    }

    refreshMutex.current = (async () => {
      try {
        const tokens = getStoredTokens();
        if (!tokens?.refresh_token) {
          setUser(null);
          setIsLoading(false);
          return;
        }

        // Try refreshing the access token.
        const data = await refreshAccessToken(tokens.refresh_token);

        // Re-fetch the user profile with the new access token.
        const currentUser = await getCurrentUser({
          ...tokens,
          access_token: data.access_token,
          expires_in: data.expires_in,
        } as never);
        setUser(currentUser);
      } catch {
        // Refresh failed — session is gone.
        clearStoredTokens();
        setUser(null);
      } finally {
        setIsLoading(false);
        refreshMutex.current = null;
      }
    })();

    await refreshMutex.current;
  }, []);

  // Restore session on mount: validate stored tokens via /me, or refresh.
  useEffect(() => {
    let cancelled = false;

    async function restoreSession() {
      if (!hasStoredSession()) {
        setIsLoading(false);
        return;
      }

      const tokens = getStoredTokens();
      const storedUser = getStoredUser();

      if (!tokens || !storedUser) {
        setIsLoading(false);
        return;
      }

      // Trust the stored user profile initially, but validate the token.
      setUser(storedUser);

      try {
        const currentUser = await getCurrentUser(tokens);
        if (!cancelled) setUser(currentUser);
      } catch {
        // /me failed — try refreshing the access token.
        try {
          if (tokens.refresh_token) {
            const data = await refreshAccessToken(tokens.refresh_token);
            if (!cancelled) {
              const currentUser = await getCurrentUser({
                ...tokens,
                access_token: data.access_token,
                expires_in: data.expires_in,
              } as never);
              setUser(currentUser);
            }
          } else {
            if (!cancelled) {
              clearStoredTokens();
              setUser(null);
            }
          }
        } catch {
          if (!cancelled) {
            clearStoredTokens();
            setUser(null);
          }
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    restoreSession();

    return () => {
      cancelled = true;
    };
  }, []);

  const hasRole = useCallback(
    (role: UserRole): boolean => roleAtLeast(user?.role ?? null, role),
    [user?.role],
  );

  const canWriteProducts = useCallback((): boolean => {
    if (!user) return false;
    return roleAtLeast(user.role, 'operator');
  }, [user?.role]);

  const canManageSources = useCallback((): boolean => {
    if (!user) return false;
    return roleAtLeast(user.role, 'operator');
  }, [user?.role]);

  const canManageUsers = useCallback((): boolean => {
    if (!user) return false;
    return roleAtLeast(user.role, 'admin');
  }, [user?.role]);

  const canRunMatching = useCallback((): boolean => {
    if (!user) return false;
    return roleAtLeast(user.role, 'operator');
  }, [user?.role]);

  const value: AuthContextType = {
    user,
    isAuthenticated: hasAuthenticated,
    isLoading,
    login,
    logout,
    refreshSession,
    hasRole,
    canWriteProducts,
    canManageSources,
    canManageUsers,
    canRunMatching,
  };

  return (
    <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
  );
}

/**
 * Hook to consume the auth context. Throws if used outside AuthProvider.
 */
export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}

export default AuthContext;
