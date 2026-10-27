import React from 'react';
import { DashboardBidRow } from '../types';
import { formatValue } from '../lib/format';
import { DeadlineChip, ProductChip, StatusChip } from './StatusChip';
import { ScoreMetric } from './ScoreMetric';

export interface BidRowProps {
  row: DashboardBidRow;
  /** Real "why it matches" reason from the persisted analysis, when available. */
  reason?: string | null;
  /** First card of a list: inset background + cyan left rule. */
  featured?: boolean;
  onSelectBid: (bidId: string) => void;
  /** Action button label (defaults to "Open bid"). */
  actionLabel?: string;
}

/**
 * One bid in a list: chips, title, organisation/department meta, optional
 * "why" line, both scores with bars, deadline chip and the open action.
 * Every figure comes from the row the backend returned.
 */
export const BidRow: React.FC<BidRowProps> = ({
  row,
  reason,
  featured,
  onSelectBid,
  actionLabel = 'Open bid',
}) => {
  const metaBits = [
    row.organisation,
    row.category || 'General Procurement',
    formatValue(row.estimated_value, row.currency),
  ].filter(Boolean) as string[];

  return (
    <div className={`bid-row${featured ? ' bid-row-featured' : ''}`}>
      <div className="bid-row-main">
        <div className="bid-row-chips">
          <StatusChip matchState={row.match_state} analyzed={row.analyzed} />
          <ProductChip productName={row.matched_product} analyzed={row.analyzed} />
        </div>

        <div className="bid-row-title" title={row.title}>
          {row.title}
        </div>

        <div className="bid-row-meta">
          {metaBits.map((bit, i) => (
            <React.Fragment key={i}>
              {i > 0 && <span aria-hidden="true">·</span>}
              <span>{bit}</span>
            </React.Fragment>
          ))}
          {(row.gem_bid_id || row.bid_number) && (
            <>
              <span aria-hidden="true">·</span>
              <span className="bid-id-mono" style={{ display: 'inline', margin: 0 }}>
                {row.gem_bid_id || row.bid_number}
              </span>
            </>
          )}
        </div>

        {reason && (
          <div className="bid-row-why">
            <span className="bid-row-why-label">Why</span>
            {reason}
          </div>
        )}
      </div>

      <div className="bid-row-side">
        <div className="bid-row-scores">
          <ScoreMetric label="Relevance" value={row.analyzed ? row.relevance_score : null} />
          <ScoreMetric label="Opportunity" value={row.analyzed ? row.opportunity_score : null} />
        </div>
        <DeadlineChip days={row.days_remaining} />
        <button
          className={featured ? 'btn-primary btn-sm' : 'btn-secondary btn-sm'}
          onClick={() => onSelectBid(row.id)}
        >
          {actionLabel}
        </button>
      </div>
    </div>
  );
};
