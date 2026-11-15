import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AllIndiaBidsResponse,
  AllIndiaClassification,
  AllIndiaMatchRow,
  AllIndiaSummary,
} from '../types';
import { KpiTile } from './KpiTile';
import { EmptyState } from './EmptyState';
import { IconClockAlert, IconListSearch, IconMapPin, IconShieldCheck, IconTarget } from './icons';

/**
 * All-India product-relevant GeM bid matching dashboard.
 *
 * Shows GeM bids that the deterministic matching engine has matched to one or
 * more SecuredApp products with a relevance score of 50/100 or higher. One GeM
 * bid can match multiple products; each (bid, product) match is its own row,
 * sharing the same bid_id so a relevant product match is never hidden.
 *
 * All figures come from persisted backend matches — nothing is estimated,
 * sampled, or fabricated. Bids without a stated location are grouped under
 * "Location Not Specified"; no state is ever invented or guessed.
 */
export const AllIndiaMatchesView: React.FC<{
  onSelectBid: (bidId: string) => void;
  loading?: boolean;
}> = ({ onSelectBid, loading: shellLoading = false }) => {
  const [summary, setSummary] = useState<AllIndiaSummary | null>(null);
  const [bids, setBids] = useState<AllIndiaMatchRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Filter state
  const [selectedState, setSelectedState] = useState('ALL');
  const [selectedProduct, setSelectedProduct] = useState('ALL');
  const [minScore, setMinScore] = useState(50);
  const [department, setDepartment] = useState('');
  const [organisation, setOrganisation] = useState('');
  const [valueMin, setValueMin] = useState<string>('');
  const [valueMax, setValueMax] = useState<string>('');
  const [searchTerm, setSearchTerm] = useState('');
  const [sortBy, setSortBy] = useState<'relevance' | 'closing_date' | 'estimated_value' | 'title'>('relevance');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const loadSummary = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/dashboard/all-india/summary');
      if (res.ok) {
        setSummary(await res.json());
      } else {
        setErrorMessage('Failed to load All-India dashboard summary.');
      }
    } catch {
      setErrorMessage('Unable to reach the All-India summary endpoint.');
    }
  }, []);

  const loadBids = useCallback(async () => {
    setLoading(true);
    setErrorMessage(null);
    try {
      const params = new URLSearchParams();
      if (selectedState !== 'ALL') params.set('state', selectedState);
      if (selectedProduct !== 'ALL') params.set('product', selectedProduct);
      if (minScore) params.set('min_score', String(minScore));
      if (department.trim()) params.set('department', department.trim());
      if (organisation.trim()) params.set('organisation', organisation.trim());
      const vMin = parseFloat(valueMin);
      if (!Number.isNaN(vMin)) params.set('estimated_value_min', String(vMin));
      const vMax = parseFloat(valueMax);
      if (!Number.isNaN(vMax)) params.set('estimated_value_max', String(vMax));
      if (searchTerm.trim()) params.set('search', searchTerm.trim());
      params.set('page', String(page));
      params.set('page_size', String(pageSize));
      params.set('sort_by', sortBy);
      params.set('sort_dir', sortDir);

      const res = await fetch(`/api/v1/dashboard/all-india/bids?${params.toString()}`);
      if (res.ok) {
        const data: AllIndiaBidsResponse = await res.json();
        setBids(data.bids);
        setTotal(data.total);
      } else {
        setErrorMessage('Failed to load All-India bid matches.');
      }
    } catch {
      setErrorMessage('Unable to load All-India bid matches.');
    } finally {
      setLoading(false);
    }
  }, [selectedState, selectedProduct, minScore, department, organisation, valueMin, valueMax, searchTerm, page, pageSize, sortBy, sortDir]);

  // Reset to page 1 when filters change
  useEffect(() => {
    setPage(1);
  }, [selectedState, selectedProduct, minScore, department, organisation, valueMin, valueMax, searchTerm, sortBy, sortDir]);

  useEffect(() => {
    loadSummary();
    loadBids();
  }, [loadSummary, loadBids]);

  const handleRefresh = useCallback(() => {
    loadSummary();
    loadBids();
  }, [loadSummary, loadBids]);

  const handleSelectBid = (bidId: string) => {
    onSelectBid(bidId);
  };

  // State options derived from the backend distribution (authoritative list).
  const stateOptions = useMemo(() => {
    return summary?.state_distribution.map((s) => ({
      value: s.location,
      label: s.location,
      count: s.bid_count,
    })) ?? [];
  }, [summary]);

  // Product options derived from the backend distribution.
  const productOptions = useMemo(() => {
    return summary?.product_distribution.map((p) => ({
      value: p.product_name,
      label: p.product_name,
      count: p.bid_count,
    })) ?? [];
  }, [summary]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const classificationTone = (c: AllIndiaClassification | null | undefined): string => {
    switch (c) {
      case 'Highly Relevant': return 'badge badge-match';
      case 'Relevant': return 'badge badge-possible';
      case 'Potentially Relevant': return 'badge badge-review';
      case 'Not Relevant': return 'badge badge-no_match';
      default: return 'badge badge-unknown';
    }
  };

  const scoreColor = (score: number): string => {
    if (score >= 85) return 'var(--accent-green)';
    if (score >= 70) return 'var(--accent-cyan)';
    if (score >= 50) return 'var(--accent-amber)';
    return 'var(--text-muted)';
  };

  if (loading || shellLoading) {
    return (
      <div className="card-panel">
        <div className="panel-header">
          <h2 className="panel-title">All India – Product Relevant Bids</h2>
          <p className="panel-subtitle">
            GeM bids matched to SecuredApp products, state-wise and product-wise.
          </p>
        </div>
        <div className="empty-state">
          <div className="empty-title">Loading All-India matches…</div>
        </div>
      </div>
    );
  }

  if (errorMessage) {
    return (
      <div className="card-panel">
        <div className="panel-header">
          <h2 className="panel-title">All India – Product Relevant Bids</h2>
        </div>
        <div className="alert-error">{errorMessage}</div>
        <div style={{ marginTop: '0.6rem' }}>
          <button className="btn-secondary btn-sm" onClick={handleRefresh}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  // KPI strip
  const kpis = [
    {
      label: 'Total relevant bids',
      value: summary?.total_relevant_bids ?? 0,
      sub: 'Bids with ≥ 50/100 match to a SecuredApp product',
      icon: <IconListSearch />,
      iconTone: 'accent' as const,
      valueTone: 'positive' as const,
    },
    {
      label: 'Highly relevant',
      value: summary?.highly_relevant_bids ?? 0,
      sub: 'Score 85–100',
      icon: <IconShieldCheck />,
      iconTone: 'positive' as const,
      valueTone: 'positive' as const,
    },
    {
      label: 'Relevant',
      value: summary?.relevant_bids ?? 0,
      sub: 'Score 70–84',
      icon: <IconTarget />,
      iconTone: 'accent' as const,
      valueTone: 'accent' as const,
    },
    {
      label: 'Potentially relevant',
      value: summary?.potentially_relevant_bids ?? 0,
      sub: 'Score 50–69',
      icon: <IconClockAlert />,
      iconTone: 'warning' as const,
      valueTone: 'warning' as const,
    },
    {
      label: 'States covered',
      value: summary?.states_covered ?? 0,
      sub: 'States / UTs with matching bids',
      icon: <IconMapPin />,
      iconTone: 'neutral' as const,
      valueTone: 'neutral' as const,
    },
    {
      label: 'Locations disclosed',
      value: summary?.location_qualities?.AVAILABLE ?? 0,
      sub: 'Bids with a published tender location',
      icon: <IconMapPin />,
      iconTone: 'neutral' as const,
      valueTone: 'neutral' as const,
    },
    {
      label: 'Products matched',
      value: summary?.products_with_matches ?? 0,
      sub: 'of 11 SecuredApp products',
      icon: <IconListSearch />,
      iconTone: 'neutral' as const,
      valueTone: 'neutral' as const,
    },
  ] as const;

  return (
    <div className="card-panel">
      <div className="panel-header">
        <div>
          <h2 className="panel-title">All India – Product Relevant Bids</h2>
          <p className="panel-subtitle">
            GeM bids matched to SecuredApp products with a relevance score of 50/
            100 or higher. One bid can match multiple products; each match is
            shown per product. Bids without a stated location appear as
            "Location Not Disclosed by Source" — no state is ever invented or
            guessed.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
          <button
            className="btn-secondary btn-sm"
            onClick={handleRefresh}
            disabled={loading || shellLoading}
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* KPI tiles */}
      <div className="metrics-row" style={{ marginTop: '0.9rem', gap: '0.5rem' }}>
        {kpis.map((k, i) => (
          <KpiTile
            key={i}
            label={k.label}
            value={k.value}
            icon={k.icon}
            iconTone={k.iconTone}
            valueTone={k.valueTone}
            sub={k.sub}
            highlight={i === 0}
          />
        ))}
      </div>

      {/* State-wise distribution */}
      <div style={{ marginTop: '1.05rem' }}>
        <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '0.9rem', color: 'var(--text-main)' }}>
          State-wise distribution
        </h3>
        {summary?.state_distribution.length === 0 ? (
          <div className="empty-state">
            <div className="empty-title">No state-wise matches</div>
          </div>
        ) : (
          <div className="table-responsive">
            <table className="feed-table feed-table-compact">
              <thead>
                <tr>
                  <th>State / Location</th>
                  <th style={{ textAlign: 'center' }}>Bids</th>
                  <th style={{ textAlign: 'center' }}>Highly relevant</th>
                  <th style={{ textAlign: 'center' }}>Relevant</th>
                  <th style={{ textAlign: 'center' }}>Potentially relevant</th>
                </tr>
              </thead>
              <tbody>
                {summary.state_distribution.map((s) => (
                  <tr key={s.location}>
                    <td style={{ fontWeight: 600, color: 'var(--text-main)' }}>{s.location}</td>
                    <td style={{ textAlign: 'center', fontSize: '0.82rem' }}>{s.bid_count}</td>
                    <td style={{ textAlign: 'center', color: 'var(--accent-green)', fontSize: '0.82rem' }}>{s.highly_relevant}</td>
                    <td style={{ textAlign: 'center', color: 'var(--accent-cyan)', fontSize: '0.82rem' }}>{s.relevant}</td>
                    <td style={{ textAlign: 'center', color: 'var(--accent-amber)', fontSize: '0.82rem' }}>{s.potentially_relevant}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="toolbar-container" style={{ marginTop: '1rem' }}>
        <div className="search-input-wrapper">
          <input
            type="text"
            className="search-input"
            placeholder="Search title, tender ID, organisation, department, product…"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>

        <select
          className="filter-select"
          value={selectedState}
          onChange={(e) => setSelectedState(e.target.value)}
          aria-label="Filter by state / location"
        >
          <option value="ALL">All Locations</option>
          {stateOptions.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label} ({o.count})
            </option>
          ))}
        </select>

        <select
          className="filter-select"
          value={selectedProduct}
          onChange={(e) => setSelectedProduct(e.target.value)}
          aria-label="Filter by product"
        >
          <option value="ALL">All Products</option>
          {productOptions.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label} ({o.count})
            </option>
          ))}
        </select>

        <select
          className="filter-select"
          value={String(minScore)}
          onChange={(e) => setMinScore(Number(e.target.value))}
          aria-label="Minimum relevance score"
        >
          <option value="50">Min score: 50 (Potentially relevant)</option>
          <option value="70">Min score: 70 (Relevant)</option>
          <option value="85">Min score: 85 (Highly relevant)</option>
        </select>

        <input
          className="filter-select"
          placeholder="Dept. contains…"
          value={department}
          onChange={(e) => setDepartment(e.target.value)}
          aria-label="Filter by department"
        />

        <input
          className="filter-select"
          placeholder="Organisation contains…"
          value={organisation}
          onChange={(e) => setOrganisation(e.target.value)}
          aria-label="Filter by organisation"
        />

        <input
          className="filter-select"
          placeholder="Min value (₹)"
          type="number"
          value={valueMin}
          onChange={(e) => setValueMin(e.target.value)}
          aria-label="Minimum estimated value"
        />

        <input
          className="filter-select"
          placeholder="Max value (₹)"
          type="number"
          value={valueMax}
          onChange={(e) => setValueMax(e.target.value)}
          aria-label="Maximum estimated value"
        />
      </div>

      {/* Content */}
      {bids.length === 0 && (
        <div className="empty-state">
          <div className="empty-title">No All-India bid matches found</div>
          <div className="empty-desc">
            Try adjusting the state, product, score, or value filters. Matches
            require a relevance score of 50/100 or higher against a SecuredApp
            product.
          </div>
        </div>
      )}

      {bids.length > 0 && (
        <>
          <div className="table-responsive">
            <table className="feed-table">
              <thead>
                <tr>
                  <th
                    onClick={() =>
                      setSortBy(sortBy === 'relevance' ? 'relevance' : 'relevance')
                    }
                    style={{ cursor: 'pointer', userSelect: 'none' }}
                  >
                    Relevance {sortBy === 'relevance' ? (sortDir === 'desc' ? '▼' : '▲') : ''}
                  </th>
                  <th>Tender / Bid ID</th>
                  <th>Tender Title</th>
                  <th>Matched Product</th>
                  <th>Score / Class.</th>
                  <th>State / Location</th>
                  <th>Organisation</th>
                  <th>Dept.</th>
                  <th>Est. Value</th>
                  <th>Closing</th>
                  <th style={{ textAlign: 'right' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {bids.map((row) => (
                  <tr key={`${row.bid_id}|${row.product_id}`}>
                    <td>
                      <span style={{ color: scoreColor(row.relevance_score_100), fontWeight: 600, fontSize: '0.82rem' }}>
                        {row.relevance_score_100}
                      </span>
                    </td>
                    <td>
                      <span className="bid-id-mono" style={{ fontSize: '0.79rem' }}>
                        {row.tender_id || '—'}
                      </span>
                    </td>
                    <td>
                      <div className="bid-title-cell" title={row.title}>
                        {row.title}
                      </div>
                    </td>
                    <td style={{ fontSize: '0.79rem' }}>
                      <span style={{ fontWeight: 600, color: 'var(--text-main)' }}>{row.product_name}</span>
                    </td>
                    <td style={{ fontSize: '0.79rem' }}>
                      <span className={classificationTone(row.classification)}>
                        {row.classification}
                      </span>
                    </td>
                    <td style={{ fontSize: '0.79rem' }}>
                      <div
                        style={{
                          fontWeight: 600,
                          color:
                            row.location_quality === 'NOT_DISCLOSED'
                              ? 'var(--text-muted)'
                              : row.location_quality === 'EXTRACTION_FAILED'
                                ? 'var(--accent-red)'
                                : 'var(--text-main)',
                          fontStyle:
                            row.location_quality !== 'AVAILABLE' ? 'italic' : 'normal',
                        }}
                      >
                        {row.location_quality === 'NOT_DISCLOSED' || !row.location || row.location === 'Location Not Disclosed by Source'
                          ? 'Location Not Disclosed by Source'
                          : row.location}
                        {row.city && row.location_quality === 'AVAILABLE' && (
                          <span
                            style={{
                              fontSize: '0.68rem',
                              color: 'var(--text-secondary)',
                              marginLeft: '0.25rem',
                              fontWeight: 400,
                            }}
                          >
                            ({row.city})
                          </span>
                        )}
                        {row.location_quality === 'EXTRACTION_FAILED' && (
                          <span
                            style={{
                              fontSize: '0.68rem',
                              color: 'var(--accent-red)',
                              marginLeft: '0.25rem',
                              fontWeight: 400,
                              fontStyle: 'italic',
                            }}
                          >
                            — extraction failed
                          </span>
                        )}
                      </div>
                    </td>
                    <td style={{ fontSize: '0.79rem', color: 'var(--text-secondary)' }}>
                      {row.organisation || 'Unstated'}
                    </td>
                    <td style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      {row.department || '—'}
                    </td>
                    <td style={{ fontSize: '0.79rem' }}>
                      {row.estimated_value !== null && row.estimated_value !== undefined
                        ? `₹${row.estimated_value.toLocaleString()}`
                        : 'Unstated'}
                    </td>
                    <td style={{ fontSize: '0.75rem' }}>
                      {row.closing_date ? new Date(row.closing_date).toLocaleDateString() : '—'}
                      {row.days_remaining !== null && row.days_remaining !== undefined && row.days_remaining <= 7 && row.days_remaining >= 0 && (
                        <span style={{ color: 'var(--accent-red)', fontSize: '0.7rem', marginLeft: '0.25rem' }}>
                          closing in {row.days_remaining}d
                        </span>
                      )}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <button
                        className="btn-primary btn-sm"
                        onClick={() => handleSelectBid(row.bid_id)}
                        title="Open bid details"
                      >
                        Inspect →
                      </button>
                      {(row.original_bid_url || row.source_url) && (
                        <a
                          className="btn-secondary btn-sm"
                          href={row.original_bid_url || row.source_url!}
                          target="_blank"
                          rel="noopener noreferrer"
                          title={row.original_bid_url || row.source_url!}
                          style={{ marginLeft: '0.35rem' }}
                        >
                          View Original
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="list-foot">
            <span>
              Showing {bids.length} of {total} matches &nbsp;|&nbsp; Page {page} of {totalPages}
            </span>
            <div style={{ display: 'flex', gap: '0.4rem' }}>
              <button
                className="btn-secondary btn-sm"
                disabled={page === 1 || loading}
                onClick={() => setPage((p) => p - 1)}
              >
                Prev
              </button>
              <button
                className="btn-secondary btn-sm"
                disabled={page >= totalPages || loading}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
};
