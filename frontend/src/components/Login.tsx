/**
 * Login page for the SecuredApp GeM Bid Intelligence Platform.
 *
 * Authenticates against the real backend endpoint POST /api/v1/auth/login
 * (per PHASE_5_0_AUTH_API_CONTRACT.md Section 3.1).
 *
 * No credentials are hardcoded. No mock authentication is used.
 */

import React, { useCallback, useRef, useState } from 'react';
import { LoginRequest } from '../types';
import { isDemoLoginEnabled, demoEmail, demoPassword } from '../lib/demoConfig';
import { useAuth } from '../context/AuthContext';
import { IconShieldCheck } from './icons';

interface LoginProps {
  onSuccess?: () => void;
}

export const Login: React.FC<LoginProps> = ({ onSuccess }) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [demoLoading, setDemoLoading] = useState(false);
  const submitRef = useRef(false);

  const { login: contextLogin } = useAuth();
  const showDemoLogin = isDemoLoginEnabled();

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();

      // Prevent duplicate submissions.
      if (submitRef.current) return;
      submitRef.current = true;

      setError(null);
      setLoading(true);

      try {
        const req: LoginRequest = {
          email: email.trim().toLowerCase(),
          password,
        };

        await contextLogin(req);

        if (onSuccess) {
          onSuccess();
        }
      } catch (err: any) {
        if (err.status === 401) {
          setError(
            err.code === 'INVALID_CREDENTIALS'
              ? 'Invalid email or password. Please try again.'
              : 'Account may be locked or credentials invalid. Please try again later.',
          );
        } else if (err.status === 422) {
          setError('Please enter a valid email and password (at least 8 characters).');
        } else {
          setError(
            'Unable to connect to the backend. Verify the server is running and try again.',
          );
        }
      } finally {
        setLoading(false);
        submitRef.current = false;
      }
    },
    [email, password, contextLogin, onSuccess],
  );

  const handleTogglePassword = useCallback(() => {
    setShowPassword((prev) => !prev);
  }, []);

  /**
   * Sign in as the pre-configured demo account through the real backend
   * authentication endpoint. Credentials come from development configuration
   * only (never hardcoded here) and are never logged.
   */
  const handleDemoLogin = useCallback(async () => {
    const email = demoEmail();
    const password = demoPassword();

    if (!email || !password) {
      setError(
        'Demo login is not configured. Set VITE_DEMO_EMAIL and VITE_DEMO_PASSWORD in development configuration.',
      );
      return;
    }

    setError(null);
    setDemoLoading(true);

    // Deliberately no credential logging — email/password never touch the console.
    try {
      await contextLogin({ email, password });

      if (onSuccess) {
        onSuccess();
      }
    } catch (err: any) {
      if (err.status === 401) {
        setError(
          'Demo login failed: invalid demo credentials. Create the demo user via POST /api/v1/auth/users.',
        );
      } else if (err.status === 422) {
        setError('Demo login credentials are invalid.');
      } else {
        setError(
          'Unable to connect to the backend. Verify the server is running and demo login is configured.',
        );
      }
    } finally {
      setDemoLoading(false);
    }
  }, [onSuccess]);

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-header">
          <div className="login-logo">
            <IconShieldCheck size={32} />
          </div>
          <h1 className="login-title">SecuredApp</h1>
          <p className="login-subtitle">GeM Bid Intelligence — Sign in</p>
        </div>

        {error && (
          <div className="login-error" role="alert">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate>
          <div className="field-group">
            <label htmlFor="email" className="field-label">
              Email address
            </label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              className="form-input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@organisation.gov.in"
              required
              disabled={loading}
              aria-required="true"
              aria-describedby="email-hint"
            />
            <span id="email-hint" className="field-hint">
              Use your organisation email address.
            </span>
          </div>

          <div className="field-group">
            <label htmlFor="password" className="field-label">
              Password
            </label>
            <div className="password-input-wrapper">
              <input
                id="password"
                name="password"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                className="form-input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
                disabled={loading}
                aria-required="true"
                aria-describedby="password-hint"
              />
              <button
                type="button"
                className="toggle-password-btn"
                onClick={handleTogglePassword}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                title={showPassword ? 'Hide password' : 'Show password'}
                disabled={loading}
              >
                {showPassword ? '🙈' : '👁'}
              </button>
            </div>
            <span id="password-hint" className="field-hint">
              Password must be at least 8 characters.
            </span>
          </div>

          <button
            type="submit"
            className="btn-primary login-btn"
            disabled={loading || demoLoading || submitRef.current}
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        {showDemoLogin && (
          <div className="login-demo">
            <button
              type="button"
              className="btn-secondary login-demo-btn"
              onClick={handleDemoLogin}
              disabled={demoLoading || loading || submitRef.current}
            >
              {demoLoading ? 'Signing in as demo…' : 'Demo Login'}
            </button>
            <p className="login-demo-hint">
              Demonstration only — authenticates against the real backend using
              the configured demo account. Disabled in production.
            </p>
          </div>
        )}

        <div className="login-footer">
          <p className="login-footer-text">
            No default account exists. Your administrator must create your
            account via the secure setup command.
          </p>
        </div>
      </div>
    </div>
  );
};

export default Login;
