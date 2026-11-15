import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ConfiguredSource,
  Product,
  SourceStatus,
  StateWiseBidRow,
  StateWiseProductMatch,
  StateWiseBidsResponse,
} from '../types';
import { api } from '../lib/api';

interface StateWiseBidsViewProps {
  onSelectBid: (bidId: string) => void;
}

/** Which collection of state bids to display. */
type BidViewTab = 'collected' | 'matched';

/**
 * State-wise Bids page.
 *
 * Displays actual tender records from state government e-procurement portals,
 * grouped and filterable by state. GeM bids are excluded — this page shows
 * only state-source bids.
 *
 * Each state exposes two views:
 *  * Collected — every genuinely collected bid for the state (zero-match
 *    states still show their collected bids here).
 *  * Matched — only bids that have at least one persisted product match.
 *
 * Each bid retains its state identity (from the data source registry) and
 * source identity. Clicking a bid opens its existing detail drawer.
 *
 * One tender matching multiple products is displayed as one row per matched
 * product (the backend returns one row per (bid, product_match) combination),
 * so the tender is never accidentally duplicated.
 */
export const StateWiseBidsView: React.FC<StateWiseBidsViewProps> = ({
  onSelectBid,
}) => {
  const [sources, setSources] = useState<ConfiguredSource[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [bids, setBids] = useState<StateWiseBidRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [sourcesError, setSourcesError] = useState<string | null>(null);
  const [productsError, setProductsError] = useState<string | null>(null);

  // Filter state
  const [selectedState, setSelectedState] = useState('ALL');
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedProduct, setSelectedProduct] = useState('ALL');
  const [selectedMatchStatus, setSelectedMatchStatus] = useState('ALL');
  const [selectedBidStatus, setSelectedBidStatus] = useState('ALL');

  // Tab: Collected / Matched
  const [viewTab, setViewTab] = useState<BidViewTab>('collected');

  const loadSources = useCallback(async () => {
    try {
      const all: ConfiguredSource[] = await api.get<ConfiguredSource[]>('/api/v1/sources');
      // Show only state sources (exclude GeM direct)
      setSources(all.filter((s) => s.source_id !== 'gem_direct').sort((a, b) => a.name.localeCompare(b.name)));
      setSourcesError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load source configurations.';
      setSourcesError(msg);
    }
  }, []);

  const loadProducts = useCallback(async () => {
    try {
      const data: Product[] = await api.get<Product[]>('/api/v1/products');
      setProducts(data);
      setProductsError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load product catalogue.';
      setProductsError(msg);
    }
  }, []);

  const loadBids = useCallback(async () => {
    setLoading(true);
    setErrorMessage(null);
    try {
      const params = new URLSearchParams();
      if (selectedState !== 'ALL') params.set('state', selectedState);
      if (searchTerm.trim()) params.set('search', searchTerm.trim());
      if (selectedProduct !== 'ALL') params.set('product', selectedProduct);
      if (selectedMatchStatus !== 'ALL') params.set('match_status', selectedMatchStatus);
      if (selectedBidStatus !== 'ALL') params.set('bid_status', selectedBidStatus);
      // Collected tab shows every collected bid (incl. no-match); Matched tab
      // shows only bids with at least one persisted product match.
      if (viewTab === 'collected') params.set('include_no_match', 'true');
      params.set('page', String(page));
      params.set('page_size', String(pageSize));

      const data: StateWiseBidsResponse = await api.get<StateWiseBidsResponse>(
        `/api/v1/bids/state-wise?${params.toString()}`,
      );
      setBids(data.bids);
      setTotal(data.total);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load state-wise bids.';
      setErrorMessage(msg);
    } finally {
      setLoading(false);
    }
  }, [selectedState, searchTerm, selectedProduct, selectedMatchStatus, selectedBidStatus, viewTab, page, pageSize]);

  // Reset to page 1 when filters or tab change
  useEffect(() => {
    setPage(1);
  }, [selectedState, searchTerm, selectedProduct, selectedMatchStatus, selectedBidStatus, viewTab]);

  useEffect(() => {
    loadSources();
    loadProducts();
    loadBids();
  }, [loadSources, loadProducts, loadBids]);

  // State options for the selector
  const stateOptions = useMemo(() => {
    return sources.map((s) => ({
      value: s.source_id,
      label: s.name,
      status: s.status as SourceStatus,
      enabled: s.enabled,
      collected: s.last_inserted,
    }));
  }, [sources]);

  // Product options
  const productOptions = useMemo(() => {
    const names = new Set<string>();
    products.forEach((p) => names.add(p.name));
    return Array.from(names).sort();
  }, [products]);

  // Match status options
  const matchStatusOptions = [
    { value: 'ALL', label: 'All Match Statuses' },
    { value: 'MATCH', label: 'Match (≥ 0.70)' },
    { value: 'POSSIBLE_MATCH', label: 'Possible Match (0.45–0.70)' },
    { value: 'NEEDS_REVIEW', label: 'Needs Review (0.25–0.45)' },
    { value: 'NO_MATCH', label: 'No Match (< 0.25)' },
    { value: 'NOT_ANALYZED', label: 'Not yet analyzed' },
  ];

  // Bid status options
  const bidStatusOptions = [
    { value: 'ALL', label: 'All Bid Statuses' },
    { value: 'OPEN', label: 'Open' },
    { value: 'CLOSING_SOON', label: 'Closing Soon' },
    { value: 'CLOSED', label: 'Closed' },
  ];

  const stateOption = stateOptions.find((s) => s.value === selectedState);
  const stateLabel = stateOption ? stateOption.label : 'All States';
  const stateStatus = stateOption ? stateOption.status : undefined;

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

  const matchBadgeClass = (matchState: string | null): string => {
    switch (matchState) {
      case 'MATCH': return 'badge badge-match';
      case 'POSSIBLE_MATCH': return 'badge badge-possible';
      case 'NEEDS_REVIEW': return 'badge badge-review';
      case 'NO_MATCH': return 'badge badge-no_match';
      default: return 'badge badge-unknown';
    }
  };

  const deadlineClass = (status: string): string => {
    switch (status) {
      case 'CLOSED': return 'badge badge-no_match';
      case 'CLOSING_SOON':
      case 'URGENT': return 'badge badge-urgent';
      case 'OPEN': return 'badge badge-info';
      default: return 'badge badge-unknown';
    }
  };

  const tabCount = viewTab === 'collected' ? total : bids.filter((b) => (b.product_matches || []).length > 0).length;

  // Deduplicate bids to prevent duplicate bid cards/rows if a tender is returned multiple times
  const uniqueBids = useMemo(() => {
    const seen = new Set<string>();
    return bids.filter((b) => {
      if (seen.has(b.id)) return false;
      seen.add(b.id);
      return true;
    });
  }, [bids]);

  const handleRefresh = useCallback(() => {
    loadBids();
  }, [loadBids]);

  const handleSelectBid = (bidId: string) => {
    onSelectBid(bidId);
  };

  // Loading shell
  if (loading) {
    return (
      <div className="card-panel">
        <div className="panel-header">
          <h2 className="panel-title">State-wise Bids</h2>
          <p className="panel-subtitle">
            Actual tender records from state government e-procurement portals.
          </p>
        </div>
        <div className="empty-state">
          <div className="empty-title">Loading state-wise bids…</div>
        </div>
      </div>
    );
  }

  // Error shell
  if (errorMessage) {
    return (
      <div className="card-panel">
        <div className="panel-header">
          <h2 className="panel-title">State-wise Bids</h2>
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

  return (
    <div className="card-panel">
      <div className="panel-header">
        <div>
          <h2 className="panel-title">State-wise Bids</h2>
          <p className="panel-subtitle">
            Actual tender records from state government e-procurement portals.
            GeM bids are excluded. Each bid retains its state and source identity.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.48rem', alignItems: 'center' }}>
          {sourcesError && (
            <span style={{ color: 'var(--accent-red)', fontSize: '0.75rem' }}>
              Sources unavailable: {sourcesError}
            </span>
          )}
          {productsError && (
            <span style={{ color: 'var(--accent-red)', fontSize: '0.75rem' }}>
              Products unavailable: {productsError}
            </span>
          )}
          <button
            className="btn-secondary btn-sm"
            onClick={handleRefresh}
            disabled={loading}
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* View tabs: Collected / Matched */}
      <div style={{ display: 'flex', gap: '0.25rem', marginBottom: '0.5rem' }}>
        {[
          { id: 'collected' as const, label: 'Collected Bids' },
          { id: 'matched' as const, label: 'Matched Bids' },
        ].map((tab) => {
          const active = viewTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setViewTab(tab.id)}
              className={`btn ${active ? 'btn-primary' : 'btn-secondary'} btn-sm`}
              aria-pressed={active}
            >
              {tab.label} ({active ? tabCount : '—'})
            </button>
          );
        })}
      </div>

      {/* Filters */}
      <div className="toolbar-container">
        <div className="search-input-wrapper">
          <input
            type="text"
            className="search-input"
            placeholder="Search by bid number, tender ID, title, organisation…"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>

        <select
          className="filter-select"
          value={selectedState}
          onChange={(e) => setSelectedState(e.target.value)}
          aria-label="Filter by state"
        >
          <option value="ALL">All States</option>
          {stateOptions.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label} ({s.enabled ? 'Connected' : s.status === 'BLOCKED' ? 'Blocked' : 'Not Configured'})
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
          {productOptions.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>

        <select
          className="filter-select"
          value={selectedMatchStatus}
          onChange={(e) => setSelectedMatchStatus(e.target.value)}
          aria-label="Filter by match status"
        >
          {matchStatusOptions.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>

        <select
          className="filter-select"
          value={selectedBidStatus}
          onChange={(e) => setSelectedBidStatus(e.target.value)}
          aria-label="Filter by bid status"
        >
          {bidStatusOptions.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>

      {/* State status indicator */}
      {selectedState !== 'ALL' && stateOption && (
        <div className="state-status-banner">
          <span className={statusBadgeClass(stateStatus)}>
            {stateStatus.replace(/_/g, ' ').toLowerCase()}
          </span>{' '}
          {stateOption.enabled
            ? 'Source is connected'
            : stateOption.status === 'BLOCKED'
              ? 'Source is blocked — portal requires authentication'
              : stateOption.status === 'CONFIG_ERROR'
                ? 'Source is not configured — no records available'
                : 'No records available'}
        </div>
      )}

      {/* Collected vs Matched hint */}
      {selectedState !== 'ALL' && stateOption && viewTab === 'matched' && total === 0 && (
        <div className="empty-state">
          <div className="empty-title">No matched bids for {stateLabel}</div>
          <div className="empty-desc">
            This state has {stateOption.collected || 0} collected bid(s) but none matched a
            SecuredApp product yet. Switch to "Collected Bids" to view them.
          </div>
        </div>
      )}

      {/* Content */}
      {uniqueBids.length === 0 && !(loading || errorMessage) && (
        <div className="empty-state">
          <div className="empty-title">
            {viewTab === 'collected'
              ? 'No state-wise bids found'
              : 'No matched bids found'}
          </div>
          <div className="empty-desc">
            {viewTab === 'collected'
              ? 'Try adjusting the filters or sync a state source from the State Tenders page to collect tender records.'
              : 'No state-wise tenders have matched a SecuredApp product under the current filters. Switch to "Collected Bids" to view all collected bids for this state.'}
          </div>
        </div>
      )}

      {uniqueBids.length > 0 && (
        <>
          <div className="table-responsive">
            <table className="feed-table">
              <thead>
                <tr>
                  <th scope="col">State</th>
                  <th scope="col">Bid / Tender Number</th>
                  <th scope="col">Tender Title</th>
                  <th scope="col">Organisation</th>
                  <th scope="col">Matched Product</th>
                  <th scope="col">Match Status</th>
                  <th scope="col">Relevance</th>
                  <th scope="col">Est. Value</th>
                  <th scope="col">Published</th>
                  <th scope="col">Closing</th>
                  <th scope="col">Source</th>
                  <th scope="col" style={{ textAlign: 'right' }}>
                    Action
                  </th>
                </tr>
              </thead>
              <tbody>
                {uniqueBids.map((bid) => (
                  <tr key={bid.id}>
                    <td>
                      <div style={{ fontWeight: 600, color: 'var(--text-main)', fontSize: '0.79rem' }}>
                        {bid.state}
                      </div>
                      <div style={{ fontSize: '0.69rem', color: 'var(--text-muted)' }}>
                        {bid.state_id}
                      </div>
                    </td>
                    <td>
                      <span className="bid-id-mono" style={{ fontSize: '0.79rem' }}>
                        {bid.bid_number || bid.gem_bid_id || '—'}
                      </span>
                    </td>
                    <td>
                      <div className="bid-title-cell" title={bid.title}>
                        {bid.title}
                      </div>
                    </td>
                    <td style={{ fontSize: '0.79rem' }}>
                      {bid.organisation || 'Unstated'}
                    </td>
                    <td>
                      {bid.product_matches && bid.product_matches.length > 0 ? (
                        <div className="pm-product-cell">
                          {bid.product_matches.map((pm: StateWiseProductMatch) => {
                            const kw = pm.matching_keywords || [];
                            return (
                              <div key={pm.product_id} style={{ display: 'flex', alignItems: 'baseline', gap: '0.3rem', flexWrap: 'wrap' }}>
                                <span className="pm-product-name" title={pm.product_name}>
                                  {pm.product_name}
                                </span>
                                {pm.match_score !== null && pm.match_score !== undefined && (
                                  <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>
                                    {(pm.match_score * 100).toFixed(0)}%
                                  </span>
                                )}
                                {kw.length > 0 && (
                                  <span style={{ fontSize: '0.62rem', color: 'var(--text-muted)', fontStyle: 'italic', marginTop: '0.1rem', display: 'block' }}>
                                    {kw.slice(0, 3).join(', ')}{kw.length > 3 ? ` +${kw.length - 3}` : ''}
                                  </span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      ) : bid.analyzed ? (
                        <span style={{ color: 'var(--text-dim)', fontSize: '0.79rem' }}>
                          No matched SecuredApp products
                        </span>
                      ) : (
                        <span style={{ color: 'var(--text-dim)', fontSize: '0.79rem' }}>
                          Not yet analyzed
                        </span>
                      )}
                    </td>
                    <td>
                      <span className={matchBadgeClass(bid.match_state)}>
                        {bid.match_state ? bid.match_state.replace(/_/g, ' ').toLowerCase() : '—'}
                      </span>
                    </td>
                    <td>
                      {bid.relevance_score !== null && bid.relevance_score !== undefined ? (
                        <span style={{ color: bid.relevance_score >= 0.7 ? 'var(--accent-green)' : bid.relevance_score >= 0.45 ? 'var(--s-possible-text)' : bid.relevance_score >= 0.25 ? 'var(--s-review-text)' : 'var(--text-muted)', fontSize: '0.79rem' }}>
                          {bid.relevance_score.toFixed(2)}
                        </span>
                      ) : (
                        <span style={{ color: 'var(--text-dim)', fontSize: '0.79rem' }}>—</span>
                      )}
                    </td>
                    <td style={{ fontSize: '0.79rem' }}>
                      {bid.estimated_value !== null && bid.estimated_value !== undefined
                        ? `₹${bid.estimated_value.toLocaleString()}`
                        : 'Unstated'}
                    </td>
                    <td style={{ fontSize: '0.75rem' }}>
                      {bid.published_date ? new Date(bid.published_date).toLocaleDateString() : '—'}
                    </td>
                    <td style={{ fontSize: '0.75rem' }}>
                      <span className={deadlineClass(bid.deadline_status)}>
                        {bid.closing_date ? new Date(bid.closing_date).toLocaleDateString() : '—'}
                      </span>
                    </td>
                    <td style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      {bid.source}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <button
                        className="btn-primary btn-sm"
                        onClick={() => handleSelectBid(bid.id)}
                        title="Open bid details"
                      >
                        Inspect →
                      </button>
                      {(bid.original_bid_url || bid.source_url) && (
                        <a
                          className="btn-secondary btn-sm"
                          href={bid.original_bid_url || bid.source_url!}
                          target="_blank"
                          rel="noopener noreferrer"
                          title={bid.original_bid_url || bid.source_url!}
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
              Showing {uniqueBids.length} of {total} bids &nbsp;|&nbsp;
              Page {page} of {Math.max(1, Math.ceil(total / pageSize))}
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
                disabled={page >= Math.max(1, Math.ceil(total / pageSize)) || loading}
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

export default StateWiseBidsView;
