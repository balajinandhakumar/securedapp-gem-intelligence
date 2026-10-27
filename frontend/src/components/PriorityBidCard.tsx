import React from 'react';
import { DashboardBidRow } from '../types';
import { BidRow } from './BidRow';

interface PriorityBidCardProps {
  row: DashboardBidRow;
  reason?: string | null;
  onSelectBid: (bidId: string) => void;
}

/**
 * Headline opportunity card — the first (strongest) entry of the relevant
 * list, rendered with the reference design's inset background and cyan rule.
 */
export const PriorityBidCard: React.FC<PriorityBidCardProps> = ({
  row,
  reason,
  onSelectBid,
}) => (
  <BidRow row={row} reason={reason} featured onSelectBid={onSelectBid} actionLabel="Open bid" />
);
