import React, { useEffect } from 'react';
import { NotificationItem } from '../types';

interface NotificationsDrawerProps {
  notifications: NotificationItem[];
  loading: boolean;
  onClose: () => void;
}

export const NotificationsDrawer: React.FC<NotificationsDrawerProps> = ({
  notifications,
  loading,
  onClose,
}) => {
  // Escape closes the drawer, matching the backdrop click and Close button.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer-panel" style={{ maxWidth: '480px' }} onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.2rem' }}>
              <span className="badge badge-match">AUDIT LOG</span>
              <span style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>
                {notifications.length} {notifications.length === 1 ? 'event' : 'events'}
              </span>
            </div>
            <h2 style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-main)', margin: 0 }}>
              Intelligence Notifications Log
            </h2>
            <p style={{ fontSize: '0.74rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
              Automated high-relevance (&ge; 0.70) procurement alert dispatches
            </p>
          </div>
          <button className="btn-secondary btn-sm" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="drawer-body">
          {loading ? (
            <div style={{ padding: '2rem 1rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.82rem' }}>
              Loading notification records...
            </div>
          ) : notifications.length === 0 ? (
            <div className="empty-state">
              <div className="empty-title">No notifications recorded yet</div>
              <div className="empty-desc">
                High-relevance GeM opportunities matching SecuredApp products trigger automated alerts here.
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
              {notifications.map((notif) => {
                const state = notif.delivery_state || notif.status;
                const isDelivered = state === 'DELIVERED';
                const isFailed = state === 'FAILED';
                const badgeClass = isDelivered ? 'badge-match' : isFailed ? 'badge-urgent' : 'badge-review';

                return (
                  <div key={notif.id} className="detail-card">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem' }}>
                      <span className={`badge ${badgeClass}`}>{notif.notification_type}</span>
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>
                        {notif.sent_at
                          ? new Date(notif.sent_at).toLocaleString()
                          : `Not dispatched (${state})`}
                      </span>
                    </div>

                    <div style={{ fontSize: '0.8rem', color: 'var(--text-main)', fontWeight: 500, marginBottom: '0.25rem' }}>
                      Channel: <span style={{ color: 'var(--accent-cyan)' }}>{notif.channel}</span> &bull; {notif.recipient}
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                      <span className={`badge ${badgeClass}`}>{state}</span>
                      {notif.delivery_configured === false && (
                        <span style={{ fontSize: '0.68rem', color: 'var(--text-dim)' }}>
                          no delivery provider configured
                        </span>
                      )}
                    </div>

                    <div style={{ fontSize: '0.71rem', fontFamily: 'var(--font-mono)', color: 'var(--text-dim)', wordBreak: 'break-all' }}>
                      Key: {notif.deduplication_key}
                    </div>

                    {notif.delivery_note && (
                      <div style={{ fontSize: '0.68rem', color: 'var(--text-dim)', marginTop: '0.3rem' }}>
                        {notif.delivery_note}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
