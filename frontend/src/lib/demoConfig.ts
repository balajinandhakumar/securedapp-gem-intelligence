/**
 * Demo-login configuration.
 *
 * The "Demo Login" button on the login page is a convenience for supervised
 * demonstrations. It is explicitly NOT a production feature:
 *
 *   - It authenticates through the real backend POST /api/v1/auth/login —
 *     no fake session, no bypass, no mocked token, and no backend change.
 *   - Credentials are supplied through development configuration (Vite env
 *     variables), never hardcoded in source code.
 *   - Credentials are never logged to the browser console or server logs.
 *   - The button is hidden in production unless the deployment explicitly
 *     authorizes demo access (VITE_DEMO_LOGIN_AUTHORIZED=true).
 *
 * A matching demo user must exist in the backend database before Demo Login
 * can succeed (create one via POST /api/v1/auth/users). The demo account is
 * a normal database user subject to the same login lockout, RBAC and token
 * rules as any other account.
 */

/** Vite exposes `VITE_*` environment variables on `import.meta.env`. The
 *  project's TS lib does not declare that shape, so we access it through a
 *  local cast rather than augmenting the global `ImportMeta` type. */
type ViteEnv = Record<string, string | undefined>;

function getEnv(): ViteEnv {
  return (import.meta as unknown as { env: ViteEnv }).env;
}

const isTrue = (value: string | undefined): boolean => value === 'true';

/**
 * Whether the Demo Login button should be rendered.
 *
 * Development: enabled via VITE_DEMO_LOGIN_ENABLED=true.
 * Production: disabled by default; requires BOTH
 * VITE_DEMO_LOGIN_ENABLED=true AND VITE_DEMO_LOGIN_AUTHORIZED=true.
 */
export function isDemoLoginEnabled(): boolean {
  const env = getEnv();
  const enabled = isTrue(env.VITE_DEMO_LOGIN_ENABLED);
  const environment = env.VITE_ENVIRONMENT ?? 'development';
  const explicitlyAuthorized = isTrue(env.VITE_DEMO_LOGIN_AUTHORIZED);
  return enabled && (environment !== 'production' || explicitlyAuthorized);
}

/** Demo account email (development configuration only). */
export function demoEmail(): string | undefined {
  return getEnv().VITE_DEMO_EMAIL;
}

/** Demo account password (development configuration only). */
export function demoPassword(): string | undefined {
  return getEnv().VITE_DEMO_PASSWORD;
}
