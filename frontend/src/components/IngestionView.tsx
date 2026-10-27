import React, { useEffect, useState } from 'react';
import { IngestionRun } from '../types';
import { GeMDirectSourcePanel } from './GeMDirectSourcePanel';
import { SourceManagementPanel } from './SourceManagementPanel';

interface IngestionViewProps {
  onImportSuccess: () => void;
}

interface ImportResponseData {
  run_id: string;
  status: string;
  total_records: number;
  created: number;
  updated: number;
  duplicates: number;
  failed: number;
  errors?: Array<{
    record_index: number;
    field: string;
    message: string;
  }>;
}

/**
 * Data Source & ingestion page.
 *
 * The preferred GeM data source is the direct public collector, driven by
 * `GeMDirectSourcePanel`. Manual dataset upload (JSON / CSV / XLSX) and the
 * ingestion audit trail are also available here.
 */
export const IngestionView: React.FC<IngestionViewProps> = ({ onImportSuccess }) => {
  const [allowUpdate, setAllowUpdate] = useState(true);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);

  const [importResult, setImportResult] = useState<ImportResponseData | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const [runs, setRuns] = useState<IngestionRun[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);

  useEffect(() => {
    fetchRuns();
  }, []);

  const fetchRuns = async () => {
    setLoadingRuns(true);
    try {
      const res = await fetch('/api/v1/ingestion/runs');
      if (res.ok) {
        const data = await res.json();
        setRuns(data);
      }
    } catch (err) {
      console.error('Failed to fetch ingestion runs', err);
    } finally {
      setLoadingRuns(false);
    }
  };

  const handleFileSelection = (file: File) => {
    setSelectedFile(file);
    setImportResult(null);
    setErrorMessage(null);
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFileSelection(e.target.files[0]);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileSelection(e.dataTransfer.files[0]);
    }
  };

  const handleUploadSubmit = async () => {
    if (!selectedFile) return;

    setUploading(true);
    setErrorMessage(null);
    setImportResult(null);

    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('allow_update', allowUpdate ? 'true' : 'false');

    const ext = selectedFile.name.split('.').pop()?.toLowerCase();
    if (ext && ['csv', 'json', 'xlsx'].includes(ext)) {
      formData.append('file_format', ext);
    }

    try {
      const res = await fetch('/api/v1/ingestion/import', {
        method: 'POST',
        body: formData,
      });

      if (res.ok) {
        const data: ImportResponseData = await res.json();
        setImportResult(data);
        setSelectedFile(null);
        fetchRuns();
        onImportSuccess();
      } else {
        const errData = await res.json();
        setErrorMessage(errData.detail || 'Failed to process file ingestion.');
      }
    } catch (err) {
      setErrorMessage('Network connection error while communicating with backend ingestion service.');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div>
      {/* Configurable multi-source registry: RSS/Atom feeds, JSON APIs, HTML listings */}
      <SourceManagementPanel onImportSuccess={onImportSuccess} />

      {/* Primary data source: direct public GeM collection, no third party */}
      <GeMDirectSourcePanel onImportSuccess={onImportSuccess} />

      {/* Manual Dataset File Upload Section */}
      <div className="card-panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: 'var(--accent-cyan)' }}>
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              Manual Dataset File Upload
            </h2>
            <p className="panel-subtitle">
              Upload GeM-formatted JSON, CSV, or XLSX files directly to the ingestion pipeline
            </p>
          </div>
        </div>

        {/* Upload Dropzone */}
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          style={{
            border: `2px dashed ${isDragging ? 'var(--accent-cyan)' : 'var(--border-color)'}`,
            background: isDragging ? 'rgba(0, 240, 255, 0.04)' : 'var(--bg-surface)',
            borderRadius: '0.5rem',
            padding: '1.5rem',
            textAlign: 'center',
            cursor: 'pointer',
            transition: 'all 0.15s ease',
            marginBottom: '1rem',
          }}
          onClick={() => document.getElementById('file-upload-input')?.click()}
        >
          <input
            id="file-upload-input"
            type="file"
            accept=".json,.csv,.xlsx"
            style={{ display: 'none' }}
            onChange={handleFileInputChange}
          />
          <svg
            width="28"
            height="28"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            style={{ color: 'var(--accent-cyan)', marginBottom: '0.35rem' }}
          >
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
          <div style={{ fontWeight: 600, fontSize: '0.88rem', color: 'var(--text-main)', marginBottom: '0.2rem' }}>
            {selectedFile ? selectedFile.name : 'Drop GeM dataset file here or click to browse'}
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
            Supports JSON, CSV, or XLSX formats with automatic schema detection
          </div>
        </div>

        {/* Upload Submit */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: '1rem' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.8rem', color: 'var(--text-main)' }}>
            <input
              type="checkbox"
              checked={allowUpdate}
              onChange={(e) => setAllowUpdate(e.target.checked)}
              style={{ accentColor: 'var(--accent-cyan)' }}
            />
            <span>Allow corrigendum updates on duplicate bid records</span>
          </label>
          <button
            className="btn-secondary btn-sm"
            disabled={!selectedFile || uploading}
            onClick={handleUploadSubmit}
          >
            {uploading ? 'Processing Dataset...' : 'Upload & Ingest File'}
          </button>
        </div>

        {/* Upload Success Banner */}
        {importResult && (
          <div style={{ marginTop: '1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.6rem' }}>
              <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--text-main)' }}>
                Dataset Ingested Successfully
              </span>
              <span className="badge badge-match">Status: {importResult.status.toUpperCase()}</span>
            </div>
            <div className="sync-result-grid">
              <div className="sync-result-item">
                <span className="sync-result-item-label">Total Records</span>
                <div className="sync-result-item-value">{importResult.total_records}</div>
              </div>
              <div className="sync-result-item">
                <span className="sync-result-item-label">Created (New)</span>
                <div className="sync-result-item-value" style={{ color: 'var(--accent-green)' }}>{importResult.created}</div>
              </div>
              <div className="sync-result-item">
                <span className="sync-result-item-label">Updated</span>
                <div className="sync-result-item-value" style={{ color: 'var(--accent-cyan)' }}>{importResult.updated}</div>
              </div>
              <div className="sync-result-item">
                <span className="sync-result-item-label">Duplicates</span>
                <div className="sync-result-item-value">{importResult.duplicates}</div>
              </div>
            </div>
          </div>
        )}

        {/* Error Banner */}
        {errorMessage && (
          <div className="alert-error" style={{ marginTop: '1.25rem', marginBottom: 0 }}>
            {errorMessage}
          </div>
        )}
      </div>

      {/* Ingestion Runs History */}
      <div className="card-panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: 'var(--accent-cyan)' }}>
                <circle cx="12" cy="12" r="10" />
                <polyline points="12 6 12 12 16 14" />
              </svg>
              Ingestion Audit Runs
            </h2>
            <p className="panel-subtitle">History of collection runs, adapters used, and database persistence counts</p>
          </div>
          <button className="btn-secondary btn-sm" onClick={fetchRuns}>
            Refresh Runs
          </button>
        </div>

        {loadingRuns ? (
          <div style={{ padding: '1.5rem', textAlign: 'center', color: 'var(--text-muted)' }}>
            Loading audit runs...
          </div>
        ) : runs.length === 0 ? (
          <div className="empty-state">
            <div className="empty-title">No ingestion runs recorded yet</div>
            <div className="empty-desc">Fetch public GeM bids above, or upload a dataset file, to execute your first collection run.</div>
          </div>
        ) : (
          <div className="table-responsive">
            <table className="feed-table">
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Source / Adapter</th>
                  <th>Records Found</th>
                  <th>New Records</th>
                  <th>Duplicates</th>
                  <th>Status</th>
                  <th>Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      {run.id.slice(0, 8)}...
                    </td>
                    <td style={{ fontWeight: 600, color: 'var(--text-main)' }}>{run.source_adapter}</td>
                    <td>{run.records_found}</td>
                    <td style={{ color: 'var(--accent-green)', fontWeight: 600 }}>{run.records_new}</td>
                    <td style={{ color: 'var(--text-dim)' }}>{run.records_duplicate}</td>
                    <td>
                      <span className={`badge ${run.status === 'SUCCESS' ? 'badge-match' : run.status === 'FAILED' ? 'badge-urgent' : 'badge-review'}`}>
                        {run.status}
                      </span>
                    </td>
                    <td style={{ color: 'var(--text-dim)', fontSize: '0.72rem' }}>
                      {new Date(run.started_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};