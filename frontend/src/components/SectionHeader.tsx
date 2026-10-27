import React from 'react';

interface SectionHeaderProps {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}

/** Panel header: title, optional supporting line, optional right-hand actions. */
export const SectionHeader: React.FC<SectionHeaderProps> = ({ title, subtitle, actions }) => (
  <div className="panel-header">
    <div>
      <h2 className="panel-title">{title}</h2>
      {subtitle && <p className="panel-subtitle">{subtitle}</p>}
    </div>
    {actions && <div>{actions}</div>}
  </div>
);
