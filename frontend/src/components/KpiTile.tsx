import React from 'react';

export type KpiTone = 'positive' | 'warning' | 'accent' | 'danger' | 'neutral';

interface KpiTileProps {
  label: string;
  value: number;
  icon: React.ReactNode;
  /** Colour treatment for the icon tile. */
  iconTone?: KpiTone;
  /** Colour treatment for the number; zero values are muted by the caller. */
  valueTone?: KpiTone | 'muted';
  sub?: string;
  /** Green left border for the headline KPI, matching the reference design. */
  highlight?: boolean;
}

const ICON_TONE_CLASS: Record<KpiTone, string> = {
  positive: ' kpi-icon-positive',
  warning: ' kpi-icon-warning',
  accent: ' kpi-icon-accent',
  danger: ' kpi-icon-danger',
  neutral: '',
};

const VALUE_TONE_CLASS: Record<string, string> = {
  positive: ' kpi-value-positive',
  warning: ' kpi-value-warning',
  accent: ' kpi-value-accent',
  muted: ' kpi-value-muted',
  neutral: '',
  danger: '',
};

/**
 * KPI tile. The value always comes from the backend summary — no fallback
 * numbers are ever substituted while data is loading or missing.
 */
export const KpiTile: React.FC<KpiTileProps> = ({
  label,
  value,
  icon,
  iconTone = 'neutral',
  valueTone = 'neutral',
  sub,
  highlight,
}) => {
  return (
    <div className={`kpi-tile${highlight ? ' kpi-tile-positive' : ''}`}>
      <div className="kpi-top">
        <div className={`kpi-icon${ICON_TONE_CLASS[iconTone]}`}>{icon}</div>
        <span className="kpi-label">{label}</span>
      </div>
      <div className={`kpi-value${VALUE_TONE_CLASS[valueTone] ?? ''}`}>{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
};
