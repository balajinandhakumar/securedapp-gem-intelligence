import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AnalysisData,
  AppTab,
  Bid,
  BidIntelligenceRow,
  DashboardSummary,
  HumanReview,
  NotificationItem,
  Product,
} from './types';
import { IconRail } from './components/IconRail';
import { TopBar } from './components/TopBar';
import { DashboardView } from './components/DashboardView';
import { BidsFeedView } from './components/BidsFeedView';
import { ProductsView } from './components/ProductsView';
import { BidDetailDrawer } from './components/BidDetailDrawer';
import { NotificationsDrawer } from './components/NotificationsDrawer';
import { NotificationsView } from './components/NotificationsView';
import { IngestionView } from './components/IngestionView';
import { ClosingSoonView } from './components/ClosingSoonView';
import { RecentIntelView } from './components/RecentIntelView';

async function readApiError(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data?.detail === 'string') return data.detail;
    if (Array.isArray(data?.detail) && data.detail.length > 0) {
      // FastAPI validation errors
      return data.detail
        .map((d: { loc?: string[]; msg?: string }) => `${d.loc?.slice(1).join('.') ?? ''} ${d.msg ?? ''}`.trim())
        .join('; ');
    }
    if (typeof data?.detail === 'object') return JSON.stringify(data.detail);
  } catch {
    /* response had no JSON body */
  }
  return fallback;
}

export default function App() {
  const [activeTab, setActiveTab] = useState<AppTab>('dashboard');

  // Visual Theme State (dark / light with localStorage persistence)
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    const saved = localStorage.getItem('securedapp_theme');
    return saved === 'light' || saved === 'dark' ? saved : 'dark';
  });

  // Global search owned by the shell, so the top bar can drive the Bids feed.
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('securedapp_theme', theme);
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));
  }, []);

  /** Typing in the top bar jumps to the Bids feed, which filters live on it. */
  const handleSearchChange = useCallback(
    (value: string) => {
      setSearchQuery(value);
      if (value.trim().length > 0 && activeTab !== 'bids') {
        setActiveTab('bids');
      }
    },
    [activeTab]
  );

  // Data States
  const [bids, setBids] = useState<BidIntelligenceRow[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);

  // Loading States
  const [loadingBids, setLoadingBids] = useState(false);
  const [loadingProducts, setLoadingProducts] = useState(false);
  const [loadingNotifications, setLoadingNotifications] = useState(false);
  const [loadingSummary, setLoadingSummary] = useState(true);

  // Inspector Drawer States
  const [selectedBid, setSelectedBid] = useState<Bid | null>(null);
  const [analysisData, setAnalysisData] = useState<AnalysisData | null>(null);
  const [bidReviews, setBidReviews] = useState<HumanReview[]>([]);
  const [loadingAnalysis, setLoadingAnalysis] = useState(false);

  // Monotonic token guarding the drawer's async loads: only the most recent
  // selection may write drawer state, so a slow response for an earlier bid can
  // never overwrite the drawer for a bid the user opened after it.
  const selectionTokenRef = useRef(0);

  // Notification Drawer State
  const [isNotifDrawerOpen, setIsNotifDrawerOpen] = useState(false);

  // Error Banner State
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [drawerError, setDrawerError] = useState<string | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);

  const fetchBids = useCallback(async () => {
    setLoadingBids(true);
    setGlobalError(null);
    try {
      const res = await fetch('/api/v1/bids/intelligence');
      if (res.ok) {
        const data = await res.json();
        setBids(data.bids ?? []);
      } else {
        setGlobalError(await readApiError(res, 'Failed to load bids from backend server.'));
      }
    } catch {
      setGlobalError('Unable to connect to backend API server. Verify backend is running.');
    } finally {
      setLoadingBids(false);
    }
  }, []);

  const fetchSummary = useCallback(async () => {
    setLoadingSummary(true);
    try {
      const res = await fetch('/api/v1/dashboard/summary');
      if (res.ok) {
        setSummary(await res.json());
      } else if (res.status === 404) {
        setSummary(null);
      } else {
        setGlobalError(await readApiError(res, 'Failed to load dashboard summary.'));
      }
    } catch {
      setGlobalError('Unable to reach the dashboard summary endpoint.');
    } finally {
      setLoadingSummary(false);
    }
  }, []);

  const fetchProducts = useCallback(async () => {
    setLoadingProducts(true);
    try {
      const res = await fetch('/api/v1/products');
      if (res.ok) {
        setProducts(await res.json());
      }
    } catch {
      setGlobalError('Unable to load the product catalogue.');
    } finally {
      setLoadingProducts(false);
    }
  }, []);

  const fetchNotifications = useCallback(async () => {
    setLoadingNotifications(true);
    try {
      const res = await fetch('/api/v1/notifications');
      if (res.ok) {
        setNotifications(await res.json());
      }
    } catch {
      /* notification drawer surfaces its own state */
    } finally {
      setLoadingNotifications(false);
    }
  }, []);

  useEffect(() => {
    fetchBids();
    fetchSummary();
    fetchProducts();
    fetchNotifications();
  }, [fetchBids, fetchSummary, fetchProducts, fetchNotifications]);

  // Keep the dashboard figures honest after any action that changes bid state.
  const refreshAll = useCallback(async () => {
    await Promise.all([fetchBids(), fetchSummary(), fetchNotifications()]);
  }, [fetchBids, fetchSummary, fetchNotifications]);

  const handleSelectBid = useCallback(
    async (bidId: string) => {
      const row = bids.find((b) => b.id === bidId);
      if (!row) return;
      const token = ++selectionTokenRef.current;

      setSelectedBid({
        id: row.id,
        gem_bid_id: row.gem_bid_id,
        bid_number: row.bid_number,
        title: row.title,
        organisation: row.organisation,
        department: row.department ?? null,
        ministry: null,
        category: row.category,
        bid_type: null,
        published_date: row.published_date,
        closing_date: row.closing_date,
        location: row.location,
        estimated_value: row.estimated_value,
        currency: row.currency,
        scope_of_work: row.scope_of_work,
        technical_requirements: null,
        eligibility_criteria: null,
        qualification_requirements: null,
        experience_requirements: null,
        certification_requirements: null,
        emd_information: null,
        tender_fee_information: null,
        contact_information: null,
        source_url: null,
        status: row.status,
        content_hash: null,
        first_discovered_at: row.last_updated_at ?? new Date().toISOString(),
        last_updated_at: row.last_updated_at ?? new Date().toISOString(),
      });
      setLoadingAnalysis(true);
      setAnalysisData(null);
      setBidReviews([]);
      setDrawerError(null);

      try {
        if (!row.analyzed) {
          setDrawerError(
            'This bid has not been analyzed yet. Opening it does not start analysis; use the "Run Analysis" action in the drawer.'
          );
        } else {
          // Rehydrate the drawer from the analysis the pipeline already stored.
          // The candidate list and scores come from persisted records, never
          // from a client-side guess or a fallback product name.
          const resAnalysis = await fetch(`/api/v1/bids/${bidId}/analysis`);
          if (token !== selectionTokenRef.current) return;
          if (resAnalysis.ok) {
            const payload = await resAnalysis.json();
            const stored = payload?.analysis;
            if (stored) {
              const storedScore = payload?.score;
              const loaded: AnalysisData = {
                bid_id: stored.bid_id ?? bidId,
                bid_title: stored.llm_output?.bid_title ?? row.title,
                intelligence: stored.llm_output ?? undefined,
                opportunity: storedScore?.score_breakdown?.opportunity_analysis ?? undefined,
                candidate_products: stored.product_matches ?? [],
              };
              setAnalysisData(loaded);
            } else {
              setDrawerError('No analysis record was found for this bid.');
            }
          } else {
            setDrawerError('Stored analysis details could not be loaded from the backend.');
          }
        }

        // source_url plus the persisted BoQ evidence are only served by the bid
        // detail endpoint, so both are patched into the drawer selection once
        // the detail arrives. `boq_items` is null when no BoQ was ever stored.
        const resDetail = await fetch(`/api/v1/bids/${bidId}`);
        if (token !== selectionTokenRef.current) return;
        if (resDetail.ok) {
          const detail = await resDetail.json();
          setSelectedBid((prev) =>
            prev && prev.id === bidId
              ? {
                  ...prev,
                  source_url: typeof detail?.source_url === 'string' ? detail.source_url : prev.source_url,
                  boq_items: detail?.boq_items ?? null,
                  boq_checked_at: detail?.boq_checked_at ?? null,
                }
              : prev
          );
        }

        const resReviews = await fetch(`/api/v1/bids/${bidId}/reviews`);
        if (token !== selectionTokenRef.current) return;
        if (resReviews.ok) {
          setBidReviews(await resReviews.json());
        }
      } catch {
        if (token === selectionTokenRef.current) {
          setDrawerError('Unable to load bid analysis details from the backend.');
        }
      } finally {
        if (token === selectionTokenRef.current) {
          setLoadingAnalysis(false);
        }
      }
    },
    [bids]
  );

  const handleRunAnalysis = useCallback(async () => {
    if (!selectedBid) return;
    setLoadingAnalysis(true);
    setDrawerError(null);
    try {
      const resAnalyze = await fetch(`/api/v1/bids/${selectedBid.id}/analyze`, { method: 'POST' });
      if (!resAnalyze.ok) {
        setDrawerError(await readApiError(resAnalyze, 'Analysis failed.'));
        return;
      }
      const data = await resAnalyze.json();

      const resMatch = await fetch(`/api/v1/bids/${selectedBid.id}/match-products`, { method: 'POST' });
      if (resMatch.ok) {
        const matchData = await resMatch.json();
        data.candidate_products = matchData.candidate_products;
      }
      setAnalysisData(data);
      await refreshAll();
    } catch {
      setDrawerError('Unable to reach the analysis endpoint.');
    } finally {
      setLoadingAnalysis(false);
    }
  }, [selectedBid, refreshAll]);

  const handleSubmitReview = useCallback(
    async (bidId: string, decision: 'RELEVANT' | 'NOT_RELEVANT' | 'MAYBE', comments: string) => {
      setReviewError(null);
      try {
        const res = await fetch(`/api/v1/bids/${bidId}/review`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            relevance_decision: decision,
            comments: comments.trim() || undefined,
          }),
        });

        if (res.ok) {
          const resReviews = await fetch(`/api/v1/bids/${bidId}/reviews`);
          if (resReviews.ok) {
            setBidReviews(await resReviews.json());
          }
          fetchNotifications();
          fetchSummary();
        } else {
          setReviewError(await readApiError(res, 'Failed to save review decision. Please try again.'));
        }
      } catch {
        setReviewError('Error connecting to backend API.');
      }
    },
    [fetchNotifications, fetchSummary]
  );

  // ---- Product management -------------------------------------------------

  const createProduct = useCallback(
    async (payload: { name: string; description: string | null }) => {
      const res = await fetch('/api/v1/products', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await readApiError(res, 'The product could not be created.'));
      await Promise.all([fetchProducts(), fetchSummary()]);
    },
    [fetchProducts, fetchSummary]
  );

  /**
   * Remove a product.
   *
   * Tries a permanent delete first. The backend refuses (409) when historical
   * bid analysis references the product, in which case we surface that and let
   * the operator fall back to deactivation, which is the safe behaviour: the
   * product stops participating in future matching but its knowledge and all
   * historical results stay intact.
   */
  const deleteProduct = useCallback(
    async (productId: string): Promise<{ blocked: boolean; message: string }> => {
      const res = await fetch(`/api/v1/products/${productId}?hard=true`, { method: 'DELETE' });

      if (res.ok) {
        await Promise.all([fetchProducts(), fetchSummary()]);
        return { blocked: false, message: '' };
      }

      if (res.status === 409) {
        // Historical analysis references this product. Deactivate instead of
        // risking the integrity of stored bid analysis records.
        const soft = await fetch(`/api/v1/products/${productId}`, { method: 'DELETE' });
        if (soft.ok) {
          await Promise.all([fetchProducts(), fetchSummary()]);
          return {
            blocked: true,
            message:
              'This product is referenced by historical bid analysis records, so it was deactivated instead of permanently deleted. It no longer participates in matching and its history is preserved.',
          };
        }
        return { blocked: true, message: await readApiError(soft, 'The product could not be removed.') };
      }

      return {
        blocked: true,
        message: await readApiError(res, 'The product could not be removed. Please try again.'),
      };
    },
    [fetchProducts, fetchSummary]
  );

  const reactivateProduct = useCallback(
    async (productId: string) => {
      const res = await fetch(`/api/v1/products/${productId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active: true }),
      });
      if (!res.ok) throw new Error(await readApiError(res, 'The product could not be reactivated.'));
      await Promise.all([fetchProducts(), fetchSummary()]);
    },
    [fetchProducts, fetchSummary]
  );

  const closingWindowDays = summary?.metrics.closing_soon_window_days ?? null;

  return (
    <div className="app-shell">
      <IconRail
        activeTab={activeTab}
        onNavigate={setActiveTab}
        notificationCount={notifications.length}
      />

      <div className="app-main">
        <TopBar
          search={searchQuery}
          onSearchChange={handleSearchChange}
          theme={theme}
          onToggleTheme={toggleTheme}
          onOpenNotifications={() => setIsNotifDrawerOpen(true)}
          notificationCount={notifications.length}
        />

        {globalError && (
          <div className="global-error-banner">
            <span>{globalError}</span>
            <button className="btn-secondary btn-sm" onClick={refreshAll}>
              Retry
            </button>
          </div>
        )}

        <main className="page-container">
          {activeTab === 'dashboard' && (
            <DashboardView
              summary={summary}
              summaryLoading={loadingSummary}
              onSelectBid={handleSelectBid}
              onNavigateTab={setActiveTab}
            />
          )}

          {activeTab === 'bids' && (
            <BidsFeedView
              bids={bids}
              products={products}
              loading={loadingBids}
              onSelectBid={handleSelectBid}
              onRefresh={fetchBids}
              search={searchQuery}
              onSearchChange={handleSearchChange}
            />
          )}

          {activeTab === 'closing-soon' && (
            <ClosingSoonView
              bids={bids}
              windowDays={closingWindowDays}
              loading={loadingBids || loadingSummary}
              onSelectBid={handleSelectBid}
            />
          )}

          {activeTab === 'recent' && (
            <RecentIntelView
              bids={bids}
              loading={loadingBids}
              onSelectBid={handleSelectBid}
              onNavigateBids={() => setActiveTab('bids')}
            />
          )}

          {activeTab === 'products' && (
            <ProductsView
              products={products}
              loading={loadingProducts}
              onCreate={createProduct}
              onDelete={deleteProduct}
              onReactivate={reactivateProduct}
            />
          )}

          {activeTab === 'ingestion' && <IngestionView onImportSuccess={refreshAll} />}

          {activeTab === 'notifications' && (
            <NotificationsView
              notifications={notifications}
              loading={loadingNotifications}
              onSelectBid={handleSelectBid}
            />
          )}
        </main>
      </div>

      {selectedBid && (
        <BidDetailDrawer
          bid={selectedBid}
          analysis={analysisData}
          reviews={bidReviews}
          loadingAnalysis={loadingAnalysis}
          onClose={() => setSelectedBid(null)}
          onSubmitReview={handleSubmitReview}
          onRunAnalysis={handleRunAnalysis}
          analysisError={drawerError}
          reviewError={reviewError}
        />
      )}

      {isNotifDrawerOpen && (
        <NotificationsDrawer
          notifications={notifications}
          loading={loadingNotifications}
          onClose={() => setIsNotifDrawerOpen(false)}
        />
      )}
    </div>
  );
}
