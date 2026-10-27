import React, { useEffect, useState } from 'react';
import { AppTab, DashboardBidRow, DashboardSummary, ProductMatch } from '../types';
import { MetricsOverview } from './MetricsOverview';
import { BidRow } from './BidRow';
import { PriorityBidCard } from './PriorityBidCard';
import { EmptyState } from './EmptyState';
import { BidRowListSkeleton } from './SkeletonLoader';
import { IconArrowRight, IconClockAlert, IconEyeSearch, IconHistory, IconTarget } from './icons';

interface DashboardViewProps {
  summary: DashboardSummary | null;
  summaryLoading: boolean;
  onSelectBid: (bidId: string) => void;
  onNavigateTab: (tab: AppTab) => void;
}

type DashboardListTab = 'relevant' | 'possible' | 'closing' | 'recent';

/**
 * Dashboard — command centre.
 * KPI strip plus the three reference tabs (Relevant matches / Closing soon /
 * Recent bid intelligence). Every figure comes from the backend summary; the
 * "why" lines are read from each bid's persisted analysis, never invented.
 */
export const DashboardView: React.FC<DashboardViewProps> = ({
  summary,
  summaryLoading,
  onSelectBid,
  onNavigateTab,
}) => {
  const [activeList, setActiveList] = useState<DashboardListTab>('relevant');
  const [tabResolved, setTabResolved] = useState(false);
  const [reasons, setReasons] = useState<Record<string, string>>({});

  // Land on a list that actually has rows. The strip keeps "Relevant matches"
  // first; it still shows its own empty state (with the 0.70 threshold note)
  // when the matcher has not produced a high-relevance hit yet.
  useEffect(() => {
    if (tabResolved || !summary) return;
    if (summary.priority_opportunities.length === 0) {
      if (summary.possible_matches.length > 0) setActiveList('possible');
      else if (summary.action_required.length > 0) setActiveList('closing');
      else if (summary.recent_bids.length > 0) setActiveList('recent');
    }
    setTabResolved(true);
  }, [summary, tabResolved]);

  const metrics = summary?.metrics ?? null;
  const relevant = summary?.priority_opportunities ?? [];
  const possible = summary?.possible_matches ?? [];
  const closing = summary?.action_required ?? [];
  const recent = summary?.recent_bids ?? [];

  const rows: DashboardBidRow[] =
    activeList === 'relevant'
      ? relevant
      : activeList === 'possible'
        ? possible
        : activeList === 'closing'
          ? closing
          : recent;

  const totalBids = metrics?.total_bids ?? 0;
  const hasBids = totalBids > 0;

  // Real "why it matches" reasons from the stored analysis of shown rows.
  useEffect(() => {
    const missing = rows
      .filter((r) => r.analyzed && r.matched_product && !reasons[r.id])
      .slice(0, 6);
    if (missing.length === 0) return;

    let cancelled = false;
    (async () => {
      const next: Record<string, string> = {};
      await Promise.all(
        missing.map(async (row) => {
          try {
            const res = await fetch(`/api/v1/bids/${row.id}/analysis`);
            if (!res.ok) return;
            const data = await res.json();
            const matches: ProductMatch[] = data?.analysis?.product_matches ?? [];
            // Only a reason that belongs to the bid's actual matched product is
            // shown; a fallback product's "why" must never fill in for another.
            const hit = matches.find((m) => m.product_name === row.matched_product);
            if (hit?.reason) next[row.id] = hit.reason;
          } catch {
            /* the reason line is optional; missing text is shown as absence */
          }
        })
      );
      if (!cancelled && Object.keys(next).length > 0) {
        setReasons((prev) => ({ ...prev, ...next }));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [rows, reasons]);

  const loading = summaryLoading && !summary;

  const tabMeta =
    activeList === 'relevant'
      ? `Showing ${relevant.length} of ${metrics?.relevant_bids ?? 0}`
      : activeList === 'possible'
        ? `Showing ${possible.length} of ${metrics?.possible_match_bids ?? 0}`
        : activeList === 'closing'
          ? `Showing ${closing.length} of ${metrics?.closing_soon_bids ?? 0} within ${
              metrics?.closing_soon_window_days ?? 7
            } days`
          : `Showing ${recent.length} of ${totalBids}`;

  const emptyState =
    activeList === 'relevant' ? (
      <EmptyState
        title={hasBids ? 'No high-relevance opportunities yet' : 'No bid data available yet'}
        description={
          hasBids
            ? 'No analyzed bid has reached the 0.70 relevance threshold against the active product knowledge base.'
            : 'Import bid data or connect an approved source to begin analysis.'
        }
        action={
          !hasBids ? (
            <button className="btn-secondary btn-sm" onClick={() => onNavigateTab('ingestion')}>
              Go to Data Source
            </button>
          ) : undefined
        }
      />
    ) : activeList === 'possible' ? (
      <EmptyState
        title="No possible matches"
        description="No analyzed bid currently sits in the possible-match relevance band (0.45–0.70) against the active product knowledge base."
      />
    ) : activeList === 'closing' ? (
      <EmptyState
        title="Nothing closing soon"
        description="No bids are currently inside their submission window."
      />
    ) : (
      <EmptyState
        title="No bids to display"
        description="Bids appear here as soon as they are ingested from a configured data source."
      />
    );

  const foot =
    activeList === 'relevant'
      ? {
          note: 'Relevant bids only. NO_MATCH and unanalyzed bids are excluded here.',
          label: 'View all bids',
          tab: 'bids' as AppTab,
        }
      : activeList === 'possible'
        ? {
            note: 'Possible matches (0.45–0.70). Verify these tenders before bidding.',
            label: 'View all bids',
            tab: 'bids' as AppTab,
          }
        : activeList === 'closing'
          ? {
            note: `Bids within ${metrics?.closing_soon_window_days ?? 7} days of their submission deadline.`,
            label: 'Open closing soon',
            tab: 'closing-soon' as AppTab,
          }
        : {
            note: 'Most recently published bids and their analysis state.',
            label: 'Open recent intelligence',
            tab: 'recent' as AppTab,
          };

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">Dashboard</h1>
        <p className="page-sub">
          Relevant matches first. Closing soon and recent intelligence have their own pages.
        </p>
      </div>

      <MetricsOverview summary={summary} loading={summaryLoading} />

      <div className="card-panel" style={{ padding: 0, overflow: 'hidden' }}>
        {/* Reference tab strip — switches the list below in place */}
        <div className="panel-tabs" role="tablist" aria-label="Dashboard lists">
          <button
            role="tab"
            aria-selected={activeList === 'relevant'}
            className={`panel-tab${activeList === 'relevant' ? ' active' : ''}`}
            onClick={() => setActiveList('relevant')}
          >
            <IconTarget size={14} />
            Relevant matches ({relevant.length})
          </button>
          <button
            role="tab"
            aria-selected={activeList === 'possible'}
            className={`panel-tab${activeList === 'possible' ? ' active' : ''}`}
            onClick={() => setActiveList('possible')}
          >
            <IconEyeSearch size={14} />
            Possible matches ({possible.length})
          </button>
          <button
            role="tab"
            aria-selected={activeList === 'closing'}
            className={`panel-tab${activeList === 'closing' ? ' active' : ''}`}
            onClick={() => setActiveList('closing')}
          >
            <IconClockAlert size={14} />
            Closing soon ({closing.length})
          </button>
          <button
            role="tab"
            aria-selected={activeList === 'recent'}
            className={`panel-tab${activeList === 'recent' ? ' active' : ''}`}
            onClick={() => setActiveList('recent')}
          >
            <IconHistory size={14} />
            Recent bid intelligence ({recent.length})
          </button>
        </div>

        <div className="panel-strip-head">
          <span className="panel-strip-title">
            {activeList === 'relevant'
              ? 'Relevant matches'
              : activeList === 'possible'
                ? 'Possible matches'
                : activeList === 'closing'
                  ? 'Closing soon'
                  : 'Recent bid intelligence'}
          </span>
          <span className="panel-strip-meta">{tabMeta}</span>
        </div>

        {loading ? (
          <BidRowListSkeleton />
        ) : rows.length === 0 ? (
          emptyState
        ) : (
          <div className="bid-row-list">
            {rows.map((row, index) =>
              index === 0 ? (
                <PriorityBidCard
                  key={row.id}
                  row={row}
                  reason={reasons[row.id]}
                  onSelectBid={onSelectBid}
                />
              ) : (
                <BidRow
                  key={row.id}
                  row={row}
                  reason={reasons[row.id]}
                  onSelectBid={onSelectBid}
                  actionLabel={row.analyzed ? 'Open bid' : 'Analyze'}
                />
              )
            )}
          </div>
        )}

        <div className="list-foot">
          <span>{foot.note}</span>
          <button className="list-foot-link" onClick={() => onNavigateTab(foot.tab)}>
            {foot.label}
            <IconArrowRight size={13} />
          </button>
        </div>
      </div>
    </div>
  );
};
