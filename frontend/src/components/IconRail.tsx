import React from 'react';
import { AppTab } from '../types';
import {
  IconBell,
  IconBox,
  IconClockAlert,
  IconDashboard,
  IconDatabase,
  IconHistory,
  IconListSearch,
  IconMapPin,
  IconMonitor,
  IconShieldCheck,
} from './icons';

interface IconRailProps {
  activeTab: AppTab;
  onNavigate: (tab: AppTab) => void;
  notificationCount: number;
}

const RAIL_ITEMS: { id: AppTab; label: string; icon: React.ReactNode }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: <IconDashboard /> },
  { id: 'bids', label: 'Bids', icon: <IconListSearch /> },
  { id: 'closing-soon', label: 'Closing soon', icon: <IconClockAlert /> },
  { id: 'recent', label: 'Recent bid intelligence', icon: <IconHistory /> },
  { id: 'products', label: 'Products', icon: <IconBox /> },
  { id: 'ingestion', label: 'Data Source', icon: <IconDatabase /> },
  { id: 'state-tenders', label: 'State Tenders', icon: <IconBox /> },
  { id: 'state-wise-bids', label: 'State-wise Bids', icon: <IconListSearch /> },
  { id: 'all-india-matches', label: 'All India – Product Relevant Bids', icon: <IconMapPin /> },
  { id: 'notifications', label: 'Notifications', icon: <IconBell /> },
  { id: 'scraper-monitoring', label: 'Scraper & Source Monitoring', icon: <IconMonitor /> },
];

/**
 * Icon-only navigation rail. Labels are exposed through `title` and
 * `aria-label`, so the compact form stays accessible.
 */
export const IconRail: React.FC<IconRailProps> = ({
  activeTab,
  onNavigate,
  notificationCount,
}) => {
  return (
    <nav className="icon-rail" aria-label="Main navigation">
      <div className="rail-logo" title="SecuredApp GeM Bid Intelligence">
        <IconShieldCheck size={19} />
      </div>

      {RAIL_ITEMS.map(({ id, label, icon }) => (
        <button
          key={id}
          className={`rail-item${activeTab === id ? ' active' : ''}`}
          onClick={() => onNavigate(id)}
          aria-label={label}
          aria-current={activeTab === id ? 'page' : undefined}
          title={label}
          style={
            id === 'notifications' && notificationCount > 0
              ? { color: 'var(--accent-cyan)' }
              : undefined
          }
        >
          {icon}
        </button>
      ))}
    </nav>
  );
};
