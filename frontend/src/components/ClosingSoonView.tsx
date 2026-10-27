import React, { useMemo } from 'react';
import { BidIntelligenceRow } from '../types';
import { BidRow } from './BidRow';
import { EmptyState } from './EmptyState';
import { SectionHeader } from './SectionHeader';
import { BidRowListSkeleton } from './SkeletonLoader';

interface ClosingSoonViewProps {
  bids: BidIntelligenceRow[];
  windowDays: number | null;
  loading: boolean;
  onSelectBid: (bidId: string) => void;
}

/**
 * Closing soon — every bid whose deadline sits inside the backend's
 * closing-soon window, soonest first. The window length comes from the
 * dashboard summary; nothing is assumed client-side.
 */
export const ClosingSoonView: React.FC<ClosingSoonViewProps> = ({
  bids,
  windowDays,
  loading,
  onSelectBid,
}) => {
  const rows = useMemo(() => {
    if (windowDays === null) return [];
    return bids
      .filter(
        (b) => b.days_remaining !== null && b.days_remaining >= 0 && b.days_remaining <= windowDays
      )
      .sort((a, b) => (a.days_remaining ?? 0) - (b.days_remaining ?? 0));
  }, [bids, windowDays]);

  const unbounded = windowDays === null && !loading;

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">Closing soon</h1>
        <p className="page-sub">
          {windowDays === null
            ? 'Bids inside the configured submission window.'
            : `Bids within ${windowDays} days of their submission deadline, soonest first.`}
        </p>
      </div>

      <div className="card-panel">
        <SectionHeader
          title="Submission deadlines"
          subtitle={
            loading
              ? 'Loading closing deadlines…'
              : `${rows.length} of ${bids.length} bids inside the window`
          }
        />

        {loading ? (
          <BidRowListSkeleton />
        ) : unbounded ? (
          <EmptyState
            title="Summary not loaded"
            description="The closing-soon window is reported by the dashboard summary. Retry once the backend responds."
          />
        ) : rows.length === 0 ? (
          <EmptyState
            title="Nothing closing soon"
            description="No bids are currently within their submission window. Deadlines appear here as soon as they fall inside the window."
          />
        ) : (
          <div className="bid-row-list">
            {rows.map((row) => (
              <BidRow key={row.id} row={row} onSelectBid={onSelectBid} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
