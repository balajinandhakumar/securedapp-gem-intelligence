import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Product,
  ProductCapability,
  ProductKeyword,
  ProductKeywordPayload,
  ProductMatchingStats,
  ProductCatalogueSummary,
} from '../types';
import { api } from '../lib/api';
import { KpiTile } from './KpiTile';
import { EmptyState } from './EmptyState';
import { IconListSearch, IconShieldCheck, IconTarget, IconMapPin, IconBox, IconArrowRight, IconClockAlert } from './icons';

interface ProductsViewProps {
  products: Product[];
  loading: boolean;
  onCreate: (payload: { name: string; description: string | null }) => Promise<void>;
  onDelete: (productId: string) => Promise<{ blocked: boolean; message: string }>;
  onReactivate: (productId: string) => Promise<void>;
  onAddKeyword: (productId: string, payload: ProductKeywordPayload) => Promise<void>;
  onUpdateKeyword: (productId: string, keywordId: string, payload: ProductKeywordPayload) => Promise<void>;
  onDeleteKeyword: (productId: string, keywordId: string) => Promise<void>;
  canWriteProducts: () => boolean;
}

/**
 * SecuredApp Product Catalogue — redesigned enterprise product portfolio page.
 *
 * Displays all 11 SecuredApp products in a modern card grid with:
 *   - KPI header strip (total products, active, categories, matching tenders)
 *   - Search by name, capability, or keyword
 *   - Category filter and sort options
 *   - Matching tender counts and highest relevance score per product
 *   - Product detail drawer with full knowledge vectors and matching tenders
 *
 * All product data comes from the backend /api/v1/products endpoint.
 * Matching stats come from /api/v1/products/catalogue-stats (persisted
 * bid-product matches — nothing is estimated or fabricated).
 */
export const ProductsView: React.FC<ProductsViewProps> = ({
  products,
  loading,
  onCreate,
  onDelete,
  onReactivate,
  onAddKeyword,
  onUpdateKeyword,
  onDeleteKeyword,
  canWriteProducts,
}) => {
  const [catalogueStats, setCatalogueStats] = useState<ProductCatalogueSummary | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsError, setStatsError] = useState<string | null>(null);

  // UI state
  const [search, setSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('ALL');
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'inactive'>('all');
  const [sortBy, setSortBy] = useState<'name' | 'matches' | 'score'>('name');
  const [showAdd, setShowAdd] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Product | null>(null);
  const [keywordTarget, setKeywordTarget] = useState<Product | null>(null);
  const [detailTarget, setDetailTarget] = useState<Product | null>(null);
  const [editKeyword, setEditKeyword] = useState<ProductKeyword | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [kwBusy, setKwBusy] = useState<Record<string, boolean>>({});

  // Load catalogue matching stats
  const loadCatalogueStats = useCallback(async () => {
    setStatsLoading(true);
    setStatsError(null);
    try {
      const res = await api.get<ProductCatalogueSummary>('/api/v1/products/catalogue-stats');
      setCatalogueStats(res);
    } catch {
      setStatsError('Unable to reach the catalogue statistics endpoint.');
    } finally {
      setStatsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCatalogueStats();
  }, [loadCatalogueStats]);

  // Keep the detail drawer in sync with refetched product data (e.g. after keyword add/remove)
  // so newly added or removed keywords are visible without reopening the drawer.
  useEffect(() => {
    if (detailTarget) {
      const updated = products.find((p) => p.id === detailTarget.id);
      if (updated && updated !== detailTarget) {
        setDetailTarget(updated);
      }
    }
  }, [products]);

  // Build category options from product data
  const categoryOptions = useMemo(() => {
    const cats = new Set<string>();
    products.forEach((p) => p.categories.forEach((c) => cats.add(c.category)));
    return Array.from(cats).sort();
  }, [products]);

  // Build stats lookup by product id
  const statsByProduct = useMemo(() => {
    const map = new Map<string, ProductMatchingStats>();
    catalogueStats?.product_stats.forEach((s) => map.set(s.product_id, s));
    return map;
  }, [catalogueStats]);

  // Filtered and sorted products
  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return products
      .filter((p) => {
        if (statusFilter === 'active' && !p.active) return false;
        if (statusFilter === 'inactive' && p.active) return false;
        if (categoryFilter !== 'ALL' && !p.categories.some((c) => c.category === categoryFilter)) return false;
        if (!term) return true;
        return (
          p.name.toLowerCase().includes(term) ||
          (p.description ?? '').toLowerCase().includes(term) ||
          p.capabilities.some((cap) => cap.name.toLowerCase().includes(term)) ||
          p.keywords.some((k) => k.keyword.toLowerCase().includes(term))
        );
      })
      .sort((a, b) => {
        if (sortBy === 'name') return a.name.localeCompare(b.name);
        const aStats = statsByProduct.get(a.id);
        const bStats = statsByProduct.get(b.id);
        if (sortBy === 'matches') {
          return (bStats?.matching_tenders ?? 0) - (aStats?.matching_tenders ?? 0);
        }
        // sortBy === 'score'
        return (bStats?.highest_relevance_score ?? 0) - (aStats?.highest_relevance_score ?? 0);
      });
  }, [products, search, statusFilter, categoryFilter, sortBy, statsByProduct]);

  const activeCount = products.filter((p) => p.active).length;
  const inactiveCount = products.length - activeCount;

  const handleCreate = async (name: string, description: string) => {
    setBusy(true);
    setPageError(null);
    try {
      await onCreate({ name, description: description || null });
      setShowAdd(false);
      await loadCatalogueStats();
    } catch (err) {
      setPageError(err instanceof Error ? err.message : 'The product could not be saved.');
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setBusy(true);
    setDeleteError(null);
    try {
      const result = await onDelete(deleteTarget.id);
      if (result.blocked) { setDeleteError(result.message); return; }
      setDeleteTarget(null);
      await loadCatalogueStats();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : 'The product could not be removed.');
    } finally {
      setBusy(false);
    }
  };

  const handleReactivate = async () => {
    if (!deleteTarget) return;
    setBusy(true);
    setDeleteError(null);
    try {
      await onReactivate(deleteTarget.id);
      setDeleteTarget(null);
      await loadCatalogueStats();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : 'The product could not be reactivated.');
    } finally {
      setBusy(false);
    }
  };

  const handleAddKeyword = async (payload: ProductKeywordPayload) => {
    if (!keywordTarget) return;
    const target = keywordTarget;
    setKwBusy((prev) => ({ ...prev, [target.id]: true }));
    try {
      await onAddKeyword(target.id, payload);
      setKeywordTarget(null);
      setEditKeyword(null);
      await loadCatalogueStats();
    } catch (err) {
      setPageError(err instanceof Error ? err.message : 'Keyword could not be added.');
      throw err;
    } finally {
      setKwBusy((prev) => ({ ...prev, [target.id]: false }));
    }
  };

  const handleUpdateKeyword = async (kw: ProductKeyword) => {
    if (!keywordTarget) return;
    const target = keywordTarget;
    setKwBusy((prev) => ({ ...prev, [target.id]: true }));
    try {
      await onUpdateKeyword(target.id, kw.id, {
        keyword: kw.keyword,
        weight: kw.weight,
        type: kw.type,
        active: kw.active,
      });
      setEditKeyword(null);
      await loadCatalogueStats();
    } catch (err) {
      setPageError(err instanceof Error ? err.message : 'Keyword could not be updated.');
      throw err;
    } finally {
      setKwBusy((prev) => ({ ...prev, [target.id]: false }));
    }
  };

  const handleDeleteKeyword = async (keywordId: string) => {
    if (!keywordTarget) return;
    const target = keywordTarget;
    setKwBusy((prev) => ({ ...prev, [target.id]: true }));
    try {
      await onDeleteKeyword(target.id, keywordId);
      // Update detailTarget immediately so the drawer reflects the removal.
      setDetailTarget((prev) => {
        if (!prev || prev.id !== target.id) return prev;
        return {
          ...prev,
          keywords: prev.keywords.filter((k) => k.id !== keywordId),
        };
      });
      await loadCatalogueStats();
    } catch (err) {
      setPageError(err instanceof Error ? err.message : 'Keyword could not be deleted.');
      throw err;
    } finally {
      setKwBusy((prev) => ({ ...prev, [target.id]: false }));
    }
  };

  const handleRemoveKeywordDirect = async (product: Product, kw: ProductKeyword) => {
    if (!window.confirm(`Remove keyword "${kw.keyword}" from "${product.name}"?`)) return;
    setKwBusy((prev) => ({ ...prev, [product.id]: true }));
    try {
      await onDeleteKeyword(product.id, kw.id);
      // Update detailTarget immediately so the drawer reflects the removal.
      setDetailTarget((prev) => {
        if (!prev || prev.id !== product.id) return prev;
        return {
          ...prev,
          keywords: prev.keywords.filter((k) => k.id !== kw.id),
        };
      });
      await loadCatalogueStats();
    } catch (err) {
      setPageError(err instanceof Error ? err.message : 'Keyword could not be removed.');
      throw err;
    } finally {
      setKwBusy((prev) => ({ ...prev, [product.id]: false }));
    }
  };

  // Wrapped delete keyword used by the detail drawer so detailTarget is
  // refreshed immediately after a successful removal, without waiting for the
  // async products refetch + sync effect chain.
  const handleDrawerDeleteKeyword = useCallback(
    async (productId: string, keywordId: string) => {
      await onDeleteKeyword(productId, keywordId);
      setDetailTarget((prev) => {
        if (!prev || prev.id !== productId) return prev;
        return {
          ...prev,
          keywords: prev.keywords.filter((k) => k.id !== keywordId),
        };
      });
      await loadCatalogueStats();
    },
    [onDeleteKeyword, loadCatalogueStats]
  );

  // ── Classification badge ──
  const classificationBadge = (cls: string | null | undefined): string => {
    switch (cls) {
      case 'MATCH': return 'badge badge-match';
      case 'POSSIBLE_MATCH': return 'badge badge-possible';
      case 'NEEDS_REVIEW': return 'badge badge-review';
      case 'NO_MATCH': return 'badge badge-no_match';
      default: return 'badge badge-unknown';
    }
  };

  // ── KPI strip ──
  const kpis = [
    {
      label: 'Total products',
      value: catalogueStats?.total_products ?? products.length,
      sub: 'SecuredApp security portfolio',
      icon: <IconBox />,
      iconTone: 'accent',
      valueTone: 'positive',
    },
    {
      label: 'Active',
      value: catalogueStats?.active_products ?? activeCount,
      sub: 'Participating in bid matching',
      icon: <IconShieldCheck />,
      iconTone: 'positive',
      valueTone: 'positive',
    },
    {
      label: 'Categories',
      value: catalogueStats?.total_categories ?? categoryOptions.length,
      sub: 'Product capability areas',
      icon: <IconListSearch />,
      iconTone: 'neutral',
      valueTone: 'neutral',
    },
    {
      label: 'Products with matches',
      value: catalogueStats?.products_with_matches ?? 0,
      sub: 'of total catalogue',
      icon: <IconTarget />,
      iconTone: 'accent',
      valueTone: 'accent',
    },
    {
      label: 'Matching tenders',
      value: catalogueStats?.total_matching_tenders ?? 0,
      sub: 'Tenders with ≥ 1 product match',
      icon: <IconMapPin />,
      iconTone: 'warning',
      valueTone: 'warning',
    },
  ];

  // ── Loading state ──
  if (loading || (statsLoading && catalogueStats === null)) {
    return (
      <div className="card-panel">
        <div className="panel-header">
          <h2 className="panel-title">SecuredApp Product Catalogue</h2>
          <p className="panel-subtitle">
            Explore the complete SecuredApp security and technology product portfolio.
          </p>
        </div>
        <div className="metrics-row" style={{ marginTop: '1rem' }}>
          {['Products', 'Categories', 'Active', 'Matching Tenders'].map((label) => (
            <div className="kpi-tile" key={label}>
              <div className="kpi-top">
                <div className="kpi-icon" />
                <span className="kpi-label">{label}</span>
              </div>
              <div className="skeleton" style={{ height: '26px', width: '55%' }} />
              <div className="kpi-sub skeleton" style={{ height: '10px', width: '80%' }} />
            </div>
          ))}
        </div>
        <div className="empty-state" style={{ marginTop: '1rem' }}>
          <div className="empty-title">Loading product catalogue…</div>
        </div>
      </div>
    );
  }

  // ── Error state ──
  if (pageError || statsError) {
    return (
      <div className="card-panel">
        <div className="panel-header">
          <h2 className="panel-title">SecuredApp Product Catalogue</h2>
        </div>
        <div className="alert-error">{pageError || statsError}</div>
        <div style={{ marginTop: '0.6rem' }}>
          <button className="btn-secondary btn-sm" onClick={loadCatalogueStats}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  // ── Empty state ──
  if (products.length === 0) {
    return (
      <div className="card-panel">
        <div className="panel-header">
          <h2 className="panel-title">SecuredApp Product Catalogue</h2>
          <p className="panel-subtitle">
            Explore the complete SecuredApp security and technology product portfolio.
          </p>
        </div>
        <div className="empty-state">
          <div className="empty-title">No products configured</div>
          <div className="empty-desc">
            Add a product to give the matching engine something to evaluate bids against.
          </div>
          {canWriteProducts() && (
            <button className="btn-primary btn-sm" onClick={() => setShowAdd(true)} style={{ marginTop: '0.25rem' }}>
              Add Product
            </button>
          )}
          {!canWriteProducts() && (
            <div className="empty-desc" style={{ marginTop: '0.25rem', color: 'var(--text-muted)' }}>
              Product creation requires Operator or Admin role.
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Empty filtered state ──
  if (filtered.length === 0) {
    return (
      <div className="card-panel">
        <div className="panel-header">
          <h2 className="panel-title">SecuredApp Product Catalogue</h2>
          <p className="panel-subtitle">
            Explore the complete SecuredApp security and technology product portfolio.
          </p>
        </div>
        <div className="empty-state">
          <div className="empty-title">No products match your filters</div>
          <div className="empty-desc">Try a different search term, category, or status filter.</div>
        </div>
      </div>
    );
  }

  // ── Main catalogue ──
  return (
    <div className="card-panel">
      {/* Header */}
      <div className="panel-header" style={{ marginBottom: '0.75rem' }}>
        <div>
          <h2 className="panel-title">SecuredApp Product Catalogue</h2>
          <p className="panel-subtitle">
            Explore the complete SecuredApp security and technology product portfolio.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.48rem', alignItems: 'center' }}>
          {canWriteProducts() && (
            <button
              className="btn-primary btn-sm"
              onClick={() => setShowAdd(true)}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
              </svg>
              Add Product
            </button>
          )}
          {!canWriteProducts() && (
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
              Product creation requires Operator or Admin role.
            </span>
          )}
        </div>
      </div>

      {/* KPI strip */}
      <div className="metrics-row" style={{ marginBottom: '1rem' }}>
        {kpis.map((k, i) => (
          <KpiTile
            key={i}
            label={k.label}
            value={k.value}
            icon={k.icon}
            iconTone={k.iconTone as 'positive' | 'warning' | 'accent' | 'danger' | 'neutral'}
            valueTone={k.valueTone as 'positive' | 'warning' | 'accent' | 'danger' | 'neutral' | 'muted'}
            sub={k.sub}
            highlight={i === 0}
          />
        ))}
      </div>

      {/* Toolbar: search, filters, sort */}
      <div className="toolbar-container" style={{ marginBottom: '1rem' }}>
        <div className="search-input-wrapper" style={{ flex: 1, maxWidth: '420px' }}>
          <svg className="search-icon-inside" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            className="search-input"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search product name, capability, or keyword…"
            aria-label="Search products"
          />
        </div>

        <select
          className="filter-select"
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          aria-label="Filter by category"
        >
          <option value="ALL">All Categories</option>
          {categoryOptions.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>

        <select
          className="filter-select"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as 'all' | 'active' | 'inactive')}
          aria-label="Filter by status"
        >
          <option value="all">All ({products.length})</option>
          <option value="active">Active ({activeCount})</option>
          <option value="inactive">Inactive ({inactiveCount})</option>
        </select>

        <select
          className="filter-select"
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as 'name' | 'matches' | 'score')}
          aria-label="Sort by"
        >
          <option value="name">Sort by Name (A–Z)</option>
          <option value="matches">Sort by Matching Tenders (▼)</option>
          <option value="score">Sort by Highest Score (▼)</option>
        </select>
      </div>

      {/* Product card grid */}
      <div className="product-grid">
        {filtered.map((product) => {
          const stats = statsByProduct.get(product.id);
          const matchCount = stats?.matching_tenders ?? 0;
          const bestScore = stats?.highest_relevance_score;
          const bestClass = stats?.highest_classification;

          return (
            <div
              key={product.id}
              className={`product-card${product.active ? '' : ' product-card-inactive'}`}
              onClick={() => setDetailTarget(product)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && setDetailTarget(product)}
            >
              <div className="product-card-head">
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <h3 className="product-card-name">{product.name}</h3>
                  <span className={product.active ? 'badge badge-confirmed' : 'badge badge-inactive'}>
                    {product.active ? 'Active' : 'Inactive'}
                  </span>
                </div>
                {bestScore !== null && (
                  <span className={`badge ${classificationBadge(bestClass)}`}>
                    {bestClass ? bestClass.replace(/_/g, ' ').toLowerCase() : '—'}
                  </span>
                )}
              </div>

              <p className="product-card-desc">
                {product.description || (
                  <span className="unanalysed-note">No description added</span>
                )}
              </p>

              {/* Keywords */}
              <div className="product-card-keywords" style={{ marginBottom: '0.6rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
                  <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600 }}>
                    Keywords ({product.keywords.length})
                  </span>
                  {canWriteProducts() && (
                    <button
                      type="button"
                      className="btn-secondary btn-xs"
                      onClick={(e) => {
                        e.stopPropagation();
                        setKeywordTarget(product);
                      }}
                      title={`Add keyword to ${product.name}`}
                      style={{ fontSize: '0.68rem', padding: '0.15rem 0.45rem' }}
                    >
                      + Add Keyword
                    </button>
                  )}
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
                  {[...product.keywords].reverse().slice(0, 6).map((kw) => (
                    <span
                      key={kw.id}
                      className={`badge ${kw.type === 'exclusion' ? 'badge-no_match' : kw.type === 'positive_signal' ? 'badge-match' : 'badge-keyword'}`}
                      style={{ fontSize: '0.7rem', padding: '0.2rem 0.45rem', display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}
                      title={`${kw.keyword} (w=${kw.weight ?? 1})`}
                    >
                      <span>{kw.keyword}</span>
                      {canWriteProducts() && (
                        <button
                          type="button"
                          className="kw-remove-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleRemoveKeywordDirect(product, kw);
                          }}
                          aria-label={`Remove keyword ${kw.keyword}`}
                          title={`Remove keyword "${kw.keyword}"`}
                          style={{
                            background: 'transparent',
                            border: 'none',
                            color: 'inherit',
                            cursor: 'pointer',
                            padding: '0 0.15rem',
                            fontWeight: 700,
                            lineHeight: 1,
                            opacity: 0.7,
                          }}
                        >
                          ×
                        </button>
                      )}
                    </span>
                  ))}
                  {product.keywords.length > 6 && (
                    <span
                      className="badge badge-unknown"
                      style={{ fontSize: '0.7rem', padding: '0.2rem 0.45rem', cursor: 'pointer' }}
                      onClick={(e) => {
                        e.stopPropagation();
                        setDetailTarget(product);
                      }}
                      title="View all keywords in details"
                    >
                      +{product.keywords.length - 6} more
                    </span>
                  )}
                  {product.keywords.length === 0 && (
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)', fontStyle: 'italic' }}>
                      No keywords configured
                    </span>
                  )}
                </div>
              </div>

              {/* Capabilities */}
              {product.capabilities.length > 0 && (
                <div className="product-capabilities" style={{ marginBottom: '0.6rem' }}>
                  <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600 }}>
                    Capabilities
                  </span>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginTop: '0.35rem' }}>
                    {product.capabilities.slice(0, 4).map((cap) => (
                      <span
                        key={cap.id}
                        className="badge badge-product"
                        style={{ fontSize: '0.7rem', padding: '0.2rem 0.5rem' }}
                        title={cap.name}
                      >
                        {cap.name}
                      </span>
                    ))}
                    {product.capabilities.length > 4 && (
                      <span className="badge badge-unknown" style={{ fontSize: '0.7rem', padding: '0.2rem 0.5rem' }}>
                        +{product.capabilities.length - 4} more
                      </span>
                    )}
                  </div>
                </div>
              )}

              {/* Matching stats */}
              <div className="product-card-foot" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.15rem' }}>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                    Matching Tenders
                  </span>
                  <span style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-main)' }}>
                    {matchCount}
                  </span>
                </div>

                {bestScore !== null && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.15rem' }}>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                      Highest Score
                    </span>
                    <span style={{ fontSize: '1.1rem', fontWeight: 700, color: bestScore >= 0.7 ? 'var(--accent-green)' : bestScore >= 0.45 ? 'var(--accent-cyan)' : bestScore >= 0.25 ? 'var(--accent-amber)' : 'var(--text-muted)' }}>
                      {(bestScore * 100).toFixed(0)}%
                    </span>
                  </div>
                )}

                <button
                  className="btn-secondary btn-sm"
                  onClick={(e) => { e.stopPropagation(); setDetailTarget(product); }}
                  title="View details"
                >
                  <IconArrowRight size={13} />
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Product detail drawer */}
      {detailTarget && (
        <ProductDetailDrawer
          product={detailTarget}
          stats={statsByProduct.get(detailTarget.id) ?? null}
          onClose={() => setDetailTarget(null)}
          onDeleteKeyword={handleDrawerDeleteKeyword}
          onAddKeyword={() => setKeywordTarget(detailTarget)}
          canWriteProducts={canWriteProducts}
        />
      )}

      {showAdd && (
        <AddProductDialog
          submitting={busy}
          onCancel={() => setShowAdd(false)}
          onSubmit={handleCreate}
        />
      )}

      {deleteTarget && (
        <DeleteDialog
          product={deleteTarget}
          busy={busy}
          serverError={deleteError}
          canReactivate={deleteTarget.active}
          onConfirm={handleDelete}
          onReactivate={handleReactivate}
          onCancel={() => { setDeleteTarget(null); setDeleteError(null); }}
        />
      )}

      {keywordTarget && (
        <KeywordDialog
          product={keywordTarget}
          submitting={kwBusy[keywordTarget.id] || false}
          onCancel={() => { setKeywordTarget(null); setEditKeyword(null); }}
          onAdd={handleAddKeyword}
          onUpdate={async (keywordId, payload) => {
            const kw = keywordTarget?.keywords.find((k) => k.id === keywordId);
            if (kw) {
              await handleUpdateKeyword({ ...kw, ...payload });
            }
          }}
          onDelete={handleDeleteKeyword}
          initialEditKeyword={editKeyword}
        />
      )}
    </div>
  );
};

// ── Product Detail Drawer ──

interface ProductDetailDrawerProps {
  product: Product;
  stats: ProductMatchingStats | null;
  onClose: () => void;
  onDeleteKeyword?: (productId: string, keywordId: string) => Promise<void>;
  onAddKeyword?: () => void;
  canWriteProducts?: () => boolean;
}

function ProductDetailDrawer({ product, stats, onClose, onDeleteKeyword, onAddKeyword, canWriteProducts }: ProductDetailDrawerProps) {
  const [tab, setTab] = useState<'overview' | 'matches'>('overview');
  const [deletingKeywordId, setDeletingKeywordId] = useState<string | null>(null);
  const [keywordDeleteError, setKeywordDeleteError] = useState<string | null>(null);

  const topKeywords = useMemo(() => {
    return [...product.keywords]
      .sort((a, b) => (b.weight ?? 1) - (a.weight ?? 1));
  }, [product.keywords]);

  const canWrite = canWriteProducts ? canWriteProducts() : false;

  const handleRemoveKeyword = async (keywordId: string) => {
    const kw = product.keywords.find((k) => k.id === keywordId);
    if (!kw) return;
    if (!window.confirm(`Remove keyword "${kw.keyword}" from "${product.name}"?`)) return;
    setDeletingKeywordId(keywordId);
    setKeywordDeleteError(null);
    try {
      if (!onDeleteKeyword) {
        setKeywordDeleteError('Keyword removal is not available.');
        return;
      }
      await onDeleteKeyword(product.id, keywordId);
      setDeletingKeywordId(null);
    } catch (err) {
      setDeletingKeywordId(null);
      setKeywordDeleteError(err instanceof Error ? err.message : 'Keyword could not be removed.');
    }
  };

  const clearError = () => setKeywordDeleteError(null);

  const topTechnologies = useMemo(() => product.technologies.slice(0, 8), [product.technologies]);
  const topCapabilities = useMemo(() => product.capabilities.slice(0, 8), [product.capabilities]);

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer-panel" onClick={(e) => e.stopPropagation()} style={{ width: '72vw', maxWidth: '900px' }}>
        <div className="drawer-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <h2 className="panel-title">{product.name}</h2>
            <span className={product.active ? 'badge badge-confirmed' : 'badge badge-inactive'}>
              {product.active ? 'Active' : 'Inactive'}
            </span>
          </div>
          <button className="btn-secondary btn-sm" onClick={onClose} aria-label="Close details">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        <div className="drawer-body">
          {/* Tabs */}
          <div className="panel-tabs" style={{ marginBottom: '0.75rem' }}>
            <button
              className={`panel-tab${tab === 'overview' ? ' active' : ''}`}
              onClick={() => setTab('overview')}
            >
              Overview
            </button>
            <button
              className={`panel-tab${tab === 'matches' ? ' active' : ''}`}
              onClick={() => setTab('matches')}
            >
              Matching Tenders
            </button>
          </div>

          {tab === 'overview' && (
            <>
              {/* Description */}
              <div style={{ marginBottom: '1rem' }}>
                <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '0.85rem', color: 'var(--text-main)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  Description
                </h3>
                <p style={{ color: 'var(--text-secondary)', lineHeight: 1.6, margin: 0 }}>
                  {product.description || 'No description available.'}
                </p>
              </div>

              {/* Capabilities grid */}
              <div style={{ marginBottom: '1rem' }}>
                <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '0.85rem', color: 'var(--text-main)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  Key Capabilities ({product.capabilities.length})
                </h3>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '0.5rem' }}>
                  {topCapabilities.map((cap) => (
                    <div key={cap.id} className="badge badge-product" style={{ padding: '0.5rem 0.75rem', fontSize: '0.82rem', border: '1px solid var(--border-subtle)' }}>
                      {cap.name}
                      {cap.weight && cap.weight !== 1 && (
                        <span style={{ float: 'right', fontSize: '0.7rem', color: 'var(--text-dim)' }}>w={cap.weight}</span>
                      )}
                    </div>
                  ))}
                  {product.capabilities.length === 0 && (
                    <span style={{ color: 'var(--text-dim)', fontStyle: 'italic' }}>No capabilities defined.</span>
                  )}
                </div>
              </div>

              {/* Technologies */}
              <div style={{ marginBottom: '1rem' }}>
                <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '0.85rem', color: 'var(--text-main)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  Technologies ({product.technologies.length})
                </h3>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                  {topTechnologies.map((tech) => (
                    <span key={tech.id} className="badge badge-tech" style={{ fontSize: '0.82rem' }}>
                      {tech.technology}
                    </span>
                  ))}
                  {product.technologies.length === 0 && (
                    <span style={{ color: 'var(--text-dim)', fontStyle: 'italic' }}>No technologies documented.</span>
                  )}
                </div>
              </div>

              {/* Keywords / signals */}
              <div style={{ marginBottom: '1rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                  <h3 style={{ margin: '0', fontSize: '0.85rem', color: 'var(--text-main)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                    Matching Signals ({product.keywords.length})
                  </h3>
                  {canWrite && onDeleteKeyword && (
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                      Remove individual keywords below
                    </span>
                  )}
                </div>
                {keywordDeleteError && (
                  <div className="alert-error" style={{ marginBottom: '0.5rem' }}>{keywordDeleteError}</div>
                )}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '0.5rem' }}>
                  {topKeywords.map((kw) => (
                    <div
                      key={kw.id}
                      className={`badge ${kw.type === 'exclusion' ? 'badge-no_match' : kw.type === 'positive_signal' ? 'badge-match' : kw.type === 'synonym' ? 'badge-possible' : 'badge-keyword'}`}
                      style={{ padding: '0.5rem 0.75rem', fontSize: '0.78rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', position: 'relative', overflow: 'hidden', minWidth: 0 }}
                    >
                      <span>{kw.keyword}</span>
                      <span style={{ fontSize: '0.68rem', color: 'var(--text-dim)' }}>w={kw.weight ?? 1}</span>
                      {canWrite && onDeleteKeyword && deletingKeywordId !== kw.id && (
                        <button
                          className="btn-danger btn-xs"
                          onClick={(e) => { e.stopPropagation(); handleRemoveKeyword(kw.id); }}
                          title={`Remove "${kw.keyword}"`}
                          style={{ padding: '0.15rem 0.35rem', fontSize: '0.65rem', marginLeft: '0.3rem', flexShrink: 0 }}
                        >
                          Remove
                        </button>
                      )}
                      {deletingKeywordId === kw.id && (
                        <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>Removing…</span>
                      )}
                    </div>
                  ))}
                  {product.keywords.length === 0 && (
                    <span style={{ color: 'var(--text-dim)', fontStyle: 'italic' }}>No matching signals defined.</span>
                  )}
                </div>
                {canWrite && onAddKeyword && (
                  <div style={{ marginTop: '0.5rem' }}>
                    <button
                      className="btn-secondary btn-sm"
                      onClick={(e) => { e.stopPropagation(); onAddKeyword?.(); }}
                      title="Add a new keyword"
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                        <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
                      </svg>
                      Add Keyword
                    </button>
                  </div>
                )}
                {canWrite && (
                  <div style={{ marginTop: '0.75rem', padding: '0.75rem', background: 'var(--s-bg-muted)', borderRadius: '6px', fontSize: '0.78rem', color: 'var(--text-secondary)', border: '1px dashed var(--border-subtle)' }}>
                    <strong>Re-evaluation note:</strong> Adding or removing keywords changes how bids are matched against this product. Previously evaluated bids may become stale and should be re-evaluated. Historical match records are preserved; new keyword settings apply to future matching runs.
                  </div>
                )}
              </div>

              {/* Categories */}
              <div>
                <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '0.85rem', color: 'var(--text-main)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  Categories ({product.categories.length})
                </h3>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                  {product.categories.map((cat) => (
                    <span key={cat.id} className="badge badge-info" style={{ fontSize: '0.82rem' }}>
                      {cat.category}
                    </span>
                  ))}
                  {product.categories.length === 0 && (
                    <span style={{ color: 'var(--text-dim)', fontStyle: 'italic' }}>No categories assigned.</span>
                  )}
                </div>
              </div>
            </>
          )}

          {tab === 'matches' && (
            <>
              <div style={{ marginBottom: '0.75rem' }}>
                <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '0.85rem', color: 'var(--text-main)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  Tender Matches
                </h3>
                <p style={{ color: 'var(--text-muted)', fontSize: '0.82rem', margin: 0 }}>
                  {stats?.matching_tenders ?? 0} tender(s) with at least one product match ·{' '}
                  {stats?.total_matches ?? 0} total match record(s)
                </p>
              </div>

              {stats?.matched_states.length > 0 && (
                <div style={{ marginBottom: '0.75rem' }}>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '0.3rem', display: 'block' }}>
                    States / Locations
                  </span>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
                    {stats.matched_states.map((s) => (
                      <span key={s} className="badge badge-map" style={{ fontSize: '0.78rem' }}>{s}</span>
                    ))}
                  </div>
                </div>
              )}

              {stats?.matched_departments.length > 0 && (
                <div style={{ marginBottom: '0.75rem' }}>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '0.3rem', display: 'block' }}>
                    Departments
                  </span>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
                    {stats.matched_departments.map((d) => (
                      <span key={d} className="badge badge-info" style={{ fontSize: '0.78rem' }}>{d}</span>
                    ))}
                  </div>
                </div>
              )}

              {stats?.matched_organisations.length > 0 && (
                <div style={{ marginBottom: '0.75rem' }}>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '0.3rem', display: 'block' }}>
                    Organisations
                  </span>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
                    {stats.matched_organisations.map((o) => (
                      <span key={o} className="badge badge-info" style={{ fontSize: '0.78rem' }}>{o}</span>
                    ))}
                  </div>
                </div>
              )}

              {(!stats || (stats.matching_tenders ?? 0) === 0) && (
                <div className="empty-state" style={{ padding: '1rem' }}>
                  <div className="empty-title">No matching tenders</div>
                  <div className="empty-desc">
                    No state-wise or GeM tenders have matched this product yet.
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Keyword Row (simplified, reused from original) ──
interface KeywordRowProps {
  keyword: ProductKeyword;
  onEdit: (kw: ProductKeyword) => void;
  onDelete: (keywordId: string) => Promise<void>;
  busy: boolean;
}

function KeywordRow({ keyword, onEdit, onDelete, busy }: KeywordRowProps) {
  const [deleting, setDeleting] = useState(false);

  const typeBadge = (t: string) => {
    const styles: Record<string, string> = {
      keyword: 'badge badge-keyword',
      synonym: 'badge badge-synonym',
      technology: 'badge badge-tech',
      positive_signal: 'badge badge-positive',
      exclusion: 'badge badge-exclusion',
    };
    return <span className={styles[t] || 'badge'}>{t}</span>;
  };

  return (
    <div className="keyword-row">
      <span className="keyword-text">{keyword.keyword}</span>
      {typeBadge(keyword.type)}
      <span className="keyword-weight">w={keyword.weight}</span>
      {keyword.active ? <span className="badge badge-active">active</span> : <span className="badge badge-inactive">inactive</span>}
      <div className="keyword-actions">
        {!busy && !deleting && (
          <button className="btn-secondary btn-xs" onClick={() => onEdit(keyword)} title="Edit keyword">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
          </button>
        )}
        {!busy && !deleting && (
          <button className="btn-danger btn-xs" onClick={async () => { setDeleting(true); try { await onDelete(keyword.id); } catch (_) { setDeleting(false); } }} title="Delete keyword">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
            </svg>
          </button>
        )}
        {deleting && <span className="btn-xs busy">Deleting…</span>}
      </div>
    </div>
  );
}

// ── Keyword Management Modal ──
interface KeywordDialogProps {
  product: Product;
  submitting: boolean;
  onCancel: () => void;
  onAdd: (payload: ProductKeywordPayload) => void;
  onUpdate: (keywordId: string, payload: ProductKeywordPayload) => void;
  onDelete: (keywordId: string) => void;
  initialEditKeyword?: ProductKeyword | null;
}

function KeywordDialog({
  product,
  submitting,
  onCancel,
  onAdd,
  onUpdate,
  onDelete,
  initialEditKeyword,
}: KeywordDialogProps) {
  const [keyword, setKeyword] = useState('');
  const [weight, setWeight] = useState(1.0);
  const [type, setType] = useState('keyword');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isEditing = editingId !== null;
  const existing = isEditing ? product.keywords.find((k) => k.id === editingId) : initialEditKeyword;

  React.useEffect(() => {
    if (existing) {
      setEditingId(existing.id);
      setKeyword(existing.keyword);
      setWeight(existing.weight ?? 1.0);
      setType(existing.type);
      setError(null);
    } else if (!isEditing) {
      setKeyword(''); setWeight(1.0); setType('keyword');
    }
  }, [existing, isEditing, product.keywords]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!keyword.trim()) { setError('Keyword is required.'); return; }
    const trimmed = keyword.trim();
    const exists = product.keywords.some((k) => k.keyword.toLowerCase() === trimmed.toLowerCase());
    if (exists) { setError('This keyword already exists on the product.'); return; }
    setError(null);
    const payload: ProductKeywordPayload = { keyword: trimmed, weight, type, active: true };
    try {
      if (isEditing && editingId) {
        await onUpdate(editingId, payload);
        setEditingId(null); setKeyword(''); setWeight(1.0); setType('keyword');
      } else {
        await onAdd(payload);
        setKeyword(''); setWeight(1.0); setType('keyword');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Keyword could not be saved.');
    }
  };

  const cancelEdit = () => { setEditingId(null); setKeyword(''); setWeight(1.0); setType('keyword'); setError(null); };

  const handleDelete = async (keywordId: string) => {
    const kw = product.keywords.find((k) => k.id === keywordId);
    if (!window.confirm(`Delete keyword "${kw?.keyword}"?`)) return;
    try { await onDelete(keywordId); if (editingId === keywordId) { setEditingId(null); setKeyword(''); setWeight(1.0); setType('keyword'); } } catch (err) { setError(err instanceof Error ? err.message : 'Keyword could not be deleted.'); }
  };

  const typeOptions = [
    { value: 'keyword', label: 'Keyword' },
    { value: 'synonym', label: 'Synonym' },
    { value: 'technology', label: 'Technology' },
    { value: 'positive_signal', label: 'Positive Signal' },
    { value: 'exclusion', label: 'Exclusion' },
  ];

  return (
    <div className="modal-backdrop" data-testid="keyword-dialog" onClick={onCancel}>
      <div className="modal-panel modal-panel-sm" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-title">{isEditing ? 'Edit Keyword' : 'Add Keyword'}</h2>
          <span className="modal-subtitle">Product: {product.name}</span>
          <button className="btn-secondary btn-sm" onClick={onCancel} aria-label="Close">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
        <div className="modal-body">
          {error && <div className="alert-error">{error}</div>}
          <form onSubmit={handleSubmit}>
            <div className="field-group">
              <label className="field-label" htmlFor="kw-keyword">Keyword <span style={{ color: 'var(--s-urgent-text)' }}>*</span></label>
              <input id="kw-keyword" className="form-input" value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="e.g. vulnerability assessment" autoFocus />
            </div>
            <div className="field-group">
              <label className="field-label" htmlFor="kw-weight">Weight</label>
              <input id="kw-weight" className="form-input" type="number" step="0.1" min="0" max="10" value={weight} onChange={(e) => setWeight(parseFloat(e.target.value) || 1.0)} placeholder="1.0" />
              <p className="field-hint">Higher weight = stronger match signal.</p>
            </div>
            <div className="field-group">
              <label className="field-label" htmlFor="kw-type">Type</label>
              <select id="kw-type" className="form-select" value={type} onChange={(e) => setType(e.target.value)}>
                {typeOptions.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
              </select>
            </div>
            <div className="modal-footer" style={{ marginTop: '1rem', borderTop: '1px solid var(--s-border)' }}>
              <button type="button" className="btn-secondary" onClick={cancelEdit} disabled={submitting}>{isEditing ? 'Cancel Edit' : 'Cancel'}</button>
              <button type="submit" className="btn-primary" disabled={submitting || !keyword.trim()}>{submitting ? 'Saving…' : isEditing ? 'Update Keyword' : 'Add Keyword'}</button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

// ── Add Product Modal ──
interface AddProductDialogProps {
  submitting: boolean;
  onCancel: () => void;
  onSubmit: (name: string, description: string) => void;
}

function AddProductDialog({ submitting, onCancel, onSubmit }: AddProductDialogProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = () => {
    if (!name.trim()) { setError('Product name is required.'); return; }
    setError(null);
    onSubmit(name.trim(), description.trim());
  };

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal-panel modal-panel-sm" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-title">Add Product</h2>
          <button className="btn-secondary btn-sm" onClick={onCancel} aria-label="Close">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
        <div className="modal-body">
          {error && <div className="alert-error">{error}</div>}
          <div className="field-group">
            <label className="field-label" htmlFor="add-product-name">Product Name <span style={{ color: 'var(--s-urgent-text)' }}>*</span></label>
            <input id="add-product-name" className="form-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. SolidityShield" maxLength={100} autoFocus />
          </div>
          <div className="field-group" style={{ marginBottom: '0.5rem' }}>
            <label className="field-label" htmlFor="add-product-desc">Description</label>
            <textarea id="add-product-desc" className="form-textarea" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Short summary of what this product delivers and its key capabilities." rows={3} />
          </div>
          <p className="field-hint">The product is saved immediately and becomes available to the matching engine.</p>
        </div>
        <div className="modal-footer">
          <button className="btn-secondary" onClick={onCancel} disabled={submitting}>Cancel</button>
          <button className="btn-primary" onClick={handleSubmit} disabled={submitting}>{submitting ? 'Saving…' : 'Add Product'}</button>
        </div>
      </div>
    </div>
  );
}

// ── Delete / Deactivate Confirmation ──
interface DeleteDialogProps {
  product: Product;
  busy: boolean;
  serverError: string | null;
  canReactivate: boolean;
  onConfirm: () => void;
  onReactivate: () => void;
  onCancel: () => void;
}

function DeleteDialog({ product, busy, serverError, canReactivate, onConfirm, onReactivate, onCancel }: DeleteDialogProps) {
  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal-panel modal-panel-sm" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-title">Remove {product.name}?</h2>
          <button className="btn-secondary btn-sm" onClick={onCancel} aria-label="Close">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
        <div className="modal-body">
          <div className="alert-warning" style={{ marginBottom: serverError ? '0.85rem' : '0' }}>
            Removing <strong>{product.name}</strong> will stop it from participating in future bid matching. Historical bid analyses that already reference it are preserved.
          </div>
          {serverError && <div className="alert-error" style={{ marginBottom: 0 }}>{serverError}</div>}
        </div>
        <div className="modal-footer">
          <button className="btn-secondary" onClick={onCancel} disabled={busy}>Cancel</button>
          {canReactivate && <button className="btn-secondary" onClick={onReactivate} disabled={busy}>{busy ? 'Working…' : 'Deactivate Only'}</button>}
          <button className="btn-danger" onClick={onConfirm} disabled={busy}>{busy ? 'Removing…' : 'Remove Product'}</button>
        </div>
      </div>
    </div>
  );
}
