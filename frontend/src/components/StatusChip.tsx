import React from 'react';
import { MatchState } from '../types';
import { deadlineMeta, matchStateMeta, productChip } from '../lib/format';

/** Match-state chip: MATCH green, POSSIBLE_MATCH blue, NEEDS_REVIEW amber,
 *  NO_MATCH neutral, unanalyzed stated explicitly. */
export const StatusChip: React.FC<{
  matchState: MatchState | null;
  analyzed: boolean;
}> = ({ matchState, analyzed }) => {
  const meta = matchStateMeta(matchState, analyzed);
  return <span className={meta.cls}>{meta.text}</span>;
};

/** Matched product chip (cyan), rendered when a product really matched.
 *  When a bid has been analysed but no product matched, shows "No Matching Product".
 */
export const ProductChip: React.FC<{
  productName: string | null;
  analyzed: boolean;
}> = ({ productName, analyzed }) => {
  if (!analyzed) return null;
  if (!productName) return <span className="badge badge-no_match">No Matching Product</span>;
  const meta = productChip(productName, analyzed);
  return <span className={meta.cls}>{meta.text}</span>;
};

/** Deadline chip: colour is paired with an explicit label, never colour alone. */
export const DeadlineChip: React.FC<{ days: number | null }> = ({ days }) => {
  const meta = deadlineMeta(days);
  return <span className={meta.cls}>{meta.text}</span>;
};
