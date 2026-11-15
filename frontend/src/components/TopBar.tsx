import React from 'react';
import { IconBell, IconSearch, IconSunMoon, IconLogout } from './icons';

interface TopBarProps {
  search: string;
  onSearchChange: (value: string) => void;
  theme: 'dark' | 'light';
  onToggleTheme: () => void;
  onOpenNotifications: () => void;
  notificationCount: number;
  user?: { name?: string | null; email?: string | null; role?: string } | null;
  onLogout?: () => void;
}

/**
 * Global top bar: search, theme toggle, notification drawer, user profile, logout.
 * Search is owned by the shell so it can drive the Bids page directly.
 */
export const TopBar: React.FC<TopBarProps> = ({
  search,
  onSearchChange,
  theme,
  onToggleTheme,
  onOpenNotifications,
  notificationCount,
  user,
  onLogout,
}) => {
  const initials = user?.name
    ? user.name
        .split(' ')
        .map((part) => part[0])
        .join('')
        .toUpperCase()
        .slice(0, 2)
    : user?.email?.split('@')[0]?.toUpperCase().slice(0, 2) || 'SA';

  const handleLogout = () => {
    if (onLogout) onLogout();
  };

  return (
    <header className="topbar">
      <label className="topbar-search">
        <IconSearch size={15} />
        <input
          type="search"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search bids, organisations, products"
          aria-label="Search bids, organisations, products"
        />
      </label>

      <div className="topbar-actions">
        <button
          className="theme-toggle-btn"
          onClick={onToggleTheme}
          title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          aria-label="Toggle theme"
        >
          <IconSunMoon size={16} />
        </button>

        <button
          className="notif-btn"
          onClick={onOpenNotifications}
          aria-label="Open notifications"
          title="Notifications"
        >
          <IconBell size={15} />
          {notificationCount > 0 && <span className="notif-count">{notificationCount}</span>}
        </button>

        {user && onLogout && (
          <div className="user-profile" aria-label="User profile">
            <div className="topbar-avatar" title={`${user.name} (${user.role})`}>
              {initials}
            </div>
            <button
              className="btn-secondary btn-sm"
              onClick={handleLogout}
              aria-label="Sign out"
              title="Sign out"
            >
              <IconLogout size={14} />
              Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  );
};
