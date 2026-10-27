import React from 'react';
import { DashboardSummary } from '../types';
import { KpiTile } from './KpiTile';
import { IconBell, IconClockAlert, IconEyeSearch, IconFiles, IconTarget } from './icons';

interface MetricsOverviewProps {
  summary: DashboardSummary | null;
  loading: boolean;
}

/**
 * KPI strip — every number comes from GET /api/v1/dashboard/summary.
 * No hardcoded fallbacks: while loading, the tiles show skeletons instead of
 * invented figures.
 */
export const MetricsOverview: React.FC<MetricsOverviewProps> = ({ summary, loading }) => {
  if (loading || !summary) {
    return (
      <div className="metrics-row" aria-busy="true">
        {['Relevant matches', 'Needs review', 'Total bids', 'Closing soon', 'Notifications'].map(
          (label) => (
            <div className="kpi-tile" key={label}>
              <div className="kpi-top">
                <div className="kpi-icon" />
                <span className="kpi-label">{label}</span>
              </div>
              <div className="skeleton" style={{ height: '26px', width: '55%' }} />
              <div className="kpi-sub skeleton" style={{ height: '10px', width: '80%' }} />
            </div>
          )
        )}
      </div>
    );
  }

  const m = summary.metrics;
  const hasBids = m.total_bids > 0;

  return (
    <div className="metrics-row">
      <KpiTile
        label="Relevant matches"
        value={m.relevant_bids}
        icon={<IconTarget />}
        iconTone="positive"
        valueTone={m.relevant_bids > 0 ? 'positive' : 'muted'}
        sub="Relevance ≥ 0.70"
        highlight
      />

      <KpiTile
        label="Needs review"
        value={m.needs_review_bids}
        icon={<IconEyeSearch />}
        iconTone="warning"
        valueTone={m.needs_review_bids > 0 ? 'warning' : 'muted'}
        sub={
          m.possible_match_bids > 0
            ? `0.25–0.45 band · ${m.possible_match_bids} possible match`
            : '0.25–0.45 band'
        }
      />

      <KpiTile
        label="Total bids"
        value={m.total_bids}
        icon={<IconFiles />}
        iconTone="neutral"
        valueTone="neutral"
        sub={
          !hasBids
            ? 'No bids ingested yet'
            : m.pending_analysis > 0
              ? `${m.analyzed_bids} analyzed · ${m.pending_analysis} pending`
              : 'All bids analyzed'
        }
      />

      <KpiTile
        label="Closing soon"
        value={m.closing_soon_bids}
        icon={<IconClockAlert size={15} />}
        iconTone="accent"
        valueTone={m.closing_soon_bids > 0 ? 'accent' : 'muted'}
        sub={`≤ ${m.closing_soon_window_days} days to submission`}
      />

      <KpiTile
        label="Notifications"
        value={m.notifications}
        icon={<IconBell size={15} />}
        iconTone="accent"
        valueTone={m.notifications > 0 ? 'accent' : 'muted'}
        sub="High-relevance alerts"
      />
    </div>
  );
};
