import React from 'react';

export function TableSkeleton() {
  return (
    <div style={{ padding: '1rem' }}>
      {[1, 2, 3, 4, 5].map((i) => (
        <div key={i} style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', alignItems: 'center' }}>
          <div className="skeleton" style={{ width: '120px', height: '24px' }} />
          <div className="skeleton" style={{ flex: 1, height: '24px' }} />
          <div className="skeleton" style={{ width: '150px', height: '24px' }} />
          <div className="skeleton" style={{ width: '100px', height: '24px' }} />
          <div className="skeleton" style={{ width: '110px', height: '32px' }} />
        </div>
      ))}
    </div>
  );
}

export function CardGridSkeleton() {
  return (
    <div className="bid-grid">
      {[1, 2, 3, 4, 5, 6].map((i) => (
        <div key={i} className="bid-card" style={{ height: '220px' }}>
          <div className="skeleton" style={{ width: '40%', height: '20px', marginBottom: '0.75rem' }} />
          <div className="skeleton" style={{ width: '90%', height: '24px', marginBottom: '0.5rem' }} />
          <div className="skeleton" style={{ width: '60%', height: '16px', marginBottom: '1rem' }} />
          <div className="skeleton" style={{ width: '100%', height: '60px', marginBottom: '1rem' }} />
          <div className="skeleton" style={{ width: '30%', height: '28px' }} />
        </div>
      ))}
    </div>
  );
}

export function BidRowListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div aria-busy="true">
      {Array.from({ length: rows }).map((_, i) => (
        <div className="bid-row" key={i}>
          <div className="bid-row-main">
            <div className="skeleton" style={{ height: '14px', width: '35%', marginBottom: 8 }} />
            <div className="skeleton" style={{ height: '12px', width: '65%' }} />
          </div>
          <div className="bid-row-side">
            <div className="skeleton" style={{ height: '30px', width: '140px' }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function DrawerSkeleton() {
  return (
    <div style={{ padding: '1.5rem' }}>
      <div className="skeleton" style={{ width: '30%', height: '24px', marginBottom: '1rem' }} />
      <div className="skeleton" style={{ width: '80%', height: '36px', marginBottom: '0.5rem' }} />
      <div className="skeleton" style={{ width: '50%', height: '20px', marginBottom: '2rem' }} />

      <div className="skeleton" style={{ width: '100%', height: '120px', marginBottom: '1.5rem' }} />
      <div className="skeleton" style={{ width: '100%', height: '180px', marginBottom: '1.5rem' }} />
      <div className="skeleton" style={{ width: '100%', height: '140px' }} />
    </div>
  );
}
