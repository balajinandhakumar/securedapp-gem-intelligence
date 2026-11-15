import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AdapterMeta,
  ConfiguredSource,
  SourceStatus,
  SourcesMeta,
  canManageSources,
} from '../types';
import { api } from '../lib/api';
import {
  IconMonitor,
  IconDatabase,
  IconClockAlert,
  IconBell,
  IconShieldCheck,
  IconListSearch,
  IconBox,
} from './icons';

interface SourceMonitoringViewProps {
  canManageSources: () => boolean;
}

/**
 * Scraper & Source Monitoring.
 *
 * Read-only observability over the configurable bid-source registry. Every
 * figure comes from the backend (``GET /api/v1/sources`` and
 * ``GET /api/v1/sources/meta``); nothing is estimated or fabricated. Source
 * connection tests and syncs are live backend calls and require the Operator
 * or Admin role.
 */
export const SourceMonitoringView: React.FC<SourceMonitoringViewProps> = ({
  canManageSources: canManageSourcesFn,
}) => {
  const [sources, setSources] = useState<ConfiguredSource[]>([]);
  const [meta, setMeta] = useState<SourcesMeta | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [testing, setTesting] = useState<Record<string, boolean>>({});
  const [syncing, setSyncing] = useState<Record<string, boolean>>({});
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; message: string }>>({});
  const [syncResults, setSyncResults] = useState<Record<string, any>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setErrorMessage(null);
    try {
      const [sourcesRes, metaRes] = await Promise.all([
        api.get<ConfiguredSource[]>('/api/v1/sources'),
        api.get<SourcesMeta>('/api/v1/sources/meta'),
      ]);
      setSources(sourcesRes);
      setMeta(metaRes);
    } catch (err) {
      console.error('Failed to load source monitoring data', err);
      setErrorMessage(
        err instanceof Error ? err.message : 'Unable to load source monitoring data.',
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const adapters: AdapterMeta[] = meta?.adapters ?? [];
  const schedulerEnabled = meta?.scheduler?.enabled ?? false;
  const adapterByKey = useMemo(
    () => new Map(adapters.map((a) => [a.adapter_key, a])),
    [adapters],
  );

  // ── Derived metrics ──────────────────────────────────────────────
  const totalSources = sources.length;
  const enabledSources = sources.filter((s) => s.enabled).length;
  const needsAttention = sources.filter(
    (s) =>
      s.status === 'CONFIG_ERROR' ||
      s.status === 'NO_RECORDS' ||
      s.status === 'NOT_CONFIGURED' ||
      s.status === 'ERROR' ||
      s.status === 'FAILED' ||
      s.status === 'BLOCKED',
  ).length;

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    sources.forEach((s) => {
      counts[s.status] = (counts[s.status] ?? 0) + 1;
    });
    return counts;
  }, [sources]);

  const totals = sources.reduce(
    (acc, s) => ({
      discovered: acc.discovered + (s.last_discovered || 0),
      validated: acc.validated + (s.last_validated || 0),
      inserted: acc.inserted + (s.last_inserted || 0),
      updated: acc.updated + (s.last_updated || 0),
      duplicates: acc.duplicates + (s.last_duplicates || 0),
      rejected: acc.rejected + (s.last_rejected || 0),
    }),
    { discovered: 0, validated: 0, inserted: 0, updated: 0, duplicates: 0, rejected: 0 },
  );

  const allTimeTotals = sources.reduce(
    (acc, s) => ({
      inserted: acc.inserted + (s.total_inserted || 0),
      updated: acc.updated + (s.total_updated || 0),
      duplicates: acc.duplicates + (s.total_duplicates || 0),
      rejected: acc.rejected + (s.total_rejected || 0),
    }),
    { inserted: 0, updated: 0, duplicates: 0, rejected: 0 },
  );

  const statusBadge = (status: SourceStatus): { cls: string; label: string } => {
    const ok = ['SUCCESS', 'PARTIAL', 'PREVIEW'];
    const bad = ['ERROR', 'FAILED', 'BLOCKED', 'NO_RECORDS'];
    const warn = ['CONFIG_ERROR', 'NEEDS_ATTENTION', 'BUSY', 'SKIPPED'];
    let cls = 'badge-review';
    if (ok.includes(status)) cls = 'badge-match';
    else if (bad.includes(status)) cls = 'badge-urgent';
    else if (warn.includes(status)) cls = 'badge-review';
    if (status === 'RUNNING') cls = 'badge-review';
    if (status === 'IDLE') cls = 'badge-unknown';
    if (status === 'NOT_CONFIGURED') cls = 'badge-inactive';
    return { cls, label: status };
  };

  const formatWhen = (iso: string | null | undefined): string => {
    if (!iso) return '—';
    try {
      return new Date(iso).toLocaleString();
    } catch {
      return iso;
    }
  };

  const handleTest = async (source: ConfiguredSource) => {
    setTesting((t) => ({ ...t, [source.source_id]: true }));
    setTestResults((r) => ({ ...r, [source.source_id]: undefined }));
    try {
      const res = await fetch(`/api/v1/sources/${encodeURIComponent(source.source_id)}/test`, {
        method: 'POST',
      });
      const data = await res.json().catch(() => null);
      setTestResults((r) => ({
        ...r,
        [source.source_id]: data
          ? { ok: Boolean(data.ok), message: data.message || data.detail || 'Connection check failed.' }
          : { ok: false, message: 'No response from backend.' },
      }));
    } catch {
      setTestResults((r) => ({
        ...r,
        [source.source_id]: { ok: false, message: 'Network error while testing source.' },
      }));
    } finally {
      setTesting((t) => ({ ...t, [source.source_id]: false }));
    }
  };

  const handleSync = async (source: ConfiguredSource) => {
    setSyncing((s) => ({ ...s, [source.source_id]: true }));
    setSyncResults((r) => ({ ...r, [source.source_id]: undefined }));
    try {
      const res = await fetch(`/api/v1/sources/${encodeURIComponent(source.source_id)}/sync`, {
        method: 'POST',
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        setSyncResults((r) => ({
          ...r,
          [source.source_id]: {
            status: 'ERROR',
            message: data?.message || data?.detail || 'Sync failed.',
            inserted: 0,
            updated: 0,
          },
        }));
      } else if (data) {
        setSyncResults((r) => ({ ...r, [source.source_id]: data }));
      }
      await load();
    } catch {
      setSyncResults((r) => ({
        ...r,
        [source.source_id]: { status: 'ERROR', message: 'Network error while syncing source.', inserted: 0, updated: 0 },
      }));
    } finally {
      setSyncing((s) => ({ ...s, [source.source_id]: false }));
    }
  };

  const handleToggle = async (source: ConfiguredSource, enabled: boolean) => {
    const res = await fetch(
      `/api/v1/sources/${encodeURIComponent(source.source_id)}/${enabled ? 'enable' : 'disable'}`,
      { method: 'POST' },
    );
    if (res.ok) await load();
  };

  return (
    <div className="card-panel">
      <div className="panel-header" style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
        <div>
          <h2 className="panel-title">
            <span style={{ color: 'var(--accent-cyan)', marginRight: '0.5rem', display: 'inline-block', verticalAlign: 'middle' }}>
              <IconMonitor size={18} />
            </span>
            Scraper & Source Monitoring
          </h2>
          <p className="panel-subtitle">
            Read-only observability over every configured bid source. Status, run counts and the last
            connection-check result come from the backend; nothing here is estimated.
          </p>
        </div>
        <button className="btn-secondary btn-sm" onClick={load} disabled={loading}>
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {errorMessage && (
        <div className="alert-error" style={{ marginBottom: '1rem' }}>{errorMessage}</div>
      )}

      {/* Scheduler banner */}
      <div className="alert-info" style={{ marginBottom: '1.25rem' }}>
        <strong>Scheduled collection:</strong>{' '}
        {schedulerEnabled
          ? 'Enabled — eligible sources collect at their configured interval.'
          : 'Off — sources only collect on manual Sync. Enable SOURCE_SCHEDULER_ENABLED in the backend to automate.'}
        {adapters.length > 0 && (
          <span style={{ marginLeft: '1rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            ({adapters.length} adapter(s) registered)
          </span>
        )}
      </div>

      {loading ? (
        <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>Loading source monitoring data…</div>
      ) : (
        <>
          {/* ── KPI strip ── */}
          <div className="metrics-row" style={{ marginBottom: '1.25rem' }}>
            <div className="kpi-tile">
              <div className="kpi-top">
                <div className="kpi-icon" />
                <span className="kpi-label">Configured sources</span>
              </div>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--text-main)' }}>{totalSources}</div>
              <div className="kpi-sub">{enabledSources} enabled · {needsAttention} need attention</div>
            </div>

            <div className="kpi-tile">
              <div className="kpi-top">
                <div className="kpi-icon" />
                <span className="kpi-label">Last run — discovered</span>
              </div>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--text-main)' }}>{totals.discovered}</div>
              <div className="kpi-sub">{totals.validated} validated</div>
            </div>

            <div className="kpi-tile">
              <div className="kpi-top">
                <div className="kpi-icon" />
                <span className="kpi-label">Last run — inserted</span>
              </div>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--accent-green)' }}>{totals.inserted}</div>
              <div className="kpi-sub">{totals.updated} updated · {totals.duplicates} duplicates</div>
            </div>

            <div className="kpi-tile">
              <div className="kpi-top">
                <div className="kpi-icon" />
                <span className="kpi-label">All time — inserted</span>
              </div>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--text-main)' }}>{allTimeTotals.inserted}</div>
              <div className="kpi-sub">{allTimeTotals.updated} updated · {allTimeTotals.rejected} rejected</div>
            </div>
          </div>

          {/* ── Status breakdown ── */}
          <div style={{ marginBottom: '1rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            {(['SUCCESS', 'CONFIG_ERROR', 'NO_RECORDS', 'NOT_CONFIGURED', 'IDLE', 'RUNNING', 'ERROR'] as const).map(
              (status) => {
                const count = statusCounts[status] ?? 0;
                if (count === 0) return null;
                const { cls } = statusBadge(status);
                return (
                  <span
                    key={status}
                    className={`badge ${cls}`}
                    title={`${status}: ${count} source(s)`}
                  >
                    {status} ({count})
                  </span>
                );
              },
            )}
          </div>

          {/* ── Source table ── */}
          <div className="table-responsive">
            <table className="feed-table">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Adapter</th>
                  <th>Status</th>
                  <th>Last check / error</th>
                  <th>Discovered</th>
                  <th>Validated</th>
                  <th>Inserted</th>
                  <th>Updated</th>
                  <th>Duplicates</th>
                  <th>Rejected</th>
                  <th>Next run</th>
                  <th style={{ width: '230px' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sources.map((source) => {
                  const adapter = adapterByKey.get(source.adapter_key);
                  const badge = statusBadge(source.status);
                  const test = testResults[source.source_id];
                  const sync = syncResults[source.source_id];

                  // Pre-compute the "last check / error" cell to avoid nested
                  // ternaries inside JSX.
                  let lastCheckNode: React.ReactNode;
                  if (test) {
                    lastCheckNode = (
                      <>
                        {test.ok ? 'Connection OK' : 'Connection failed'}
                        <br />
                        <span style={{ color: test.ok ? 'var(--accent-green)' : 'var(--accent-amber)' }}>
                          {test.message}
                        </span>
                      </>
                    );
                  } else if (source.last_error) {
                    lastCheckNode = source.last_error;
                  } else {
                    lastCheckNode = <span style={{ color: 'var(--text-dim)' }}>Not yet tested</span>;
                  }
                  return (
                    <tr key={source.source_id}>
                      <td>
                        <div style={{ fontWeight: 600, color: 'var(--text-main)' }}>{source.name}</div>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                          <code>{source.source_id}</code>{' '}
                          {source.base_url && <span style={{ marginLeft: '0.35rem', color: 'var(--text-dim)' }}>{source.base_url}</span>}
                        </div>
                        <div style={{ display: 'flex', gap: '0.35rem', marginTop: '0.3rem', flexWrap: 'wrap' }}>
                          <span className={`badge ${badge.cls}`}>{badge.label}</span>
                          <span className={`badge ${source.enabled ? 'badge-match' : 'badge-review'}`}>
                            {source.enabled ? 'ENABLED' : 'DISABLED'}
                          </span>
                          {source.has_credentials && (
                            <span style={{ marginLeft: '0.35rem', color: 'var(--accent-amber)' }} title="Uses a credential from an env var">
                              key
                            </span>
                          )}
                        </div>
                        {source.last_error && (
                          <div style={{ marginTop: '0.3rem', fontSize: '0.72rem', color: 'var(--accent-amber)', maxWidth: '340px' }} title={source.last_error}>
                            {source.last_error}
                          </div>
                        )}
                      </td>
                      <td>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-main)' }}>{source.source_type}</div>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{adapter?.adapter_label ?? source.adapter_key}</div>
                        {source.base_url && (
                          <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>{source.base_url}</div>
                        )}
                      </td>
                      <td>
                        <span className={`badge ${badge.cls}`}>{badge.label}</span>
                        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{formatWhen(source.last_attempt_at)}</div>
                      </td>
                      <td style={{ fontSize: '0.72rem', color: 'var(--text-muted)', maxWidth: '300px' }}>
                        {lastCheckNode}
                      </td>
                      <td style={{ fontSize: '0.75rem', color: 'var(--text-main)' }}>{source.last_discovered || 0}</td>
                      <td style={{ fontSize: '0.75rem', color: 'var(--text-main)' }}>{source.last_validated || 0}</td>
                      <td style={{ fontSize: '0.75rem', color: 'var(--accent-green)' }}>{source.last_inserted || 0}</td>
                      <td style={{ fontSize: '0.75rem', color: 'var(--accent-cyan)' }}>{source.last_updated || 0}</td>
                      <td style={{ fontSize: '0.75rem', color: 'var(--text-main)' }}>{source.last_duplicates || 0}</td>
                      <td style={{ fontSize: '0.75rem', color: 'var(--text-main)' }}>{source.last_rejected || 0}</td>
                      <td style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                        {source.next_run_at ? formatWhen(source.next_run_at) : '—'}
                      </td>
                      <td>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
                          {canManageSourcesFn() && (
                            <>
                              <button
                                className="btn-secondary btn-xs"
                                disabled={testing[source.source_id]}
                                onClick={() => handleTest(source)}
                                title="Run live connection test"
                              >
                                {testing[source.source_id] ? 'Testing…' : 'Test'}
                              </button>
                              <button
                                className="btn-primary btn-xs"
                                disabled={!source.enabled || syncing[source.source_id]}
                                onClick={() => handleSync(source)}
                                title="Run collection now"
                              >
                                {syncing[source.source_id] ? 'Syncing…' : 'Sync'}
                              </button>
                              <button
                                className="btn-secondary btn-xs"
                                onClick={() => handleToggle(source, !source.enabled)}
                                title={source.enabled ? 'Disable source' : 'Enable source'}
                              >
                                {source.enabled ? 'Disable' : 'Enable'}
                              </button>
                            </>
                          )}
                          {!canManageSourcesFn() && (
                            <span className="btn-xs busy" style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                              read-only
                            </span>
                          )}
                          {test && (
                            <div
                              className={test.ok ? 'alert-info' : 'alert-warning'}
                              style={{ marginTop: '0.5rem', marginBottom: 0, fontSize: '0.75rem' }}
                            >
                              {test.ok ? 'Test passed: ' : 'Test failed: '}
                              {test.message}
                            </div>
                          )}
                          {sync && sync.status && (
                            <div style={{ marginTop: '0.4rem', fontSize: '0.75rem' }}>
                              <span className={`badge ${statusBadge(sync.status as SourceStatus).cls}`}>{sync.status}</span>{' '}
                              {sync.message}
                              <br />
                              <span style={{ color: 'var(--accent-green)' }}>inserted {sync.inserted || 0}</span>{' · '}
                              <span style={{ color: 'var(--accent-cyan)' }}>updated {sync.updated || 0}</span>{' · '}
                              <span style={{ color: 'var(--text-main)' }}>duplicates {sync.duplicates || 0}</span>
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {sources.length === 0 && (
                  <tr>
                    <td colSpan={12}>
                      <div className="empty-state" style={{ padding: '1.5rem' }}>
                        <div className="empty-title">No sources configured</div>
                        <div className="empty-desc">
                          Register a bid source on the Data Source page to begin collection and monitoring.
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* ── Adapter catalog ── */}
          {adapters.length > 0 && (
            <div style={{ marginTop: '1.5rem', paddingTop: '1rem', borderTop: '1px solid var(--border-color)' }}>
              <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '0.85rem', color: 'var(--text-main)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                Registered adapters
              </h3>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem' }}>
                {adapters.map((adapter) => (
                  <span
                    key={adapter.adapter_key}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '0.4rem',
                      padding: '0.35rem 0.7rem',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--r-sm)',
                      background: 'var(--bg-surface)',
                      fontSize: '0.75rem',
                    }}
                  >
                    <span style={{ fontWeight: 600, color: 'var(--text-main)' }}>{adapter.adapter_key}</span>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>{adapter.method}</span>
                    {adapter.requires_credentials && (
                      <span style={{ color: 'var(--accent-amber)', fontSize: '0.7rem' }} title="Requires credentials">cred</span>
                    )}
                    {adapter.requires_browser && (
                      <span style={{ color: 'var(--accent-amber)', fontSize: '0.7rem' }} title="Browser-rendered">browser</span>
                    )}
                  </span>
                ))}
              </div>
              <p style={{ marginTop: '0.5rem', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                Adapter labels and requirements are reported by the backend catalog
                ({adapters.length} registered). Source configs are stored secret-free
                (credentials referenced by environment-variable name only).
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
};
