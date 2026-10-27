import React, { useEffect, useState } from 'react';
import { AnalysisData, Bid, BoqItem, HumanReview } from '../types';
import { DrawerSkeleton } from './SkeletonLoader';

interface BidDetailDrawerProps {
  bid: Bid;
  analysis: AnalysisData | null;
  reviews: HumanReview[];
  loadingAnalysis: boolean;
  onClose: () => void;
  onSubmitReview: (bidId: string, decision: 'RELEVANT' | 'NOT_RELEVANT' | 'MAYBE', comments: string) => Promise<void>;
  onRunAnalysis: () => Promise<void>;
  analysisError: string | null;
  reviewError: string | null;
}

// Only these states mean the intelligence pipeline actually identified a product
// for the bid. NO_MATCH candidates (including the arbitrary top-ranked catalogue
// row a tie at zero produces) must never be presented as that bid's product.
const MATCHED_STATES = ['MATCH', 'POSSIBLE_MATCH', 'NEEDS_REVIEW'] as const;

// ── Small helper components ────────────────────────────────────────────────

function SectionTitle({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="section-title-sm">
      {icon}
      {children}
    </div>
  );
}

// BoQ lists can carry hundreds of rows. Collapsed, the section shows this many
// items; the expand control reveals every persisted line item, so nothing is
// permanently hidden.
const BOQ_INITIAL_VISIBLE = 20;

// Fields with a known meaning (rendered with a fixed layout). Any other
// persisted column is still displayed as a labelled key/value pair.
const BOQ_KNOWN_FIELDS = new Set([
  'item_number',
  'title',
  'description',
  'quantity',
  'unit',
  'consignee_id',
  'delivery_period',
]);

function humanizeField(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * One BoQ line item: item number, title, description, quantity, unit plus any
 * other persisted columns (consignee, delivery period, unknown CSV headers).
 */
function BoqItemRow({ item }: { item: BoqItem }) {
  const extras = Object.entries(item).filter(
    ([key, value]) =>
      !BOQ_KNOWN_FIELDS.has(key) &&
      value !== null &&
      value !== undefined &&
      String(value).trim() !== ''
  );
  return (
    <div
      style={{
        background: 'var(--bg-surface-2)',
        border: '1px solid var(--border-color)',
        borderRadius: 'var(--r-sm)',
        padding: '0.4rem 0.6rem',
        fontSize: '0.74rem',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem' }}>
        <span style={{ color: 'var(--text-main)', fontWeight: 600 }}>
          {item.item_number ? `${item.item_number}. ` : ''}
          {item.title || item.description || 'Item'}
        </span>
        {(item.quantity || item.unit) && (
          <span style={{ color: 'var(--accent-cyan)', whiteSpace: 'nowrap' }}>
            {[item.quantity, item.unit].filter(Boolean).join(' ')}
          </span>
        )}
      </div>
      {item.description && item.title && item.description !== item.title && (
        <div style={{ color: 'var(--text-dim)', marginTop: '0.15rem' }}>{item.description}</div>
      )}
      {(item.consignee_id || item.delivery_period) && (
        <div style={{ color: 'var(--text-dim)', marginTop: '0.15rem', fontSize: '0.7rem' }}>
          {[
            item.consignee_id && `Consignee: ${item.consignee_id}`,
            item.delivery_period && `Delivery period: ${item.delivery_period}`,
          ]
            .filter(Boolean)
            .join('  ·  ')}
        </div>
      )}
      {extras.length > 0 && (
        <div style={{ color: 'var(--text-dim)', marginTop: '0.15rem', fontSize: '0.7rem' }}>
          {extras.map(([key, value]) => `${humanizeField(key)}: ${String(value)}`).join('  ·  ')}
        </div>
      )}
    </div>
  );
}

/**
 * Bill-of-Quantities evidence for a bid. BoQ is bid-level data (not analysis
 * output) so it is shown whenever it is known, even for an unanalysed bid.
 * Every persisted line item is reachable: the collapsed state shows an initial
 * page and the expand control reveals the full list. Missing provenance is
 * handled explicitly: an attempted-but-empty enrichment is stated, and a bid
 * never enriched renders nothing at all.
 */
function BoqSection({ bid }: { bid: Bid }) {
  const boq = bid.boq_items;
  const items = Array.isArray(boq?.items) ? boq!.items : [];
  const hasItems = items.length > 0;
  const [showAll, setShowAll] = useState(false);

  if (!hasItems && !bid.boq_checked_at) return null;

  const expandable = items.length > BOQ_INITIAL_VISIBLE;
  const visible = showAll || !expandable ? items : items.slice(0, BOQ_INITIAL_VISIBLE);
  const remaining = items.length - visible.length;

  return (
    <div className="drawer-section">
      <SectionTitle
        icon={
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="8" y1="6" x2="21" y2="6"/>
            <line x1="8" y1="12" x2="21" y2="12"/>
            <line x1="8" y1="18" x2="21" y2="18"/>
            <line x1="3" y1="6" x2="3.01" y2="6"/>
            <line x1="3" y1="12" x2="3.01" y2="12"/>
            <line x1="3" y1="18" x2="3.01" y2="18"/>
          </svg>
        }
      >
        Bill of Quantities (BoQ)
      </SectionTitle>

      {hasItems ? (
        <div className="detail-card">
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: '0.5rem',
              flexWrap: 'wrap',
              marginBottom: '0.55rem',
            }}
          >
            <span style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-main)' }}>
              {boq?.item_count ?? items.length} line item{items.length === 1 ? '' : 's'}
            </span>
            <div style={{ display: 'flex', gap: '0.45rem', alignItems: 'center', flexWrap: 'wrap' }}>
              {boq?.retrieved_at && (
                <span style={{ fontSize: '0.68rem', color: 'var(--text-dim)' }}>
                  Retrieved {new Date(boq.retrieved_at).toLocaleString()}
                </span>
              )}
              {boq?.source_url && (
                <a
                  className="btn-secondary btn-sm"
                  href={boq.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={boq.source_url}
                >
                  Open BoQ source
                </a>
              )}
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
            {visible.map((item, i) => (
              <BoqItemRow key={i} item={item} />
            ))}
          </div>

          {expandable && (
            <div
              style={{
                marginTop: '0.5rem',
                display: 'flex',
                gap: '0.5rem',
                alignItems: 'center',
                flexWrap: 'wrap',
              }}
            >
              <button
                type="button"
                className="btn-secondary btn-sm"
                onClick={() => setShowAll((v) => !v)}
              >
                {showAll
                  ? `Show first ${BOQ_INITIAL_VISIBLE}`
                  : `Show all ${items.length} line items`}
              </button>
              <span style={{ fontSize: '0.68rem', color: 'var(--text-dim)' }}>
                {showAll
                  ? `All ${items.length} persisted line items shown.`
                  : `Showing ${visible.length} of ${items.length}; ${remaining} more available.`}
              </span>
            </div>
          )}
          {!boq?.source_url && (
            <div style={{ fontSize: '0.68rem', color: 'var(--text-dim)', marginTop: '0.45rem' }}>
              Source document URL was not recorded for this BoQ.
            </div>
          )}
        </div>
      ) : (
        <div className="detail-card">
          <p style={{ fontSize: '0.79rem', color: 'var(--text-muted)', margin: 0 }}>
            No Bill of Quantities was published for this bid.
            {bid.boq_checked_at && (
              <> Enrichment was last attempted {new Date(bid.boq_checked_at).toLocaleString()}.</>
            )}
          </p>
        </div>
      )}
    </div>
  );
}


// ── Main Drawer ────────────────────────────────────────────────────────────

export const BidDetailDrawer: React.FC<BidDetailDrawerProps> = ({
  bid,
  analysis,
  reviews,
  loadingAnalysis,
  onClose,
  onSubmitReview,
  onRunAnalysis,
  analysisError,
  reviewError,
}) => {
  const [reviewDecision, setReviewDecision] = useState<'RELEVANT' | 'NOT_RELEVANT' | 'MAYBE'>('RELEVANT');
  const [comments, setComments]             = useState('');
  const [submitting, setSubmitting]         = useState(false);

  // Escape closes the drawer, matching the backdrop click and Close button.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const handleReviewSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await onSubmitReview(bid.id, reviewDecision, comments);
      setComments('');
    } finally {
      setSubmitting(false);
    }
  };

  const highestMatch =
    analysis?.candidate_products && analysis.candidate_products.length > 0
      ? analysis.candidate_products.find((c) => (MATCHED_STATES as readonly string[]).includes(c.match_state)) ?? null
      : null;

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer-panel" onClick={(e) => e.stopPropagation()}>

        {/* ── Header ──────────────────────────────────────────── */}
        <div className="drawer-header">
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', gap: '0.45rem', alignItems: 'center', marginBottom: '0.3rem', flexWrap: 'wrap' }}>
              <span className="badge badge-possible" style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                {bid.gem_bid_id || bid.bid_number || 'BID'}
              </span>
              {bid.organisation && (
                <span style={{ fontSize: '0.73rem', color: 'var(--text-muted)' }}>
                  {bid.organisation}
                </span>
              )}
            </div>
            <h2 style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-main)', lineHeight: 1.3, margin: 0 }}>
              {bid.title}
            </h2>
            {(bid.category || bid.location) && (
              <div style={{ fontSize: '0.72rem', color: 'var(--text-dim)', marginTop: '0.22rem' }}>
                {[bid.category || 'General Procurement', bid.location].filter(Boolean).join(' · ')}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: '0.45rem', alignItems: 'center', flexShrink: 0 }}>
            {bid.source_url && (
              <a
                className="btn-secondary btn-sm"
                href={bid.source_url}
                target="_blank"
                rel="noopener noreferrer"
                title={bid.source_url}
              >
                Open source
              </a>
            )}
            <button className="btn-secondary btn-sm" onClick={onClose} aria-label="Close">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
              Close
            </button>
          </div>
        </div>

        {/* ── Body ────────────────────────────────────────────── */}
        <div className="drawer-body">
          {analysisError && (
            <div className="alert-error">{analysisError}</div>
          )}

          {/* No analysis, not loading */}
          {!analysis && !loadingAnalysis && (
            <div className="empty-state">
              <div className="empty-title">Not yet analyzed</div>
              <div className="empty-desc">
                Scores are never estimated. Analysis has not been run for this bid yet; run the
                intelligence pipeline to produce real relevance and opportunity figures.
              </div>
              <button
                className="btn-primary btn-sm"
                onClick={onRunAnalysis}
                style={{ marginTop: '0.35rem' }}
              >
                Run Analysis
              </button>
            </div>
          )}

          {/* Loading */}
          {loadingAnalysis ? (
            <DrawerSkeleton />
          ) : analysis ? (
            <>
              {/* ── Intelligence KPI strip ─────────────────────── */}
              <div className="intel-kpi-strip">
                <div>
                  <span className="intel-kpi-label">Product Match</span>
                  <div className="intel-kpi-value">
                    {highestMatch
                      ? `${Math.round(highestMatch.final_relevance_score * 100)}%`
                      : 'No match'}
                  </div>
                  {highestMatch && (
                    <span
                      className={`badge badge-${highestMatch.match_state.toLowerCase()}`}
                      style={{ marginTop: '0.22rem' }}
                    >
                      {highestMatch.match_state}
                    </span>
                  )}
                </div>

                <div>
                  <span className="intel-kpi-label">Opportunity</span>
                  <div className="intel-kpi-value" style={{ color: 'var(--accent-green)' }}>
                    {analysis.opportunity?.opportunity_score
                      ? `${Math.round(analysis.opportunity.opportunity_score * 100)}%`
                      : 'N/A'}
                  </div>
                  {analysis.opportunity && (
                    <span className="badge badge-confirmed" style={{ marginTop: '0.22rem' }}>
                      {analysis.opportunity.opportunity_label.replace('_', ' ')}
                    </span>
                  )}
                </div>

                <div>
                  <span className="intel-kpi-label">Deadline</span>
                  <div className="intel-kpi-value">
                    {analysis.intelligence?.deadline_intelligence?.days_remaining !== undefined
                      ? `${analysis.intelligence.deadline_intelligence.days_remaining}d`
                      : '—'}
                  </div>
                  {analysis.intelligence?.deadline_intelligence?.status && (
                    <span
                      className={`badge badge-${analysis.intelligence.deadline_intelligence.status.toLowerCase()}`}
                      style={{ marginTop: '0.22rem' }}
                    >
                      {analysis.intelligence.deadline_intelligence.status}
                    </span>
                  )}
                </div>

                <div>
                  <span className="intel-kpi-label">Est. Value</span>
                  <div
                    className="intel-kpi-value"
                    style={{ fontSize: '0.88rem', color: 'var(--accent-cyan)' }}
                  >
                    {bid.estimated_value ? `₹${bid.estimated_value.toLocaleString()}` : 'Unstated'}
                  </div>
                </div>
              </div>

              {/* ── Section 1: Product Match ───────────────────── */}
              <div className="drawer-section">
                <SectionTitle
                  icon={
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <polygon points="12 2 2 7 12 12 22 7 12 2"/>
                      <polyline points="2 17 12 22 22 17"/>
                    </svg>
                  }
                >
                  Product Capability Match
                </SectionTitle>

                {highestMatch ? (
                  <div className="detail-card">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.45rem' }}>
                      <span style={{ fontWeight: 700, fontSize: '0.92rem', color: 'var(--text-main)' }}>
                        {highestMatch.product_name}
                      </span>
                      <span className={`badge badge-${highestMatch.match_state.toLowerCase()}`}>
                        {Math.round(highestMatch.final_relevance_score * 100)}% · {highestMatch.match_state}
                      </span>
                    </div>

                    <p style={{ fontSize: '0.79rem', color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: highestMatch.signals?.length ? '0.75rem' : 0 }}>
                      {highestMatch.reason}
                    </p>

                    {highestMatch.signals && highestMatch.signals.length > 0 && (
                      <div>
                        <div style={{ fontSize: '0.67rem', color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600, marginBottom: '0.38rem' }}>
                          Match Signals ({highestMatch.signals.length})
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.38rem' }}>
                          {highestMatch.signals.map((sig, i) => (
                            <div
                              key={i}
                              style={{
                                background: 'var(--bg-surface-2)',
                                border: '1px solid var(--border-color)',
                                borderRadius: 'var(--r-sm)',
                                padding: '0.42rem 0.6rem',
                                fontSize: '0.74rem',
                              }}
                            >
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: sig.snippet ? '0.18rem' : 0 }}>
                                <span style={{ fontWeight: 600, color: 'var(--accent-cyan)' }}>{sig.text}</span>
                                <span className={`badge ${sig.strength === 'EXCLUSION' ? 'badge-urgent' : 'badge-match'}`}>
                                  {sig.strength} · {sig.field}
                                </span>
                              </div>
                              {sig.snippet && (
                                <div style={{ color: 'var(--text-dim)', fontStyle: 'italic', fontSize: '0.71rem' }}>
                                  "{sig.snippet}"
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="detail-card">
                    <p style={{ fontSize: '0.79rem', color: 'var(--text-muted)' }}>
                      No product capabilities matched for this procurement notice.
                    </p>
                  </div>
                )}
              </div>

              {/* ── Section 2: Extracted Requirements ─────────── */}
              <div className="drawer-section">
                <SectionTitle
                  icon={
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                      <polyline points="14 2 14 8 20 8"/>
                    </svg>
                  }
                >
                  Extracted Requirements
                </SectionTitle>

                {analysis.intelligence?.requirements && analysis.intelligence.requirements.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.42rem' }}>
                    {analysis.intelligence.requirements.map((req, i) => (
                      <div key={i} className="detail-card" style={{ marginBottom: 0 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.22rem' }}>
                          <span style={{ fontSize: '0.7rem', color: 'var(--accent-cyan)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                            {req.category.replace(/_/g, ' ')}
                          </span>
                          <span className="badge badge-confirmed">Mandatory</span>
                        </div>
                        <div style={{ fontSize: '0.79rem', color: 'var(--text-main)' }}>{req.requirement_text}</div>
                        {req.evidence?.evidence && (
                          <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)', marginTop: '0.32rem', fontStyle: 'italic' }}>
                            "{req.evidence.evidence}"
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="detail-card">
                    <p style={{ fontSize: '0.79rem', color: 'var(--text-muted)' }}>
                      No specific structured technical requirements extracted.
                    </p>
                  </div>
                )}
              </div>

              {/* ── Section 3: Eligibility ────────────────────── */}
              <div className="drawer-section">
                <SectionTitle
                  icon={
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                      <polyline points="22 4 12 14.01 9 11.01"/>
                    </svg>
                  }
                >
                  Tender Eligibility Assessment
                </SectionTitle>

                {analysis.intelligence?.eligibility_assessments && analysis.intelligence.eligibility_assessments.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.42rem' }}>
                    {analysis.intelligence.eligibility_assessments.map((el, i) => (
                      <div key={i} className="detail-card" style={{ marginBottom: 0 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.22rem' }}>
                          <span style={{ fontWeight: 600, fontSize: '0.79rem', color: 'var(--text-main)' }}>
                            {el.requirement_name}
                          </span>
                          <span className={`badge ${el.status === 'CONFIRMED' ? 'badge-confirmed' : 'badge-review'}`}>
                            {el.status === 'CONFIRMED' ? 'Confirmed' : 'Verify'}
                          </span>
                        </div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{el.reason}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="detail-card">
                    <p style={{ fontSize: '0.79rem', color: 'var(--text-muted)' }}>
                      Standard eligibility terms apply. No restrictive pre-qualification barriers identified.
                    </p>
                  </div>
                )}
              </div>

              {/* ── Section 4: Opportunity Breakdown ─────────── */}
              {analysis.opportunity?.score_breakdown && (
                <div className="drawer-section">
                  <SectionTitle
                    icon={
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <line x1="18" y1="20" x2="18" y2="10"/>
                        <line x1="12" y1="20" x2="12" y2="4"/>
                        <line x1="6" y1="20" x2="6" y2="14"/>
                      </svg>
                    }
                  >
                    Opportunity Score Breakdown
                  </SectionTitle>

                  <div className="detail-card">
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.55rem' }}>
                      {analysis.opportunity.score_breakdown.map((comp, i) => (
                        <div
                          key={i}
                          style={{
                            background: 'var(--bg-surface)',
                            border: '1px solid var(--border-color)',
                            borderRadius: 'var(--r-sm)',
                            padding: '0.6rem 0.72rem',
                          }}
                        >
                          <div style={{ fontSize: '0.69rem', color: 'var(--text-muted)' }}>
                            {comp.name} ({Math.round(comp.weight * 100)}% wt)
                          </div>
                          <div style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text-main)', marginTop: '0.12rem' }}>
                            {Math.round(comp.raw_value * 100)}%
                          </div>
                          <div style={{ fontSize: '0.68rem', color: 'var(--text-dim)' }}>{comp.description}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* ── Section 5: Human Review ───────────────────── */}
              <div className="drawer-section">
                <SectionTitle
                  icon={
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
                      <circle cx="8.5" cy="7" r="4"/>
                    </svg>
                  }
                >
                  Human Review &amp; Triage
                </SectionTitle>

                <form onSubmit={handleReviewSubmit} className="detail-card">
                  <div style={{ marginBottom: '0.82rem' }}>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontWeight: 600, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                      Relevance Decision
                    </div>
                    <div style={{ display: 'flex', gap: '0.42rem' }}>
                      {(['RELEVANT', 'MAYBE', 'NOT_RELEVANT'] as const).map((d) => (
                        <button
                          key={d}
                          type="button"
                          className={reviewDecision === d ? 'btn-primary btn-sm' : 'btn-secondary btn-sm'}
                          onClick={() => setReviewDecision(d)}
                          style={{ flex: 1, justifyContent: 'center' }}
                        >
                          {d === 'NOT_RELEVANT' ? 'Not Relevant' : d.charAt(0) + d.slice(1).toLowerCase()}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div style={{ marginBottom: '0.82rem' }}>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontWeight: 600, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                      Reviewer Notes
                    </div>
                    <textarea
                      className="form-textarea"
                      style={{ minHeight: '60px' }}
                      placeholder="Strategic evaluation notes, action items…"
                      value={comments}
                      onChange={(e) => setComments(e.target.value)}
                    />
                  </div>

                  <button type="submit" className="btn-primary" disabled={submitting} style={{ width: '100%', justifyContent: 'center' }}>
                    {submitting ? 'Recording…' : 'Record Decision'}
                  </button>

                  {reviewError && (
                    <div className="alert-error" style={{ marginTop: '0.55rem', marginBottom: 0 }}>
                      {reviewError}
                    </div>
                  )}

                  <button
                    type="button"
                    className="btn-secondary btn-sm"
                    onClick={onRunAnalysis}
                    disabled={loadingAnalysis}
                    style={{ width: '100%', justifyContent: 'center', marginTop: '0.5rem' }}
                  >
                    Re-run Analysis
                  </button>
                </form>

                {/* Review History */}
                {reviews.length > 0 && (
                  <div style={{ marginTop: '0.65rem' }}>
                    <div style={{ fontSize: '0.67rem', color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700, marginBottom: '0.35rem' }}>
                      Review History ({reviews.length})
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.38rem' }}>
                      {reviews.map((rev) => (
                        <div
                          key={rev.id}
                          style={{
                            background: 'var(--bg-surface)',
                            border: '1px solid var(--border-color)',
                            borderRadius: 'var(--r-sm)',
                            padding: '0.52rem 0.7rem',
                            fontSize: '0.74rem',
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: rev.comments ? '0.18rem' : 0 }}>
                            <span className={`badge ${rev.relevance_decision === 'RELEVANT' ? 'badge-match' : rev.relevance_decision === 'MAYBE' ? 'badge-review' : 'badge-no_match'}`}>
                              {rev.relevance_decision}
                            </span>
                            <span style={{ fontSize: '0.68rem', color: 'var(--text-dim)' }}>
                              {new Date(rev.reviewed_at).toLocaleString()}
                            </span>
                          </div>
                          {rev.comments && (
                            <div style={{ color: 'var(--text-muted)', marginTop: '0.18rem' }}>
                              "{rev.comments}"
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </>
          ) : null}

          {/* BoQ is bid-level evidence, not analysis output, so it is shown in
              every drawer state (including a bid that has not been analysed). */}
          <BoqSection bid={bid} />
        </div>
      </div>
    </div>
  );
};
