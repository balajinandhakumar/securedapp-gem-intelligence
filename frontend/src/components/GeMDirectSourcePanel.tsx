import React, { useCallback, useEffect, useState } from 'react';

interface GeMDirectSourcePanelProps {
  onImportSuccess: () => void;
}

interface GeMDirectStatus {
  source: string;
  provider: string;
  configured: boolean;
  status: string;
  allowed_hosts: string[];
  listing_url: string;
  timeout_seconds: number;
  max_retries: number;
  request_interval_seconds: number;
  max_urls_per_run: number;
  scheduler_enabled: boolean;
  scheduler_interval_minutes: number;
  blocked: boolean;
  is_running: boolean;
  requires_credentials: boolean;
  default_keywords?: string[];
  pagination_enabled?: boolean;
  max_pages?: number;
  max_pages_unlimited?: boolean;
  records_per_page?: number;
  keyword_filter_enabled?: boolean;
  detail_enrichment_enabled?: boolean;
  max_detail_pages?: number;
  max_consecutive_page_failures?: number;
  scheduler_note?: string;
  scheduler_next_run?: string | null;
  last_run?: {
    status?: string;
    last_run_id?: string | null;
    last_run_time?: string | null;
  };
  last_run_stats?: {
    rows_seen?: number;
    received?: number;
    validated?: number;
    rejected?: number;
    inserted?: number;
    updated?: number;
    duplicates?: number;
    intelligence_processed?: number;
    notifications_created?: number;
    duration_seconds?: number;
    stop_reason?: string | null;
    limit_reached?: boolean;
  };
}

interface ExtractedFieldReport {
  source_url?: string | null;
  extracted_fields: string[];
  missing_fields: string[];
}

interface GeMDirectResult {
  status: string;
  message: string;
  collection_method?: string | null;
  requested_urls: number;
  rejected_urls: number;
  scrape_errors: number;
  received: number;
  validated: number;
  rejected: number;
  inserted: number;
  updated: number;
  duplicates: number;
  intelligence_processed: number;
  notifications_created: number;
  duration_seconds: number;
  pages_visited?: number;
  pages_available?: number | null;
  records_available?: number | null;
  rows_seen?: number;
  duplicate_rows?: number;
  unique_bids?: number;
  parser_failures?: number;
  page_failures?: number;
  detail_enriched?: number;
  detail_failures?: number;
  keyword_skipped?: number;
  stop_reason?: string | null;
  limit_reached?: boolean;
  blocked_stage?: string | null;
  http_status?: number | null;
  errors: Array<{ field: string; message: string }>;
  extracted_fields: ExtractedFieldReport[];
}

/**
 * Direct public GeM bid collector control for the Data Source page.
 *
 * This collector talks to GeM's own public pages directly. It uses no third-party
 * tender data provider, needs no API key and no credentials, and only ever
 * requests the host-allowlisted public GeM pages listed in the backend status.
 * Collection runs are triggered here manually and, when the scheduler is
 * enabled, also once per configured interval by the backend; both paths use
 * the same pipeline and never overlap.
 */
export const GeMDirectSourcePanel: React.FC<GeMDirectSourcePanelProps> = ({ onImportSuccess }) => {
  const [status, setStatus] = useState<GeMDirectStatus | null>(null);
  const [keywords, setKeywords] = useState('');
  const [applyKeywordFilter, setApplyKeywordFilter] = useState(false);
  const [previewOnly, setPreviewOnly] = useState(true);
  const [pageBudget, setPageBudget] = useState('');
  const [fetching, setFetching] = useState(false);
  const [result, setResult] = useState<GeMDirectResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/ingestion/gem-direct/status');
      if (res.ok) {
        setStatus(await res.json());
      }
    } catch (err) {
      console.error('Failed to fetch GeM direct collector status', err);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const handleFetch = async () => {
    setFetching(true);
    setErrorMessage(null);
    setResult(null);

    const payload: Record<string, unknown> = {
      preview: previewOnly,
      allow_update_duplicates: true,
      auto_notify: true,
      apply_keyword_filter: applyKeywordFilter,
    };
    if (keywords.trim()) {
      payload.keywords = keywords.split(',').map((k) => k.trim()).filter(Boolean);
    }
    if (pageBudget.trim()) {
      const parsedBudget = Number(pageBudget.trim());
      if (Number.isFinite(parsedBudget) && parsedBudget >= 0) {
        payload.max_pages = Math.floor(parsedBudget);
      }
    }

    try {
      const res = await fetch('/api/v1/ingestion/gem-direct/fetch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (res.ok) {
        setResult(data);
        if (!previewOnly && (data.inserted > 0 || data.updated > 0)) {
          onImportSuccess();
        }
      } else {
        setErrorMessage(data.detail || 'Direct GeM collection failed.');
      }
    } catch {
      setErrorMessage('Network error while communicating with the backend GeM direct collector.');
    } finally {
      setFetching(false);
      fetchStatus();
    }
  };

  const configured = status?.configured ?? false;
  const busy = fetching || status?.is_running;
  const blocked = status?.blocked ?? false;
  const badgeClass = blocked
    ? 'badge-urgent'
    : busy
      ? 'badge-review'
      : configured
        ? 'badge-match'
        : 'badge-review';
  const badgeText = blocked
    ? 'STATUS: BLOCKED BY SOURCE'
    : busy
      ? 'COLLECTING...'
      : configured
        ? 'STATUS: READY'
        : 'STATUS: NOT CONFIGURED';
  const lastRun = status?.last_run;
  const lastRunTime = lastRun?.last_run_time ? new Date(lastRun.last_run_time).toLocaleString() : null;
  const lastStats = status?.last_run_stats;

  return (
    <div className="card-panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
            <span className={`badge ${badgeClass}`}>{badgeText}</span>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Data Source: <strong>Direct GeM Public Collector</strong>
            </span>
          </div>
          <h2 className="panel-title">Data Source: GeM — Direct Public Bid Collector</h2>
          <p className="panel-subtitle" style={{ maxWidth: '680px', lineHeight: 1.45 }}>
            Collects bid records straight from GeM&apos;s own public pages. No third-party tender data provider is
            involved, and <strong>no API key, login, or credential of any kind is required or accepted</strong>. Only the
            host-allowlisted public GeM pages below are ever requested, at a low request rate. If GeM refuses collection
            the run stops immediately and no attempt is made to work around it.
          </p>
        </div>

        <div
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-color)',
            borderRadius: '0.5rem',
            padding: '0.75rem 1rem',
            fontSize: '0.78rem',
            minWidth: '230px',
          }}
        >
          <div style={{ color: 'var(--text-muted)', marginBottom: '0.3rem' }}>Collector Status:</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem', fontSize: '0.74rem' }}>
            <div>Provider: <code style={{ color: 'var(--accent-cyan)' }}>{status?.provider || '—'}</code></div>
            <div>Credentials: <code style={{ color: 'var(--accent-green)' }}>None required</code></div>
            <div>Allowed hosts: <code style={{ color: 'var(--accent-green)' }}>{(status?.allowed_hosts || []).join(', ') || '—'}</code></div>
            <div>Listing: <code style={{ color: 'var(--text-dim)' }}>{status?.listing_url || '—'}</code></div>
            <div>Max URLs / run: <code style={{ color: 'var(--text-dim)' }}>{status?.max_urls_per_run ?? '—'}</code></div>
            <div>
              Pagination:{' '}
              <code style={{ color: 'var(--text-dim)' }}>
                {status?.pagination_enabled
                  ? `${status.records_per_page ?? 10} rows/page, budget ${
                      status.max_pages_unlimited ? 'unlimited' : `${status.max_pages ?? '—'} pages`
                    }`
                  : 'Off (page 1 only)'}
              </code>
            </div>
            <div>Request interval: <code style={{ color: 'var(--text-dim)' }}>{status?.request_interval_seconds ?? '—'}s</code></div>
            <div>Timeout / retries: <code style={{ color: 'var(--text-dim)' }}>{status?.timeout_seconds ?? '—'}s / {status?.max_retries ?? '—'}</code></div>
            <div>
              Scheduler:{' '}
              <code style={{ color: status?.scheduler_enabled ? 'var(--accent-green)' : 'var(--accent-amber)' }}>
                {status?.scheduler_enabled
                  ? `Enabled (every ${status.scheduler_interval_minutes ?? 60} min)`
                  : 'Disabled (manual only)'}
              </code>
            </div>
            {status?.scheduler_enabled && (
              <div>
                Next scheduled run:{' '}
                <code style={{ color: 'var(--text-dim)' }}>
                  {status.scheduler_next_run
                    ? new Date(status.scheduler_next_run).toLocaleString()
                    : 'Not scheduled'}
                </code>
              </div>
            )}
            <div>
              Last run:{' '}
              <code style={{ color: 'var(--text-dim)' }}>
                {lastRun?.status ? `${lastRun.status}${lastRunTime ? ` — ${lastRunTime}` : ''}` : 'Never'}
              </code>
            </div>
            {lastStats && (
              <div>
                Latest statistics:{' '}
                <code style={{ color: 'var(--text-dim)' }}>
                  {[
                    `${lastStats.inserted ?? 0} new`,
                    `${lastStats.updated ?? 0} updated`,
                    `${lastStats.duplicates ?? 0} dup`,
                    `${lastStats.validated ?? 0} validated`,
                    `${lastStats.rejected ?? 0} rejected`,
                  ].join(', ')}
                  {typeof lastStats.limit_reached === 'boolean' &&
                    ` — ${lastStats.limit_reached ? 'truncated' : 'complete'}`}
                </code>
              </div>
            )}
          </div>
        </div>
      </div>

      <div style={{ marginTop: '1.25rem', paddingTop: '1rem', borderTop: '1px solid var(--border-color)' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.8rem', color: 'var(--text-main)' }}>
            <input
              type="checkbox"
              checked={applyKeywordFilter}
              onChange={(e) => setApplyKeywordFilter(e.target.checked)}
              style={{ accentColor: 'var(--accent-cyan)' }}
              disabled={!configured || busy}
            />
            <span>Filter to product keywords before matching</span>
          </label>

          {applyKeywordFilter && (
            <div className="field-group">
              <label className="field-label">Keyword Filter (Optional):</label>
              <input
                type="text"
                className="form-input"
                placeholder="Leave blank to use the configured product keywords"
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
                disabled={!configured || busy}
              />
              <span className="field-hint">
                Off by default. When enabled, records that match none of these terms are reported but are not
                sent to the matching engine or saved. A small vocabulary removes almost the whole public
                GeM set, so leaving this off collects the full listing and lets the product matching engine
                decide what is relevant.
              </span>
            </div>
          )}

          <div className="field-group">
            <label className="field-label">Page Budget (Optional):</label>
            <input
              type="number"
              min={0}
              className="form-input"
              placeholder={
                status?.max_pages_unlimited
                  ? 'Unlimited: walk every page the listing offers'
                  : `Default: ${status?.max_pages ?? '—'} pages`
              }
              value={pageBudget}
              onChange={(e) => setPageBudget(e.target.value)}
              disabled={!configured || busy}
            />
            <span className="field-hint">
              Maximum number of listing pages to walk in this run (0 = unlimited). GeM paginates 10 rows per
              page, so 100 pages is at most 1,000 bids. When the budget stops the walk early the result is
              reported with <code>limit_reached</code> so truncated coverage is never shown as complete.
            </span>
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.8rem', color: 'var(--text-main)' }}>
            <input
              type="checkbox"
              checked={previewOnly}
              onChange={(e) => setPreviewOnly(e.target.checked)}
              style={{ accentColor: 'var(--accent-cyan)' }}
              disabled={busy}
            />
            <span>Preview only (validate and report extracted fields without saving)</span>
          </label>

          <button className="btn-primary" disabled={!configured || busy} onClick={handleFetch}>
            {busy ? 'Fetching...' : 'Fetch GeM Bids'}
          </button>
        </div>

        {status?.scheduler_note && (
          <div className="alert-info" style={{ marginTop: '1rem', marginBottom: 0 }}>
            {status.scheduler_note}
          </div>
        )}

        {blocked && (
          <div className="alert-error" style={{ marginTop: '1rem', marginBottom: 0 }}>
            GeM refused automated collection and this run has been stopped. No bypass, retry storm, or access-control
            workaround is attempted. Wait for the block to clear before the next manual fetch.
          </div>
        )}

        {!configured && (
          <div className="alert-info" style={{ marginTop: '1rem', marginBottom: 0 }}>
            Direct GeM collection: Not Configured. Set <code>GEM_DIRECT_ENABLED=true</code> and{' '}
            <code>GEM_DIRECT_ALLOWED_HOSTS</code> in the backend environment to enable the collector. No credentials are
            involved.
          </div>
        )}

        {result && (
          <div style={{ marginTop: '1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.6rem', flexWrap: 'wrap', gap: '0.5rem' }}>
              <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--text-main)' }}>{result.message}</span>
              <span className={`badge ${result.status === 'SUCCESS' ? 'badge-match' : result.status === 'BLOCKED' ? 'badge-urgent' : 'badge-review'}`}>
                Status: {result.status}
              </span>
            </div>
            <div className="sync-result-grid">
              <div className="sync-result-item">
                <span className="sync-result-item-label">Collection Method</span>
                <div className="sync-result-item-value">{result.collection_method || '—'}</div>
              </div>
              <div className="sync-result-item">
                <span className="sync-result-item-label">Pages Walked</span>
                <div className="sync-result-item-value">
                  {result.pages_visited ?? '—'}
                  {result.pages_available != null ? ` / ${result.pages_available}` : ''}
                </div>
              </div>
              <div className="sync-result-item">
                <span className="sync-result-item-label">Rows Found</span>
                <div className="sync-result-item-value">
                  {result.rows_seen ?? '—'}
                  {result.records_available != null ? ` of ${result.records_available} offered` : ''}
                </div>
              </div>
              <div className="sync-result-item">
                <span className="sync-result-item-label">Unique Bids</span>
                <div className="sync-result-item-value">{result.unique_bids ?? '—'}</div>
              </div>
              <div className="sync-result-item">
                <span className="sync-result-item-label">Received</span>
                <div className="sync-result-item-value">{result.received}</div>
              </div>
              <div className="sync-result-item">
                <span className="sync-result-item-label">Validated</span>
                <div className="sync-result-item-value" style={{ color: 'var(--accent-green)' }}>{result.validated}</div>
              </div>
              <div className="sync-result-item">
                <span className="sync-result-item-label">Rejected</span>
                <div className="sync-result-item-value" style={{ color: 'var(--accent-amber)' }}>{result.rejected}</div>
              </div>
              <div className="sync-result-item">
                <span className="sync-result-item-label">Inserted</span>
                <div className="sync-result-item-value" style={{ color: 'var(--accent-green)' }}>{result.inserted}</div>
              </div>
              <div className="sync-result-item">
                <span className="sync-result-item-label">Updated</span>
                <div className="sync-result-item-value" style={{ color: 'var(--accent-cyan)' }}>{result.updated}</div>
              </div>
              <div className="sync-result-item">
                <span className="sync-result-item-label">Duplicates</span>
                <div className="sync-result-item-value">{result.duplicates}</div>
              </div>
              <div className="sync-result-item">
                <span className="sync-result-item-label">Unparsed Rows</span>
                <div className="sync-result-item-value" style={{ color: (result.parser_failures ?? 0) > 0 ? 'var(--accent-amber)' : undefined }}>
                  {result.parser_failures ?? 0}
                </div>
              </div>
              <div className="sync-result-item">
                <span className="sync-result-item-label">Failed Pages</span>
                <div className="sync-result-item-value" style={{ color: (result.page_failures ?? 0) > 0 ? 'var(--accent-amber)' : undefined }}>
                  {result.page_failures ?? 0}
                </div>
              </div>
              <div className="sync-result-item">
                <span className="sync-result-item-label">Matched &amp; Scored</span>
                <div className="sync-result-item-value">{result.intelligence_processed}</div>
              </div>
              <div className="sync-result-item">
                <span className="sync-result-item-label">Notifications</span>
                <div className="sync-result-item-value">{result.notifications_created}</div>
              </div>
              <div className="sync-result-item">
                <span className="sync-result-item-label">Duration</span>
                <div className="sync-result-item-value">{result.duration_seconds}s</div>
              </div>
            </div>

            {result.limit_reached && (
              <div className="alert-info" style={{ marginTop: '0.75rem', marginBottom: 0 }}>
                Coverage was truncated by the page budget: {result.pages_visited ?? 0} of{' '}
                {result.pages_available ?? '?'} available page(s) were walked, covering{' '}
                {result.rows_seen ?? 0} of {result.records_available ?? '?'} record(s) the listing offers. Raise
                the page budget or run again to collect the rest — this run is not a complete set.
              </div>
            )}

            {!result.limit_reached && result.pages_available != null && (result.pages_visited ?? 0) >= result.pages_available && (
              <div className="alert-info" style={{ marginTop: '0.75rem', marginBottom: 0 }}>
                The whole result set was walked: {result.pages_visited} of {result.pages_available} page(s),
                covering {result.rows_seen ?? 0} of {result.records_available ?? '?'} record(s) the listing
                offered at run time (stop reason: {result.stop_reason || 'unknown'}).
              </div>
            )}

            {result.blocked_stage && (
              <div className="alert-error" style={{ marginTop: '0.75rem', marginBottom: 0 }}>
                Collection stopped at the <code>{result.blocked_stage}</code> stage
                {result.http_status ? ` (HTTP ${result.http_status})` : ''}. Nothing was persisted.
              </div>
            )}

            {(result.extracted_fields ?? []).length > 0 && (
              <div style={{ marginTop: '1rem' }}>
                <div className="section-title-sm" style={{ marginBottom: '0.35rem' }}>Extracted Fields</div>
                {(result.extracted_fields ?? []).slice(0, 5).map((report, idx) => (
                  <div key={idx} style={{ fontSize: '0.74rem', color: 'var(--text-muted)', marginBottom: '0.4rem', lineHeight: 1.5 }}>
                    <code style={{ color: 'var(--accent-cyan)' }}>{report.source_url || 'n/a'}</code>
                    <div>
                      <span style={{ color: 'var(--accent-green)' }}>Found:</span>{' '}
                      {(report.extracted_fields ?? []).length ? (report.extracted_fields ?? []).join(', ') : 'none'}
                    </div>
                    <div>
                      <span style={{ color: 'var(--text-dim)' }}>Not on page:</span>{' '}
                      {(report.missing_fields ?? []).length ? (report.missing_fields ?? []).join(', ') : 'none'}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {(result.errors ?? []).length > 0 && (
              <div className="alert-warning" style={{ marginTop: '0.75rem', marginBottom: 0 }}>
                {(result.errors ?? []).slice(0, 5).map((e, i) => (
                  <div key={i}>{e.field}: {e.message}</div>
                ))}
              </div>
            )}
          </div>
        )}

        {errorMessage && (
          <div className="alert-error" style={{ marginTop: '1rem', marginBottom: 0 }}>
            {errorMessage}
          </div>
        )}
      </div>
    </div>
  );
};
