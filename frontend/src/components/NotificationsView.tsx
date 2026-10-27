import React from 'react';
import { NotificationItem } from '../types';
import { EmptyState } from './EmptyState';
import { SectionHeader } from './SectionHeader';

interface NotificationsViewProps {
  notifications: NotificationItem[];
  loading: boolean;
  onSelectBid: (bidId: string) => void;
}

/** Explicit delivery state badge: QUEUED | DELIVERED | FAILED. */
function deliveryBadge(state: string | undefined): string {
  if (state === 'DELIVERED') return 'badge badge-match';
  if (state === 'FAILED') return 'badge badge-urgent';
  return 'badge badge-review';
}

/**
 * Notifications page — the persisted notification log. An empty log is shown
 * as an empty state: alerts are only generated when a bid actually reaches
 * the relevance threshold, so the count is never padded.
 */
export const NotificationsView: React.FC<NotificationsViewProps> = ({
  notifications,
  loading,
  onSelectBid,
}) => {
  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">Notifications</h1>
        <p className="page-sub">
          Automated alerts generated when a bid reaches the 0.70 relevance threshold.
        </p>
      </div>

      <div className="card-panel">
        <SectionHeader
          title="Notification log"
          subtitle={
            loading
              ? 'Loading notification records…'
              : `${notifications.length} ${notifications.length === 1 ? 'event' : 'events'} recorded`
          }
        />

        {loading ? (
          <div className="skeleton" style={{ height: '120px' }} aria-busy="true" />
        ) : notifications.length === 0 ? (
          <EmptyState
            title="No notifications recorded yet"
            description="High-relevance GeM opportunities matching SecuredApp products trigger automated alerts here."
          />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
            {notifications.map((notif) => (
              <div key={notif.id} className="detail-card" style={{ marginBottom: 0 }}>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: '0.6rem',
                    marginBottom: '0.4rem',
                    flexWrap: 'wrap',
                  }}
                >
                  <span className="badge badge-product">{notif.notification_type}</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>
                    {notif.sent_at ? new Date(notif.sent_at).toLocaleString() : 'Not dispatched yet'}
                  </span>
                </div>

                <div style={{ fontSize: '0.8rem', color: 'var(--text-main)', fontWeight: 500 }}>
                  Channel:{' '}
                  <span style={{ color: 'var(--accent-cyan)' }}>{notif.channel}</span> ·{' '}
                  {notif.recipient}
                </div>

                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: '0.6rem',
                    marginTop: '0.5rem',
                    flexWrap: 'wrap',
                  }}
                >
                  <span className={deliveryBadge(notif.delivery_state)}>
                    {notif.delivery_state || notif.status}
                  </span>
                  {notif.delivery_state && notif.status !== notif.delivery_state && (
                    <span style={{ fontSize: '0.68rem', color: 'var(--text-dim)' }}>
                      stored status: {notif.status}
                    </span>
                  )}
                  {notif.bid_id && (
                    <button
                      className="btn-secondary btn-sm"
                      onClick={() => onSelectBid(notif.bid_id)}
                    >
                      Open bid
                    </button>
                  )}
                </div>

                {notif.delivery_note && (
                  <div style={{ fontSize: '0.68rem', color: 'var(--text-dim)', marginTop: '0.4rem' }}>
                    {notif.delivery_note}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
