import React from 'react';
import { scoreColor, scorePercent } from '../lib/format';

interface ScoreMetricProps {
  label: string;
  /** Backend score in the 0–1 range; null means the bid has no score. */
  value: number | null;
}

/** Label + score + mini bar, as used on the reference bid cards. */
export const ScoreMetric: React.FC<ScoreMetricProps> = ({ label, value }) => {
  const color = scoreColor(value);
  return (
    <div className="score-metric">
      <span className="score-metric-label">{label}</span>
      <span className="score-metric-value" style={{ color: value === null ? 'var(--text-dim)' : color }}>
        {value === null ? '—' : value.toFixed(2)}
      </span>
      <span className="score-bar">
        <b style={{ width: `${scorePercent(value)}%`, background: color }} />
      </span>
    </div>
  );
};
