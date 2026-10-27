import React, { useCallback, useEffect, useState } from 'react';
import {
  AdapterMeta,
  ConfiguredSource,
  SourceCreatePayload,
  SourceRunRow,
  SourceSyncResult,
  SourcesMeta,
  SourceUpdatePayload,
} from '../types';

interface SourceManagementPanelProps {
  onImportSuccess: () => void;
}

/**
 * Configurable data-source registry UI for the Data Source page.
 *
 * Every configured source is collected through the same backend pipeline the
 * rest of the page uses. A source is never shown as "ready" just because the
 * form saved: "Test" runs a live connection check and "Sync" performs a real
 * collection run through the existing validation -> normalization -> dedupe ->
 * 11-product matching -> notification pipeline. Secrets are referenced by
 * environment-variable name only (`auth.env_ref`); the backend masks any
 * secret-key value in the config it returns, so nothing sensitive is rendered.
 */
export const SourceManagementPanel: React.FC<SourceManagementPanelProps> = ({ onImportSuccess }) => {
  const [meta, setMeta] = useState<SourcesMeta | null>(null);
  const [sources, setSources] = useState<ConfiguredSource[]>([]);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Editing state: '' = list, '_new' = create form, otherwise source_id being edited.
  const [editing, setEditing] = useState<string>('');
  const [form, setForm] = useState<{
    source_id: string;
    name: string;
    adapter_key: string;
    source_type: string;
    base_url: string;
    collection_interval_minutes: string;
    notes: string;
    configJson: string;
  }>(emptyForm());

  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Per-source action state.
  const [syncing, setSyncing] = useState<Record<string, boolean>>({});
  const [testing, setTesting] = useState<Record<string, boolean>>({});
  const [syncResults, setSyncResults] = useState<Record<string, SourceSyncResult>>({});
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; message: string }>>({});
  const [openRuns, setOpenRuns] = useState<Record<string, SourceRunRow[] | undefined>>({});
  const [runsLoading, setRunsLoading] = useState<Record<string, boolean>>({});

  const loadMeta = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/sources/meta');
      if (res.ok) setMeta(await res.json());
    } catch (err) {
      console.error('Failed to fetch source catalog', err);
    }
  }, []);

  const loadSources = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const res = await fetch('/api/v1/sources');
      if (res.ok) {
        setSources(await res.json());
      } else {
        setErrorMessage('Failed to load configured sources.');
      }
    } catch (err) {
      console.error('Failed to fetch sources', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMeta();
    loadSources();
  }, [loadMeta, loadSources]);

  const adapters = meta?.adapters ?? [];

  const selectAdapter = (adapterKey: string) => {
    const adapter = adapters.find((a) => a.adapter_key === adapterKey);
    setForm((prev) => ({
      ...prev,
      adapter_key: adapterKey,
      source_type: adapter?.source_types?.[0] ?? adapterKey,
      configJson: CONFIG_TEMPLATES[adapterKey] ?? '{}',
    }));
  };

  const openCreate = () => {
    setEditing('_new');
    setFormError(null);
    setForm((prev) => ({
      ...emptyForm(),
      configJson: CONFIG_TEMPLATES[adapters[0]?.adapter_key ?? ''] ?? '{}',
    }));
  };

  const openEdit = (source: ConfiguredSource) => {
    setEditing(source.source_id);
    setFormError(null);
    setSyncResults((r) => ({ ...r, [source.source_id]: undefined }));
    setForm({
      source_id: source.source_id,
      name: source.name,
      adapter_key: source.adapter_key,
      source_type: source.source_type,
      base_url: source.base_url ?? '',
      collection_interval_minutes: String(source.collection_interval_minutes || 60),
      notes: source.notes ?? '',
      configJson: JSON.stringify(source.config ?? {}, null, 2),
    });
  };

  const cancelEdit = () => {
    setEditing('');
    setForm(emptyForm());
    setFormError(null);
  };

  const handleSave = async () => {
    setFormError(null);
    let config: Record<string, unknown>;
    try {
      config = JSON.parse(form.configJson);
      if (config === null || Array.isArray(config) || typeof config !== 'object') {
        setFormError('Config must be a JSON object.');
        return;
      }
    } catch {
      setFormError('Config is not valid JSON.');
      return;
    }

    const interval = Math.max(5, Math.min(10080, Number(form.collection_interval_minutes) || 60));
    const isNew = editing === '_new';
    if (isNew && form.source_id.trim().length < 2) {
      setFormError('Source ID must be at least 2 characters.');
      return;
    }
    if (!form.name.trim()) {
      setFormError('Name is required.');
      return;
    }

    setSaving(true);
    try {
      if (isNew) {
        const payload: SourceCreatePayload = {
          source_id: form.source_id.trim().toLowerCase(),
          name: form.name.trim(),
          base_url: form.base_url.trim() || null,
          source_type: form.source_type || form.adapter_key,
          adapter_key: form.adapter_key,
          config,
          enabled: true,
          collection_interval_minutes: interval,
          notes: form.notes.trim() || null,
        };
        const res = await fetch('/api/v1/sources', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => null);
        if (!res.ok) {
          setFormError(data?.detail ?? 'Failed to create source.');
          return;
        }
      } else {
        const payload: SourceUpdatePayload = {
          name: form.name.trim(),
          base_url: form.base_url.trim() || null,
          source_type: form.source_type || null,
          adapter_key: form.adapter_key,
          config,
          collection_interval_minutes: interval,
          notes: form.notes.trim() || null,
        };
        const res = await fetch(`/api/v1/sources/${encodeURIComponent(editing)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => null);
        if (!res.ok) {
          setFormError(data?.detail ?? 'Failed to update source.');
          return;
        }
      }
      setEditing('');
      setForm(emptyForm());
      await loadSources(true);
    } catch {
      setFormError('Network error while saving source.');
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (source: ConfiguredSource, enabled: boolean) => {
    const res = await fetch(`/api/v1/sources/${encodeURIComponent(source.source_id)}/${enabled ? 'enable' : 'disable'}`, {
      method: 'POST',
    });
    if (res.ok) await loadSources(true);
  };

  const handleTest = async (source: ConfiguredSource) => {
    setTesting((t) => ({ ...t, [source.source_id]: true }));
    setTestResults((r) => ({ ...r, [source.source_id]: undefined }));
    try {
      const res = await fetch(`/api/v1/sources/${encodeURIComponent(source.source_id)}/test`, { method: 'POST' });
      const data = await res.json().catch(() => null);
      setTestResults((r) => ({
        ...r,
        [source.source_id]: data ? { ok: Boolean(data.ok), message: data.message || data.detail || 'Connection check failed.' } : { ok: false, message: 'No response from backend.' },
      }));
    } catch {
      setTestResults((r) => ({ ...r, [source.source_id]: { ok: false, message: 'Network error while testing source.' } }));
    } finally {
      setTesting((t) => ({ ...t, [source.source_id]: false }));
    }
  };

  const handleSync = async (source: ConfiguredSource) => {
    setSyncing((s) => ({ ...s, [source.source_id]: true }));
    setSyncResults((r) => ({ ...r, [source.source_id]: undefined }));
    setTestResults((r) => ({ ...r, [source.source_id]: undefined }));
    try {
      const res = await fetch(`/api/v1/sources/${encodeURIComponent(source.source_id)}/sync`, { method: 'POST' });
      const data: (SourceSyncResult & { detail?: string }) | null = await res.json().catch(() => null);
      if (!res.ok) {
        setSyncResults((r) => ({
          ...r,
          [source.source_id]: {
            status: 'ERROR',
            message: data?.message || data?.detail || 'Sync failed.',
            inserted: 0,
            updated: 0,
          } as SourceSyncResult,
        }));
      } else if (data) {
        setSyncResults((r) => ({ ...r, [source.source_id]: data }));
        if (data.inserted > 0 || data.updated > 0) onImportSuccess();
      }
      await loadSources(true);
    } catch {
      setSyncResults((r) => ({
        ...r,
        [source.source_id]: { status: 'ERROR', message: 'Network error while syncing source.', inserted: 0, updated: 0 } as SourceSyncResult,
      }));
    } finally {
      setSyncing((s) => ({ ...s, [source.source_id]: false }));
    }
  };

  const handleDelete = async (source: ConfiguredSource) => {
    if (!window.confirm(`Delete source "${source.name}"? Its collected bids remain in the database.`)) return;
    const res = await fetch(`/api/v1/sources/${encodeURIComponent(source.source_id)}`, { method: 'DELETE' });
    if (res.ok || res.status === 204) {
      setOpenRuns((r) => ({ ...r, [source.source_id]: undefined }));
      await loadSources(true);
    } else {
      setErrorMessage(`Failed to delete source: ${source.source_id}`);
    }
  };

  const toggleRuns = async (source: ConfiguredSource) => {
    if (openRuns[source.source_id] !== undefined) {
      setOpenRuns((r) => ({ ...r, [source.source_id]: undefined }));
      return;
    }
    if (runsLoading[source.source_id]) return;
    setRunsLoading((r) => ({ ...r, [source.source_id]: true }));
    try {
      const res = await fetch(`/api/v1/sources/${encodeURIComponent(source.source_id)}/runs?limit=10`);
      if (res.ok) {
        const runs = (await res.json()) as SourceRunRow[];
        setOpenRuns((r) => ({ ...r, [source.source_id]: runs }));
      }
    } catch {
      console.error('Failed to load run history', source.source_id);
    } finally {
      setRunsLoading((r) => ({ ...r, [source.source_id]: false }));
    }
  };

  const schedulerEnabled = meta?.scheduler?.enabled ?? false;

  return (
    <div className="card-panel">
      <div className="panel-header">
        <div>
          <h2 className="panel-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: 'var(--accent-cyan)' }}>
              <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
              <circle cx="12" cy="12" r="3" />
            </svg>
            Data Sources — Configurable Bid-Source Registry
          </h2>
          <p className="panel-subtitle" style={{ maxWidth: '720px', lineHeight: 1.45 }}>
            Register any public tender feed (RSS/Atom, JSON API, HTML listing) as a source. Every request is
            SSRF-guarded to public addresses only, credentials are referenced by environment-variable name, and
            each <strong>Sync</strong> runs the exact same validation → normalization → dedupe → 11-product
            matching → notification pipeline used elsewhere on this page.
          </p>
        </div>
        <button className="btn-secondary btn-sm" onClick={openCreate} disabled={Boolean(editing)}>
          + Add Source
        </button>
      </div>

      <div className="alert-info" style={{ marginBottom: '1.25rem' }}>
        <strong>Scheduled collection:</strong>{' '}
        {schedulerEnabled
          ? 'Enabled for eligible sources at their configured interval.'
          : 'Off by default. Sources only collect when you press Sync (recommended) — enable SOURCE_SCHEDULER_ENABLED=true in the backend to automate.'}
      </div>

      {errorMessage && (
        <div className="alert-error" style={{ marginBottom: '1rem' }}>
          {errorMessage}
        </div>
      )}

      {loading ? (
        <div style={{ padding: '1.5rem', textAlign: 'center', color: 'var(--text-muted)' }}>Loading sources...</div>
      ) : sources.length === 0 && editing === '' ? (
        <div className="empty-state">
          <div className="empty-title">No configured sources yet</div>
          <div className="empty-desc">
            Register an RSS/Atom feed, a JSON API, or an HTML listing to start collecting bids from additional sources.
            Press &quot;Add Source&quot; above to begin.
          </div>
        </div>
      ) : (
        <div className="table-responsive">
          <table className="feed-table">
            <thead>
              <tr>
                <th>Source</th>
                <th>Type / Adapter</th>
                <th>Last Run</th>
                <th>Totals</th>
                <th>Scheduled</th>
                <th style={{ width: '240px' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((source) => {
                const badge = statusBadge(source.status);
                const run = syncResults[source.source_id];
                const test = testResults[source.source_id];
                const staticRuns = openRuns[source.source_id];
                return (
                  <React.Fragment key={source.source_id}>
                    <tr>
                      <td>
                        <div style={{ fontWeight: 600, color: 'var(--text-main)' }}>{source.name}</div>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                          <code>{source.source_id}</code>
                          {source.has_credentials && (
                            <span style={{ marginLeft: '0.35rem', color: 'var(--accent-amber)' }} title="Uses a credential from an env var">key</span>
                          )}
                        </div>
                        <div style={{ display: 'flex', gap: '0.35rem', marginTop: '0.3rem', flexWrap: 'wrap' }}>
                          <span className={`badge ${badge.cls}`}>{badge.label}</span>
                          <span className={`badge ${source.enabled ? 'badge-match' : 'badge-review'}`}>
                            {source.enabled ? 'ENABLED' : 'DISABLED'}
                          </span>
                        </div>
                        {source.last_error && (
                          <div style={{ marginTop: '0.3rem', fontSize: '0.72rem', color: 'var(--accent-amber)', maxWidth: '320px' }} title={source.last_error}>
                            {source.last_error}
                          </div>
                        )}
                      </td>
                      <td>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-main)' }}>{source.source_type}</div>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{source.adapter_label}</div>
                        {source.base_url && (
                          <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>{source.base_url}</div>
                        )}
                      </td>
                      <td>
                        <div style={{ fontSize: '0.74rem', color: 'var(--text-main)' }}>
                          {source.status === 'IDLE' && !source.last_attempt_at
                            ? 'Never'
                            : `${source.last_discovered} found · ${source.last_inserted} new · ${source.last_updated} updated`}
                        </div>
                        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                          {source.last_attempt_at ? formatWhen(source.last_attempt_at) : '—'}
                        </div>
                        <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>
                          {source.last_duplicates} dup · {source.last_rejected} rejected
                        </div>
                      </td>
                      <td>
                        <div style={{ fontSize: '0.74rem', color: 'var(--text-main)' }}>
                          {source.total_runs} runs · {source.total_inserted} inserted
                        </div>
                        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                          {source.total_updated} upd · {source.total_duplicates} dup · {source.total_rejected} rej
                        </div>
                      </td>
                      <td>
                        <div style={{ fontSize: '0.74rem', color: 'var(--text-main)' }}>
                          {source.enabled ? `every ${source.collection_interval_minutes} min` : '—'}
                        </div>
                        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                          {source.next_run_at ? `next: ${formatWhen(source.next_run_at)}` : '—'}
                        </div>
                      </td>
                      <td>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
                          <button
                            className="btn-secondary btn-sm"
                            disabled={testing[source.source_id]}
                            onClick={() => handleTest(source)}
                          >
                            {testing[source.source_id] ? 'Testing...' : 'Test'}
                          </button>
                          <button
                            className="btn-primary btn-sm"
                            disabled={!source.enabled || syncing[source.source_id]}
                            onClick={() => handleSync(source)}
                          >
                            {syncing[source.source_id] ? 'Syncing...' : 'Sync'}
                          </button>
                          <button className="btn-secondary btn-sm" disabled={Boolean(editing)} onClick={() => openEdit(source)}>
                            Edit
                          </button>
                          <button className="btn-secondary btn-sm" disabled={syncing[source.source_id]} onClick={() => toggleRuns(source)}>
                            {staticRuns !== undefined ? 'Hide Runs' : runsLoading[source.source_id] ? 'Runs...' : 'Runs'}
                          </button>
                          <button
                            className="btn-secondary btn-sm"
                            onClick={() => handleToggle(source, !source.enabled)}
                            title={source.enabled ? 'Pause scheduled+manual collection' : 'Resume collection'}
                          >
                            {source.enabled ? 'Disable' : 'Enable'}
                          </button>
                          <button
                            className="btn-secondary btn-sm"
                            style={{ color: 'var(--accent-amber)' }}
                            onClick={() => handleDelete(source)}
                          >
                            Delete
                          </button>
                        </div>
                        {test && (
                          <div
                            className={test.ok ? 'alert-info' : 'alert-warning'}
                            style={{ marginTop: '0.5rem', marginBottom: 0 }}
                          >
                            {test.ok ? 'Connection check passed: ' : 'Connection check failed: '}
                            {test.message}
                          </div>
                        )}
                        {run && (
                          <div style={{ marginTop: '0.6rem' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.75rem', color: 'var(--text-main)' }}>
                              <span className={`badge ${statusBadge(run.status).cls}`}>{run.status}</span>
                              <span>{run.message}</span>
                            </div>
                            <div className="sync-result-grid" style={{ marginTop: '0.5rem' }}>
                              <div className="sync-result-item">
                                <span className="sync-result-item-label">Discovered</span>
                                <div className="sync-result-item-value">{run.discovered}</div>
                              </div>
                              <div className="sync-result-item">
                                <span className="sync-result-item-label">Inserted</span>
                                <div className="sync-result-item-value" style={{ color: 'var(--accent-green)' }}>{run.inserted}</div>
                              </div>
                              <div className="sync-result-item">
                                <span className="sync-result-item-label">Updated</span>
                                <div className="sync-result-item-value" style={{ color: 'var(--accent-cyan)' }}>{run.updated}</div>
                              </div>
                              <div className="sync-result-item">
                                <span className="sync-result-item-label">Duplicates</span>
                                <div className="sync-result-item-value">{run.duplicates}</div>
                              </div>
                              <div className="sync-result-item">
                                <span className="sync-result-item-label">Rejected</span>
                                <div className="sync-result-item-value" style={{ color: 'var(--accent-amber)' }}>{run.rejected}</div>
                              </div>
                              <div className="sync-result-item">
                                <span className="sync-result-item-label">Duration</span>
                                <div className="sync-result-item-value">{run.duration_seconds}s</div>
                              </div>
                            </div>
                            {(run.errors ?? []).length > 0 && (
                              <div className="alert-warning" style={{ marginTop: '0.5rem', marginBottom: 0 }}>
                                {(run.errors ?? []).slice(0, 5).map((e, i) => (
                                  <div key={i} style={{ fontSize: '0.72rem' }}>{e.field}: {e.message}</div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                    {staticRuns !== undefined && (
                      <tr>
                        <td colSpan={6} style={{ background: 'var(--bg-surface)' }}>
                          <RunHistory rows={staticRuns} />
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {editing !== '' && (
        <div style={{ marginTop: '1.25rem', paddingTop: '1.25rem', borderTop: '1px solid var(--border-color)' }}>
          <div className="section-title-sm" style={{ marginBottom: '0.75rem' }}>
            {editing === '_new' ? 'Add Data Source' : `Edit Source: ${editing}`}
          </div>

          <div className="field-group">
            <label className="field-label">Adapter Type</label>
            <select
              className="form-input"
              value={form.adapter_key}
              onChange={(e) => selectAdapter(e.target.value)}
              disabled={Boolean(editing !== '_new')}
            >
              {adapters.map((adapter) => (
                <option key={adapter.adapter_key} value={adapter.adapter_key}>
                  {adapter.adapter_label} — {adapter.source_types.join(', ')}
                </option>
              ))}
            </select>
            {currentAdapter(adapters, form.adapter_key)?.requires_browser && (
              <span className="field-hint">
                This adapter drives a browser (Playwright) to fetch the listing. It is registered but not part of the
                MVP&apos;s live-verified set — use the plain HTML listing adapter unless a JS-rendered page is required.
              </span>
            )}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
            {editing === '_new' && (
              <div className="field-group">
                <label className="field-label">Source ID <span style={{ color: 'var(--text-muted)' }}>(unique, lowercase)</span></label>
                <input
                  type="text"
                  className="form-input"
                  value={form.source_id}
                  onChange={(e) => setForm((f) => ({ ...f, source_id: e.target.value, name: f.name || e.target.value }))}
                  placeholder="e.g. my-ministry-rss"
                />
              </div>
            )}
            <div className="field-group">
              <label className="field-label">Display Name</label>
              <input
                type="text"
                className="form-input"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="Human-readable source name"
              />
            </div>
            <div className="field-group">
              <label className="field-label">Collection Interval (minutes)</label>
              <input
                type="number"
                min={5}
                max={10080}
                className="form-input"
                value={form.collection_interval_minutes}
                onChange={(e) => setForm((f) => ({ ...f, collection_interval_minutes: e.target.value }))}
              />
              <span className="field-hint">Used only when automatic scheduling is enabled.</span>
            </div>
          </div>

          <div className="field-group">
            <label className="field-label">Base URL (optional, public URL only)</label>
            <input
              type="text"
              className="form-input"
              value={form.base_url}
              onChange={(e) => setForm((f) => ({ ...f, base_url: e.target.value }))}
              placeholder="https://…"
            />
          </div>

          <div className="field-group">
            <label className="field-label">Adapter Configuration (JSON)</label>
            <textarea
              className="form-input"
              rows={12}
              style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}
              value={form.configJson}
              onChange={(e) => setForm((f) => ({ ...f, configJson: e.target.value }))}
              spellCheck={false}
            />
            <span className="field-hint">{CONFIG_HINTS[form.adapter_key] ?? 'Configuration accepted by the selected adapter.'}</span>
          </div>

          <div className="field-group">
            <label className="field-label">Notes (optional)</label>
            <input
              type="text"
              className="form-input"
              value={form.notes}
              onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
            />
          </div>

          {formError && (
            <div className="alert-error" style={{ marginBottom: 0, marginTop: '0.5rem' }}>{formError}</div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.6rem', marginTop: '1rem' }}>
            <button className="btn-secondary btn-sm" onClick={cancelEdit} disabled={saving}>
              Cancel
            </button>
            <button className="btn-primary btn-sm" onClick={handleSave} disabled={saving}>
              {saving ? 'Saving...' : editing === '_new' ? 'Create Source' : 'Save Changes'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

function emptyForm() {
  return {
    source_id: '',
    name: '',
    adapter_key: 'json_api',
    source_type: 'json_api',
    base_url: '',
    collection_interval_minutes: '60',
    notes: '',
    configJson: '{}',
  };
}

function currentAdapter(adapters: AdapterMeta[], adapterKey: string): AdapterMeta | undefined {
  return adapters.find((a) => a.adapter_key === adapterKey);
}

function statusBadge(status: string): { cls: string; label: string } {
  const ok = ['SUCCESS', 'PARTIAL', 'PREVIEW'];
  const bad = ['ERROR', 'FAILED', 'BLOCKED', 'NO_RECORDS'];
  const warn = ['CONFIG_ERROR', 'NEEDS_ATTENTION', 'BUSY', 'SKIPPED'];
  let cls = 'badge-review';
  if (ok.includes(status)) cls = 'badge-match';
  else if (bad.includes(status)) cls = 'badge-urgent';
  else if (warn.includes(status)) cls = 'badge-review';
  if (status === 'RUNNING') cls = 'badge-review';
  return { cls, label: `STATUS: ${status}` };
}

function formatWhen(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

const CONFIG_TEMPLATES: Record<string, string> = {
  rss_feed: JSON.stringify(
    {
      url: 'https://public-tenders.example.gov.in/feed.xml',
      max_records: 200,
      max_retries: 2,
      timeout_seconds: 30,
    },
    null,
    2,
  ),
  json_api: JSON.stringify(
    {
      url: 'https://public-tenders.example.gov.in/api/opportunities',
      records_path: 'items',
      field_map: {
        title: 'title',
        source_url: 'link',
        closing_date: 'deadline',
        organisation: 'agency',
        category: 'category',
        gem_bid_id: 'id',
      },
      page_param: 'page',
      page_size_param: 'page_size',
      page_size: 100,
      max_pages: 5,
      max_records: 500,
      timeout_seconds: 30,
      max_retries: 2,
      auth: {
        type: 'bearer',
        env_ref: 'MY_SOURCE_TOKEN',
      },
    },
    null,
    2,
  ),
  html_listing: JSON.stringify(
    {
      url: 'https://public-tenders.example.gov.in/listing',
      row_selector: 'tr.bid-row',
      field_map: {
        title: 'td.title@text',
        source_url: 'td a@href',
        closing_date: 'td.due@text',
        organisation: 'td.org@text',
      },
      pagination: { param: 'page', next_selector: 'a.next@href' },
      max_pages: 5,
      max_records: 300,
      timeout_seconds: 30,
      max_retries: 2,
    },
    null,
    2,
  ),
  playwright_html: JSON.stringify(
    {
      url: 'https://public-tenders.example.gov.in/listing',
      row_selector: 'tr.bid-row',
      field_map: {
        title: 'td.title@text',
        source_url: 'td a@href',
        closing_date: 'td.due@text',
        organisation: 'td.org@text',
      },
      max_pages: 3,
      max_records: 200,
      timeout_seconds: 45,
      max_retries: 2,
    },
    null,
    2,
  ),
};

const CONFIG_HINTS: Record<string, string> = {
  rss_feed:
    'url: the RSS 2.0 or Atom feed (SSRF-guarded). Optional: max_records, timeout_seconds (5–120), max_retries (0–5).',
  json_api:
    'url + records_path (dotted path to the records list) + field_map (canonical field → source field). Optional: ' +
    'page_param/page_size_param/page_size/max_pages/max_records; auth = {type: bearer|header|query, env_ref} referencing an environment variable.',
  html_listing:
    'url + row_selector + field_map using "css" or "css@attr" selectors (title and a source_url selector are expected). ' +
    'Optional: pagination = {param, next_selector} for query-param or next-link pagination. Rows whose source link is not public are dropped whole.',
  playwright_html:
    'Rendered with a headless browser after the same SSRF checks. Same selectors as html_listing. Not part of the live-verified MVP adapter set.',
};

function RunHistory({ rows }: { rows: SourceRunRow[] }) {
  const cellMuted: React.CSSProperties = { fontSize: '0.75rem', color: 'var(--text-dim)' };
  const cellMain: React.CSSProperties = { fontSize: '0.75rem', color: 'var(--text-main)' };
  const cellOk: React.CSSProperties = { fontSize: '0.75rem', color: 'var(--accent-green)', fontWeight: 600 };
  const cellWarn: React.CSSProperties = { fontSize: '0.75rem', color: 'var(--accent-amber)' };
  if (rows.length === 0) {
    return <div className="empty-state"><div className="empty-title">No runs recorded</div></div>;
  }
  return (
    <div className="table-responsive">
      <table className="feed-table">
        <thead>
          <tr>
            <th>Trigger</th>
            <th>Status</th>
            <th>Discovered</th>
            <th>Validated</th>
            <th>Inserted</th>
            <th>Updated</th>
            <th>Duplicates</th>
            <th>Rejected</th>
            <th>Started</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((run) => (
            <tr key={run.id}>
              <td style={cellMuted}>{run.trigger}</td>
              <td style={cellMain}><span className={`badge ${statusBadgeForRun(run.status).cls}`}>{run.status}</span></td>
              <td style={cellMuted}>{run.discovered}</td>
              <td style={cellMuted}>{run.validated}</td>
              <td style={cellOk}>{run.inserted}</td>
              <td style={cellMain}>{run.updated}</td>
              <td style={cellMuted}>{run.duplicates}</td>
              <td style={cellWarn}>{run.rejected}</td>
              <td style={cellMuted}>{formatWhen(run.started_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function statusBadgeForRun(status: string): { cls: string } {
  const ok = ['SUCCESS', 'PARTIAL'];
  const bad = ['ERROR', 'FAILED', 'BLOCKED', 'NO_RECORDS'];
  if (ok.includes(status)) return { cls: 'badge-match' };
  if (bad.includes(status)) return { cls: 'badge-urgent' };
  return { cls: 'badge-review' };
}