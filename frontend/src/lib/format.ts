import { MatchState } from '../types';

/** Text colour for a 0–1 score, following the palette: green ≥0.70, blue ≥0.45, amber ≥0.25. */
export function scoreColor(score: number | null): string {
  if (score === null) return 'var(--text-dim)';
  if (score >= 0.7) return 'var(--accent-green)';
  if (score >= 0.45) return 'var(--s-possible-text)';
  if (score >= 0.25) return 'var(--s-review-text)';
  return 'var(--text-muted)';
}

/** Bar width percentage for a 0–1 score. */
export function scorePercent(score: number | null): number {
  if (score === null) return 0;
  return Math.round(Math.min(1, Math.max(0, score)) * 100);
}

export interface ChipMeta {
  text: string;
  cls: string;
}

/**
 * Deadline chip. Colour is never the only signal — the label always states
 * what the deadline actually is ("Closes in 2d", "Closed", "Unstated").
 */
export function deadlineMeta(days: number | null): ChipMeta {
  if (days === null) return { text: 'Unstated', cls: 'badge badge-unknown' };
  if (days < 0) return { text: 'Closed', cls: 'badge badge-no_match' };
  if (days === 0) return { text: 'Closes today', cls: 'badge badge-urgent' };
  if (days <= 3) return { text: `Closes in ${days}d`, cls: 'badge badge-urgent' };
  if (days <= 7) return { text: `Closes in ${days}d`, cls: 'badge badge-review' };
  return { text: `${days}d left`, cls: 'badge badge-unknown' };
}

/**
 * Match-state chip. Unanalyzed bids are stated as such — they are never
 * rendered as a score or a match state they do not have.
 */
export function matchStateMeta(
  matchState: MatchState | null,
  analyzed: boolean
): ChipMeta {
  if (!analyzed) return { text: 'Not yet analyzed', cls: 'badge badge-unknown' };
  switch (matchState) {
    case 'MATCH':
      return { text: 'MATCH', cls: 'badge badge-match' };
    case 'POSSIBLE_MATCH':
      return { text: 'POSSIBLE MATCH', cls: 'badge badge-possible' };
    case 'NEEDS_REVIEW':
      return { text: 'NEEDS REVIEW', cls: 'badge badge-review' };
    case 'NO_MATCH':
      return { text: 'NO MATCH', cls: 'badge badge-no_match' };
    default:
      return { text: 'UNMATCHED', cls: 'badge badge-unmatched' };
  }
}

/** Product chip shown next to the match state. */
export function productChip(productName: string | null, analyzed: boolean): ChipMeta | null {
  if (!analyzed || !productName) return null;
  return { text: productName, cls: 'badge badge-product' };
}

export function formatValue(value: number | null, currency: string): string {
  if (value === null || value === undefined) return '';
  const symbol = currency === 'INR' ? '₹' : `${currency} `;
  try {
    return `${symbol}${value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
  } catch {
    return `${symbol}${value}`;
  }
}

export function formatDate(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}
