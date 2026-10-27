import React from 'react';

interface EmptyStateProps {
  title: string;
  description: string;
  action?: React.ReactNode;
}

/** Neutral empty state used across every list view. */
export const EmptyState: React.FC<EmptyStateProps> = ({ title, description, action }) => (
  <div className="empty-state">
    <div className="empty-title">{title}</div>
    <div className="empty-desc">{description}</div>
    {action}
  </div>
);
