import React, {
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import {
  AnalysisData,
  AppTab,
  Bid,
  BidIntelligenceRow,
  DashboardSummary,
  HumanReview,
  NotificationItem,
  Product,
  UserRole,
} from './types';
import { api } from './lib/api';
import { ApiError } from './lib/api';
import { useAuth } from './context/AuthContext';
import { Login } from './components/Login';
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
import { StateTendersView } from './components/StateTendersView';
import { StateWiseBidsView } from './components/StateWiseBidsView';
import { AllIndiaMatchesView } from './components/AllIndiaMatchesView';
import { SourceMonitoringView } from './components/SourceMonitoringView';
import { AccessDenied } from './components/AccessDenied';
import { IconShieldCheck } from './components/icons';

/**
 * Read the error detail from a Response, falling back to a default message.
 */
async function readApiError(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data?.detail === 'string') return data.detail;
    if (Array.isArray(data?.detail) && data.detail.length > 0) {
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

/**
 * Inner application — rendered only when the user is authenticated.
 * Contains all the pre-existing views and data-fetching logic, now using the
 * auth-aware `api` utility so Bearer tokens and 401/403 handling are automatic.
 */
function InnerApp() {
  const {
    user,
    logout,
    refreshSession,
    canWriteProducts,
    canManageSources,
    canManageUsers,
    canRunMatching,
  } = useAuth();

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

  // Monotonic token guarding the drawer's async loads
  const selectionTokenRef = useRef(0);

  // Notification Drawer State
  const [isNotifDrawerOpen, setIsNotifDrawerOpen] = useState(false);

  // Error Banner State
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [drawerError, setDrawerError] = useState<string | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);

  // Access-denied state (403). When a backend call is rejected for
  // insufficient permissions the AccessDenied component is shown in place of
  // the current view. Frontend role gates reduce noise; backend authorization
  // remains the security boundary, so a 403 from the backend always wins.
  const [accessDenied, setAccessDenied] = useState<{
    requiredRole?: string;
  } | null>(null);

  const clearAccessDenied = useCallback(() => {
    setAccessDenied(null);
    setGlobalError(null);
  }, []);

  const fetchBids = useCallback(async () => {
    setLoadingBids(true);
    setGlobalError(null);
    try {
      const res = await api.get<{ bids?: BidIntelligenceRow[] }>('/api/v1/bids/intelligence');
      setBids(res.bids ?? []);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        await refreshSession();
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setAccessDenied({ requiredRole: 'VIEWER' });
        setGlobalError(null);
        return;
      }
      if (err instanceof ApiError && err.isNetworkError) {
        setGlobalError('Unable to connect to backend API server. Verify backend is running.');
      } else if (err instanceof Error) {
        setGlobalError(err.message);
      }
    } finally {
      setLoadingBids(false);
    }
  }, [refreshSession]);

  const fetchSummary = useCallback(async () => {
    setLoadingSummary(true);
    try {
      const res = await api.get<DashboardSummary>('/api/v1/dashboard/summary');
      setSummary(res);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        await refreshSession();
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setAccessDenied({ requiredRole: 'VIEWER' });
        setGlobalError(null);
        setLoadingSummary(false);
        return;
      }
      if (err instanceof ApiError && err.status === 404) {
        setSummary(null);
        setLoadingSummary(false);
        return;
      }
      if (err instanceof ApiError && err.isNetworkError) {
        setGlobalError('Unable to reach the dashboard summary endpoint.');
      } else if (err instanceof Error) {
        setGlobalError(err.message);
      }
    } finally {
      setLoadingSummary(false);
    }
  }, [refreshSession]);

  const fetchProducts = useCallback(async () => {
    setLoadingProducts(true);
    try {
      const data = await api.get<Product[]>('/api/v1/products');
      setProducts(data);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        await refreshSession();
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setAccessDenied({ requiredRole: 'VIEWER' });
        setGlobalError(null);
        return;
      }
      setGlobalError('Unable to load the product catalogue.');
    } finally {
      setLoadingProducts(false);
    }
  }, [refreshSession]);

  const fetchNotifications = useCallback(async () => {
    setLoadingNotifications(true);
    setGlobalError(null);
    try {
      const data = await api.get<NotificationItem[]>('/api/v1/notifications');
      setNotifications(data);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        await refreshSession();
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setAccessDenied({ requiredRole: 'VIEWER' });
        setGlobalError(null);
        return;
      }
      if (err instanceof ApiError && err.isNetworkError) {
        setGlobalError('Unable to reach the notifications endpoint.');
      } else if (err instanceof Error) {
        setGlobalError(err.message);
      }
    } finally {
      setLoadingNotifications(false);
    }
  }, [refreshSession]);

  useEffect(() => {
    fetchBids();
    fetchSummary();
    fetchProducts();
    fetchNotifications();
  }, [fetchBids, fetchSummary, fetchProducts, fetchNotifications]);

  const refreshAll = useCallback(async () => {
    await Promise.all([fetchBids(), fetchSummary(), fetchProducts(), fetchNotifications()]);
  }, [fetchBids, fetchSummary, fetchProducts, fetchNotifications]);

  const handleSelectBid = useCallback(
    async (bidId: string) => {
      // The intelligence feed only carries open bids, but All-India matches can
      // surface closed bids too. Fall back to the per-bid detail endpoint (any
      // bid, open or closed) so "Inspect" still opens the bid-detail drawer.
      let row = bids.find((b) => b.id === bidId);
      if (!row) {
        try {
          const detail = await api.get<any>(`/api/v1/bids/${bidId}`);
          row = {
            id: detail.id,
            gem_bid_id: detail.gem_bid_id,
            bid_number: detail.bid_number,
            title: detail.title,
            organisation: detail.organisation,
            department: detail.department ?? null,
            category: detail.category ?? null,
            published_date: detail.published_date,
            closing_date: detail.closing_date,
            location: detail.location,
            estimated_value: detail.estimated_value,
            currency: detail.currency,
            scope_of_work: detail.scope_of_work,
            status: detail.status,
            last_updated_at: detail.last_updated_at,
            analyzed: false,
          } as any;
        } catch {
          setGlobalError('Unable to load bid details.');
          return;
        }
      }
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
        source_url: typeof row.source_url === 'string' ? row.source_url : null,
        original_bid_url: typeof row.original_bid_url === 'string' ? row.original_bid_url : null,
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
            'This bid has not been analyzed yet. Opening it does not start analysis; use the "Run Analysis" action in the drawer.',
          );
        } else {
          try {
            const payload = await api.get<any>(`/api/v1/bids/${bidId}/analysis`);
            if (token !== selectionTokenRef.current) return;
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
          } catch {
            setDrawerError('Stored analysis details could not be loaded from the backend.');
          }
        }

        try {
          const detail = await api.get<any>(`/api/v1/bids/${bidId}`);
          if (token !== selectionTokenRef.current) return;
          setSelectedBid((prev) =>
            prev && prev.id === bidId
              ? {
                  ...prev,
                  source_url: typeof detail?.source_url === 'string' ? detail.source_url : prev.source_url,
                  original_bid_url: typeof detail?.original_bid_url === 'string' ? detail.original_bid_url : prev.original_bid_url,
                  boq_items: detail?.boq_items ?? null,
                  boq_checked_at: detail?.boq_checked_at ?? null,
                }
              : prev
          );
        } catch {
          /* detail fetch failed — non-fatal */
        }

        try {
          const reviews = await api.get<HumanReview[]>(`/api/v1/bids/${bidId}/reviews`);
          if (token !== selectionTokenRef.current) return;
          setBidReviews(reviews);
        } catch {
          /* reviews fetch failed — non-fatal */
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
    if (!canRunMatching()) {
      setDrawerError('Running analysis requires Operator or Admin role.');
      return;
    }
    setLoadingAnalysis(true);
    setDrawerError(null);
    try {
      await api.post(`/api/v1/bids/${selectedBid.id}/analyze`);
      const matchData = await api.post<{ candidate_products: any[] }>(`/api/v1/bids/${selectedBid.id}/match-products`);
      setAnalysisData((prev) =>
        prev ? { ...prev, candidate_products: matchData.candidate_products } : prev
      );
      await refreshAll();
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setDrawerError('Insufficient permissions to run analysis.');
      } else {
        setDrawerError('Unable to reach the analysis endpoint.');
      }
    } finally {
      setLoadingAnalysis(false);
    }
  }, [selectedBid, canRunMatching, refreshAll]);

  const handleSubmitReview = useCallback(
    async (bidId: string, decision: 'RELEVANT' | 'NOT_RELEVANT' | 'MAYBE', comments: string) => {
      setReviewError(null);
      try {
        await api.post(`/api/v1/bids/${bidId}/review`, {
          relevance_decision: decision,
          comments: comments.trim() || undefined,
        });
        const reviews = await api.get<HumanReview[]>(`/api/v1/bids/${bidId}/reviews`);
        setBidReviews(reviews);
        fetchNotifications();
        fetchSummary();
      } catch (err) {
        if (err instanceof ApiError && err.status === 403) {
          setReviewError('Insufficient permissions to submit a review.');
        } else {
          setReviewError('Error connecting to backend API.');
        }
      }
    },
    [fetchNotifications, fetchSummary]
  );

  // ---- Product management -------------------------------------------------

  const createProduct = useCallback(
    async (payload: { name: string; description: string | null }) => {
      if (!canWriteProducts()) {
        throw new Error('Creating products requires Operator or Admin role.');
      }
      await api.post('/api/v1/products', payload);
      await Promise.all([fetchProducts(), fetchSummary()]);
    },
    [fetchProducts, fetchSummary, canWriteProducts]
  );

  const addKeyword = useCallback(
    async (productId: string, payload: { keyword: string; weight?: number; type?: string; active?: boolean }) => {
      if (!canWriteProducts()) {
        throw new Error('Adding keywords requires Operator or Admin role.');
      }
      await api.post(`/api/v1/products/${productId}/keywords`, payload);
      await fetchProducts();
    },
    [fetchProducts, canWriteProducts]
  );

  const updateKeyword = useCallback(
    async (
      productId: string,
      keywordId: string,
      payload: { keyword: string; weight?: number; type?: string; active?: boolean },
    ) => {
      if (!canWriteProducts()) {
        throw new Error('Updating keywords requires Operator or Admin role.');
      }
      await api.put(`/api/v1/products/${productId}/keywords/${keywordId}`, payload);
      await fetchProducts();
    },
    [fetchProducts, canWriteProducts]
  );

  const deleteKeyword = useCallback(
    async (productId: string, keywordId: string) => {
      if (!canWriteProducts()) {
        throw new Error('Deleting keywords requires Operator or Admin role.');
      }
      await api.delete(`/api/v1/products/${productId}/keywords/${keywordId}`);
      await fetchProducts();
    },
    [fetchProducts, canWriteProducts]
  );

  const deleteProduct = useCallback(
    async (productId: string): Promise<{ blocked: boolean; message: string }> => {
      if (!canWriteProducts()) {
        throw new Error('Deleting products requires Operator or Admin role.');
      }
      const res = await fetch(`/api/v1/products/${productId}?hard=true`, { method: 'DELETE' });

      if (res.ok) {
        await Promise.all([fetchProducts(), fetchSummary()]);
        return { blocked: false, message: '' };
      }

      if (res.status === 409) {
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
    [fetchProducts, fetchSummary, canWriteProducts]
  );

  const reactivateProduct = useCallback(
    async (productId: string) => {
      if (!canWriteProducts()) {
        throw new Error('Reactivating products requires Operator or Admin role.');
      }
      await api.put(`/api/v1/products/${productId}`, { active: true });
      await Promise.all([fetchProducts(), fetchSummary()]);
    },
    [fetchProducts, fetchSummary, canWriteProducts]
  );

  const handleSyncSource = useCallback(
    async (sourceId: string) => {
      if (!canManageSources()) {
        throw new Error('Source sync requires Operator or Admin role.');
      }
      const res = await fetch(`/api/v1/sources/${sourceId}/sync`, {
        method: 'POST',
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Source sync failed.');
      }
      await res.json();
      await Promise.all([fetchBids(), fetchSummary()]);
    },
    [fetchBids, fetchSummary, canManageSources]
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
          user={user}
          onLogout={logout}
        />

        {globalError && !accessDenied && (
          <div className="global-error-banner">
            <span>{globalError}</span>
            <button className="btn-secondary btn-sm" onClick={refreshAll}>
              Retry
            </button>
          </div>
        )}

        {accessDenied ? (
          <div
            className="page-container"
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: '55vh',
              padding: 0,
            }}
          >
            <AccessDenied requiredRole={accessDenied.requiredRole} onBack={clearAccessDenied} />
          </div>
        ) : (
          <main className="page-container">
            {activeTab === 'dashboard' && (
              <DashboardView
              summary={summary}
              summaryLoading={loadingSummary}
              onSelectBid={handleSelectBid}
              onNavigateTab={setActiveTab}
              canRunMatching={canRunMatching}
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
              onAddKeyword={addKeyword}
              onUpdateKeyword={updateKeyword}
              onDeleteKeyword={deleteKeyword}
              canWriteProducts={canWriteProducts}
            />
          )}

          {activeTab === 'ingestion' && <IngestionView onImportSuccess={refreshAll} />}

          {activeTab === 'state-tenders' && (
            <StateTendersView onSyncSource={handleSyncSource} />
          )}

          {activeTab === 'state-wise-bids' && (
            <StateWiseBidsView onSelectBid={handleSelectBid} />
          )}

          {activeTab === 'notifications' && (
            <NotificationsView
              notifications={notifications}
              loading={loadingNotifications}
              onSelectBid={handleSelectBid}
            />
          )}

          {activeTab === 'all-india-matches' && (
            <AllIndiaMatchesView
              onSelectBid={handleSelectBid}
            />
          )}

          {activeTab === 'scraper-monitoring' && (
            <SourceMonitoringView
              canManageSources={canManageSources}
            />
          )}
          </main>
        )}
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
          canWriteProducts={canWriteProducts}
          canManageUsers={canManageUsers}
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

/**
 * Root app — handles the authentication gate.
 *   - While isLoading: show a session-restore spinner.
 *   - When unauthenticated: show the Login page.
 *   - When authenticated: render InnerApp.
 */
export default function App() {
  const { user, isAuthenticated, isLoading, login, logout } = useAuth();

  // If session is still being restored, show a neutral loading state.
  if (isLoading) {
    return (
      <div className="login-page">
        <div className="login-card">
          <div className="login-header">
            <div className="login-logo">
              <IconShieldCheck size={32} />
            </div>
            <h1 className="login-title">SecuredApp</h1>
            <p className="login-subtitle">Restoring session…</p>
          </div>
        </div>
      </div>
    );
  }

  // Not authenticated → show login page.
  //
  // Login is self-contained: it renders its own shield/logo, heading,
  // subtitle, card, fields and buttons. Rendering it directly (without an
  // outer login-page/login-card/header here) avoids the duplicated branding
  // that previously appeared twice on the login screen.
  if (!isAuthenticated) {
    return <Login onSuccess={() => {}} />;
  }

  // Authenticated → render the full app.
  return <InnerApp />;
}
