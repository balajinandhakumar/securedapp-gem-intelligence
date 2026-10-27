import React, { useMemo } from 'react';
import { BidIntelligenceRow } from '../types';
import { BidRow } from './BidRow';
import { EmptyState } from './EmptyState';
import { SectionHeader } from './SectionHeader';
import { BidRowListSkeleton } from './SkeletonLoader';

interface RecentIntelViewProps {
  bids: BidIntelligenceRow[];
  loading: boolean;
  onSelectBid: (bidId: string) => void;
  onNavigateBids: () => void;
}

/** How many recent rows this page shows before pointing at the full feed. */
const RECENT_LIMIT = 25;

/**
 * Recent bid intelligence — the most recently published bids that already
 * have persisted analysis, newest first.
 */
export const RecentIntelView: React.FC<RecentIntelViewProps> = ({
  bids,
  loading,
  onSelectBid,
  onNavigateBids,
}) => {
  const rows = useMemo(
    () => bids.filter((b) => b.analyzed).slice(0, RECENT_LIMIT),
    [bids]
  );
  const analyzedTotal = useMemo(() => bids.filter((b) => b.analyzed).length, [bids]);

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">Recent bid intelligence</h1>
        <p className="page-sub">
          Most recently published bids and the analysis the pipeline actually produced for them.
        </p>
      </div>

      <div className="card-panel">
        <SectionHeader
          title="Latest analyzed bids"
          subtitle={loading ? 'Loading…' : `Showing ${rows.length} of ${analyzedTotal} analyzed bids`}
        />

        {loading ? (
          <BidRowListSkeleton rows={5} />
        ) : rows.length === 0 ? (
          <EmptyState
            title="No analyzed bids yet"
            description="Bids appear here once the intelligence pipeline has analyzed them."
            action={
              <button className="btn-secondary btn-sm" onClick={onNavigateBids}>
                Open Bids
              </button>
            }
          />
        ) : (
          <div className="bid-row-list">
            {rows.map((row) => (
              <BidRow
                key={row.id}
                row={row}
                onSelectBid={onSelectBid}
                actionLabel={row.analyzed ? 'Open bid' : 'Analyze'}
              />
            ))}
          </div>
        )}

        {rows.length > 0 && (
          <div className="list-foot">
            <span>Newest publications first. Unanalyzed bids are listed on the Bids page.</span>
            <button className="list-foot-link" onClick={onNavigateBids}>
              View all bids
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
