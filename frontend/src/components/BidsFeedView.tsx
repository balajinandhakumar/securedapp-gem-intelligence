import React, { useEffect, useMemo, useState } from 'react';
import { BidIntelligenceRow, MatchState, Product } from '../types';
import { deadlineMeta } from '../lib/format';
import { TableSkeleton, CardGridSkeleton } from './SkeletonLoader';

interface BidsFeedViewProps {
  bids: BidIntelligenceRow[];
  loading: boolean;
  products: Product[];
  onSelectBid: (bidId: string) => void;
  onRefresh: () => void;
  /** Global search box in the top bar. */
  search: string;
  onSearchChange: (value: string) => void;
}

type SortKey = 'published' | 'relevance' | 'deadline' | 'value';

// Rows rendered per page. The feed can hold tens of thousands of bids; rendering
// every row at once froze the tab, so the table/grid reveal rows in batches.
const PAGE_SIZE = 50;

function matchBadgeClass(matchState: MatchState | null): string {
  switch (matchState) {
    case 'MATCH':          return 'badge badge-match';
    case 'POSSIBLE_MATCH': return 'badge badge-possible';
    case 'NEEDS_REVIEW':   return 'badge badge-needs_review';
    case 'NO_MATCH':       return 'badge badge-no_match';
    default:               return 'badge badge-unknown';
  }
}

function scoreColor(score: number | null): string {
  if (score === null) return 'var(--text-dim)';
  if (score >= 0.7)  return 'var(--accent-green)';
  if (score >= 0.45) return 'var(--s-possible-text)';
  if (score >= 0.25) return 'var(--s-review-text)';
  return 'var(--text-muted)';
}

function ProductMatchCell({ row }: { row: BidIntelligenceRow }) {
  if (!row.analyzed) {
    return <span className="unanalysed-note">Not yet analyzed</span>;
  }
  // The backend only names a product when the pipeline actually matched one,
  // so a missing name on an analyzed row means NO_MATCH, not missing data.
  if (!row.matched_product) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.22rem' }}>
        <span style={{ color: 'var(--text-dim)', fontSize: '0.79rem' }}>No relevant product</span>
        <span className={matchBadgeClass(row.match_state)}>{row.match_state ?? 'NO_MATCH'}</span>
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.22rem' }}>
      <span style={{ fontWeight: 600, color: 'var(--text-main)', fontSize: '0.79rem' }}>
        {row.matched_product}
      </span>
      <span className={matchBadgeClass(row.match_state)}>
        {row.match_state ?? 'UNMATCHED'}
      </span>
    </div>
  );
}

function RelevanceCell({ row }: { row: BidIntelligenceRow }) {
  if (!row.analyzed || row.relevance_score === null) {
    return <span className="unanalysed-note">Not yet analyzed</span>;
  }
  const pct = Math.round(Math.min(1, Math.max(0, row.relevance_score)) * 100);
  return (
    <div className="relevance-cell">
      <span className="relevance-num" style={{ color: scoreColor(row.relevance_score) }}>
        {row.relevance_score.toFixed(2)}
      </span>
      <span className="relevance-bar">
        <span
          className="relevance-bar-fill"
          style={{ width: `${pct}%`, background: scoreColor(row.relevance_score) }}
        />
      </span>
    </div>
  );
}

function OpportunityCell({ row }: { row: BidIntelligenceRow }) {
  if (!row.analyzed || row.opportunity_score === null) {
    return <span className="unanalysed-note">Not yet analyzed</span>;
  }
  return (
    <span className="relevance-num" style={{ color: scoreColor(row.opportunity_score) }}>
      {row.opportunity_score.toFixed(2)}
    </span>
  );
}

function DeadlineCell({ row }: { row: BidIntelligenceRow }) {
  const { text, cls } = deadlineMeta(row.days_remaining);
  return <span className={cls}>{text}</span>;
}

/**
 * Bid intelligence feed.
 * Rows from GET /api/v1/bids/intelligence — no client-side scoring.
 * Unanalyzed bids shown honestly as "Not yet analyzed".
 */
export const BidsFeedView: React.FC<BidsFeedViewProps> = ({
  bids,
  loading,
  products,
  onSelectBid,
  onRefresh,
  search,
  onSearchChange,
}) => {
  const [selectedProduct, setSelectedProduct] = useState('ALL');
  const [selectedClass, setSelectedClass]     = useState('ALL');
  const [sortKey, setSortKey]                 = useState<SortKey>('published');
  const [viewMode, setViewMode]               = useState<'table' | 'grid'>('table');
  const [visibleCount, setVisibleCount]       = useState(PAGE_SIZE);

  // A new search term, filter or sort order re-defines the result set, so the
  // visible window restarts at the first page.
  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [search, selectedProduct, selectedClass, sortKey, viewMode]);

  const filteredBids = useMemo(() => {
    const term = search.trim().toLowerCase();
    const rows = bids.filter((bid) => {
      if (selectedProduct !== 'ALL' && bid.matched_product !== selectedProduct) return false;
      if (selectedClass !== 'ALL') {
        if (selectedClass === 'NOT_ANALYZED') {
          if (bid.analyzed) return false;
        } else if (bid.match_state !== selectedClass) {
          return false;
        }
      }
      if (!term) return true;
      return (
        (bid.title ?? '').toLowerCase().includes(term) ||
        (bid.gem_bid_id ?? '').toLowerCase().includes(term) ||
        (bid.bid_number ?? '').toLowerCase().includes(term) ||
        (bid.organisation ?? '').toLowerCase().includes(term)
      );
    });

    return rows.sort((a, b) => {
      switch (sortKey) {
        case 'relevance': return (b.relevance_score ?? -1) - (a.relevance_score ?? -1);
        case 'deadline': {
          const av = a.days_remaining ?? Number.MAX_SAFE_INTEGER;
          const bv = b.days_remaining ?? Number.MAX_SAFE_INTEGER;
          return av - bv;
        }
        case 'value': return (b.estimated_value ?? -1) - (a.estimated_value ?? -1);
        default:
          return (b.published_date ?? b.last_updated_at ?? '').localeCompare(
            a.published_date ?? a.last_updated_at ?? ''
          );
      }
    });
  }, [bids, search, selectedProduct, selectedClass, sortKey]);

  const analyzedCount = bids.filter((b) => b.analyzed).length;
  const hasFilters    = search || selectedProduct !== 'ALL' || selectedClass !== 'ALL';

  // Only the visible window is mounted; "Load more" extends it.
  const visibleBids = filteredBids.slice(0, visibleCount);

  return (
    <>
      <div className="page-head">
        <h1 className="page-title">Bids</h1>
        <p className="page-sub">
          Every stored bid with its real analysis state. Use the top bar or the filters below to
          narrow the feed.
        </p>
      </div>

      <div className="card-panel">
        {/* Header */}
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Bid Intelligence Feed</h2>
            <p className="panel-subtitle">
              {filteredBids.length} of {bids.length} bids · {analyzedCount} analyzed
            </p>
          </div>

          <div style={{ display: 'flex', gap: '0.48rem', alignItems: 'center' }}>
            {/* View toggle */}
            <div className="view-toggle">
              <button
                className={`view-toggle-btn${viewMode === 'table' ? ' active' : ''}`}
                onClick={() => setViewMode('table')}
                aria-label="Table view"
                title="Table view"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/>
                  <line x1="8" y1="18" x2="21" y2="18"/>
                  <line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/>
                  <line x1="3" y1="18" x2="3.01" y2="18"/>
                </svg>
              </button>
              <button
                className={`view-toggle-btn${viewMode === 'grid' ? ' active' : ''}`}
                onClick={() => setViewMode('grid')}
                aria-label="Grid view"
                title="Card view"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
                  <rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>
                </svg>
              </button>
            </div>

            <button className="btn-secondary btn-sm" onClick={onRefresh}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
              </svg>
              Refresh
            </button>
          </div>
        </div>

        {/* Filters */}
        <div className="toolbar-container">
          <div className="search-input-wrapper">
            <svg className="search-icon-inside" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
            </svg>
            <input
              type="text"
              className="search-input"
              placeholder="Search by title, bid reference, buyer…"
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
            />
          </div>

          <select
            className="filter-select"
            value={selectedProduct}
            onChange={(e) => setSelectedProduct(e.target.value)}
            aria-label="Filter by product"
          >
            <option value="ALL">All Products</option>
            {products.map((p) => (
              <option key={p.id} value={p.name}>{p.name}</option>
            ))}
          </select>

          <select
            className="filter-select"
            value={selectedClass}
            onChange={(e) => setSelectedClass(e.target.value)}
            aria-label="Filter by analysis state"
          >
            <option value="ALL">All States</option>
            <option value="MATCH">Match (≥ 0.70)</option>
            <option value="POSSIBLE_MATCH">Possible Match (0.45–0.70)</option>
            <option value="NEEDS_REVIEW">Needs Review (0.25–0.45)</option>
            <option value="NO_MATCH">No Match (&lt; 0.25)</option>
            <option value="NOT_ANALYZED">Not yet analyzed</option>
          </select>

          <select
            className="filter-select"
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            aria-label="Sort bids"
          >
            <option value="published">Newest first</option>
            <option value="relevance">Highest relevance</option>
            <option value="deadline">Closing soonest</option>
            <option value="value">Highest value</option>
          </select>

          {hasFilters && (
            <button
              className="btn-secondary btn-sm"
              onClick={() => { onSearchChange(''); setSelectedProduct('ALL'); setSelectedClass('ALL'); }}
            >
              Clear
            </button>
          )}
        </div>

        {/* Content */}
        {loading ? (
          viewMode === 'table' ? <TableSkeleton /> : <CardGridSkeleton />
        ) : bids.length === 0 ? (
          <div className="empty-state">
            <div className="empty-title">No bids ingested yet</div>
            <div className="empty-desc">
              Import bid data from the Data Source page. Live GeM access requires authorized API credentials.
            </div>
          </div>
        ) : filteredBids.length === 0 ? (
          <div className="empty-state">
            <div className="empty-title">No bids match your filters</div>
            <div className="empty-desc">Try a different search term, product, or analysis state.</div>
          </div>
        ) : viewMode === 'table' ? (
          <div className="table-responsive">
            <table className="feed-table">
              <thead>
                <tr>
                  <th scope="col">Bid</th>
                  <th scope="col">Organisation</th>
                  <th scope="col">Product Match</th>
                  <th scope="col">Relevance</th>
                  <th scope="col">Deadline</th>
                  <th scope="col">Opportunity</th>
                  <th scope="col" style={{ textAlign: 'right' }}>
                    Action
                  </th>
                </tr>
              </thead>
              <tbody>
                {visibleBids.map((bid) => (
                  <tr key={bid.id}>
                    <td>
                      <span className="bid-id-mono">{bid.gem_bid_id || bid.bid_number || '—'}</span>
                      <div className="bid-title-cell" title={bid.title}>{bid.title}</div>
                      <div className="bid-meta-sub">
                        <span>{bid.category || 'General Procurement'}</span>
                      </div>
                    </td>
                    <td>
                      <div style={{ fontWeight: 500, color: 'var(--text-main)', fontSize: '0.79rem' }}>
                        {bid.organisation || 'Unstated'}
                      </div>
                      <div style={{ fontSize: '0.69rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>
                        {bid.location || 'India'}
                      </div>
                    </td>
                    <td><ProductMatchCell row={bid} /></td>
                    <td><RelevanceCell row={bid} /></td>
                    <td><DeadlineCell row={bid} /></td>
                    <td><OpportunityCell row={bid} /></td>
                    <td style={{ textAlign: 'right' }}>
                      <button className="btn-primary btn-sm" onClick={() => onSelectBid(bid.id)}>
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
        ) : (
          <div className="bid-grid">
            {visibleBids.map((bid) => (
              <div key={bid.id} className="bid-card">
                <div>
                  <div className="bid-card-header">
                    <span className="opp-bid-id">{bid.gem_bid_id || bid.bid_number || '—'}</span>
                    <DeadlineCell row={bid} />
                  </div>
                  <div className="bid-card-title">{bid.title}</div>
                  <div className="bid-card-org">{bid.organisation || 'Organisation unstated'}</div>

                  {!bid.analyzed ? (
                    <div style={{ marginTop: '0.45rem' }}>
                      <span className="unanalysed-note">Not yet analyzed</span>
                    </div>
                  ) : bid.matched_product ? (
                    <div className="opp-match-pill">
                      <span className="opp-product-name">{bid.matched_product}</span>
                      <span className={matchBadgeClass(bid.match_state)}>
                        {bid.relevance_score?.toFixed(2)}
                      </span>
                    </div>
                  ) : (
                    <div className="opp-match-pill">
                      <span className="unanalysed-note">No relevant product</span>
                      <span className={matchBadgeClass(bid.match_state)}>
                        {bid.match_state ?? 'NO_MATCH'}
                      </span>
                    </div>
                  )}

                  {bid.scope_of_work && (
                    <div className="bid-card-snippet">
                      {bid.scope_of_work.length > 120
                        ? `${bid.scope_of_work.slice(0, 120)}…`
                        : bid.scope_of_work}
                    </div>
                  )}
                </div>
                <div className="bid-card-footer">
                  <span style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-main)' }}>
                    {bid.estimated_value ? `₹${bid.estimated_value.toLocaleString()}` : 'Unstated value'}
                  </span>
                  <button className="btn-primary btn-sm" onClick={() => onSelectBid(bid.id)}>
                    Inspect →
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Pagination — only a window is mounted, keeping the tab responsive. */}
        {!loading && filteredBids.length > 0 && (
          <div className="list-foot">
            <span>
              Showing {visibleBids.length} of {filteredBids.length} bids
            </span>
            {visibleCount < filteredBids.length && (
              <button
                className="btn-secondary btn-sm"
                onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}
              >
                Load more (+{Math.min(PAGE_SIZE, filteredBids.length - visibleCount)})
              </button>
            )}
          </div>
        )}
      </div>
    </>
  );
};
