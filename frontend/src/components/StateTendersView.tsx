import React, { useCallback, useEffect, useState } from 'react';
import {
  ConfiguredSource,
  SourceStatus,
} from '../types';

interface StateTendersViewProps {
  onSyncSource: (sourceId: string) => Promise<void>;
}

/**
 * Unified State Government Tenders collection page.
 *
 * Displays all configured state/UT GePNIC sources in a single, business-focused
 * view. Each source row shows its live status, last sync statistics, and
 * provides a manual sync trigger. States that have not yet been configured
 * are shown as "Not Configured".
 *
 * The GeM Direct Public Collector is displayed separately on the Data Source
 * page and is NOT shown here.
 */
export const StateTendersView: React.FC<StateTendersViewProps> = ({
  onSyncSource,
}) => {
  const [sources, setSources] = useState<ConfiguredSource[]>([]);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const loadSources = useCallback(async () => {
    setLoading(true);
    setErrorMessage(null);
    try {
      const res = await fetch('/api/v1/sources');
      if (res.ok) {
        const allSources: ConfiguredSource[] = await res.json();
        // Filter to show only state government sources (exclude GeM direct)
        const stateSources = allSources.filter(
          (s) => s.source_id !== 'gem_direct'
        );
        setSources(stateSources.sort((a, b) => a.name.localeCompare(b.name)));
      } else {
        setErrorMessage('Failed to load source configurations.');
      }
    } catch (err) {
      console.error('Failed to fetch sources', err);
      setErrorMessage('Unable to load source configuration.');
    } finally {
      setLoading(false);
    }
  }, []);

  const handleSync = async (sourceId: string) => {
    setLoading(true);
    try {
      const res = await fetch(`/api/v1/sources/${sourceId}/sync`, {
        method: 'POST',
      });
      if (res.ok) {
        const result = await res.json();
        setSources((prev) =>
          prev.map((s) =>
            s.source_id === sourceId
              ? {
                  ...s,
                  status: (result.status as SourceStatus) || s.status,
                  last_attempt_at: new Date().toISOString(),
                  last_discovered: result.discovered ?? s.last_discovered,
                  last_validated: result.validated ?? s.last_validated,
                  last_rejected: result.rejected ?? s.last_rejected,
                  last_inserted: result.inserted ?? s.last_inserted,
                  last_updated: result.updated ?? s.last_updated,
                  last_duplicates: result.duplicates ?? s.last_duplicates,
                }
              : s
          )
        );
      } else {
        const errData = await res.json();
        setErrorMessage(
          errData.detail || 'Sync failed. Check the source configuration.'
        );
      }
    } catch (err) {
      setErrorMessage('Unable to trigger source sync.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSources();
  }, [loadSources]);

  const statusBadgeClass = (status: SourceStatus | undefined): string => {
    const statusMap: Record<string, string> = {
      IDLE: 'badge-info',
      RUNNING: 'badge-info',
      SUCCESS: 'badge-match',
      PARTIAL: 'badge-review',
      FAILED: 'badge-urgent',
      SKIPPED: 'badge-info',
      BUSY: 'badge-info',
      BLOCKED: 'badge-urgent',
      NO_RECORDS: 'badge-info',
      ERROR: 'badge-urgent',
      CONFIG_ERROR: 'badge-urgent',
      NEEDS_ATTENTION: 'badge-review',
      NOT_CONFIGURED: 'badge-info',
    };
    return `badge ${statusMap[status || 'IDLE'] || 'badge-info'}`;
  };

  if (loading) {
    return (
      <div className="card-panel">
        <div className="panel-header">
          <h2 className="panel-title">State Government Tenders</h2>
          <p className="panel-subtitle">
            Unified monitoring of state government e-procurement portals.
          </p>
        </div>
        <div className="empty-state">
          <div className="empty-title">Loading source status...</div>
        </div>
      </div>
    );
  }

  if (errorMessage) {
    return (
      <div className="card-panel">
        <div className="panel-header">
          <h2 className="panel-title">State Government Tenders</h2>
        </div>
        <div className="alert-error">{errorMessage}</div>
      </div>
    );
  }

  return (
    <div className="card-panel">
      <div className="panel-header">
        <div>
          <h2 className="panel-title">State Government Tenders</h2>
          <p className="panel-subtitle">
            Unified monitoring of state government e-procurement portals.
            Each state is an independent data source with its own collection
            schedule, checkpoint, and results.
          </p>
        </div>
        <button
          className="btn-primary btn-sm"
          onClick={() => {
            setLoading(true);
            loadSources().finally(() => setLoading(false));
          }}
        >
          {loading ? 'Refreshing...' : 'Refresh All Sources'}
        </button>
      </div>

      {sources.length === 0 && (
        <div className="empty-state">
          <div className="empty-title">No state sources configured</div>
          <div className="empty-desc">
            No state government tenders sources are currently configured. Add a
            new source via the Data Source management page.
          </div>
        </div>
      )}

      {sources.length > 0 && (
        <div className="table-responsive">
          <table className="feed-table">
            <thead>
              <tr>
                <th>State / Source</th>
                <th>Portal URL</th>
                <th>Status</th>
                <th>Last Sync</th>
                <th>Discovered</th>
                <th>Validated</th>
                <th>Inserted</th>
                <th>Updated</th>
                <th>Duplicates</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((source) => (
                <tr key={source.id}>
                  <td>
                    <div style={{ fontWeight: 600, color: 'var(--text-main)' }}>
                      {source.name}
                    </div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      {source.source_id}
                    </div>
                  </td>
                  <td style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    {source.base_url || 'Not configured'}
                  </td>
                  <td>
                    <span className={statusBadgeClass(source.status)}>
                      {source.status.replace(/_/g, ' ').toLowerCase()}
                    </span>
                  </td>
                  <td
                    style={{
                      fontSize: '0.75rem',
                      color: 'var(--text-muted)',
                    }}
                  >
                    {source.last_success_at ? (
                      <span>
                        {new Date(source.last_success_at).toLocaleString()}
                      </span>
                    ) : (
                      <span style={{ color: 'var(--text-muted)' }}>
                        Never synced
                      </span>
                    )}
                  </td>
                  <td style={{ fontSize: '0.75rem' }}>
                    {source.last_discovered}
                  </td>
                  <td style={{ fontSize: '0.75rem' }}>
                    {source.last_validated}
                  </td>
                  <td style={{ fontSize: '0.75rem' }}>
                    {source.last_inserted}
                  </td>
                  <td style={{ fontSize: '0.75rem' }}>
                    {source.last_updated}
                  </td>
                  <td style={{ fontSize: '0.75rem' }}>
                    {source.last_duplicates}
                  </td>
                  <td>
                    <button
                      className="btn-secondary btn-sm"
                      onClick={() => onSyncSource(source.source_id)}
                      disabled={loading}
                    >
                      Sync
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default StateTendersView;
