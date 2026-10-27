import React, { useMemo, useState } from 'react';
import { Product } from '../types';

interface ProductsViewProps {
  products: Product[];
  loading: boolean;
  onCreate: (payload: { name: string; description: string | null }) => Promise<void>;
  onDelete: (productId: string) => Promise<{ blocked: boolean; message: string }>;
  onReactivate: (productId: string) => Promise<void>;
}

type StatusFilter = 'all' | 'active' | 'inactive';

// ── Add Product Modal ──────────────────────────────────────────────────────

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
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>

        <div className="modal-body">
          {error && <div className="alert-error">{error}</div>}

          <div className="field-group">
            <label className="field-label" htmlFor="add-product-name">
              Product Name <span style={{ color: 'var(--s-urgent-text)' }}>*</span>
            </label>
            <input
              id="add-product-name"
              className="form-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. SolidityShield"
              maxLength={100}
              autoFocus
            />
          </div>

          <div className="field-group" style={{ marginBottom: '0.5rem' }}>
            <label className="field-label" htmlFor="add-product-desc">Description</label>
            <textarea
              id="add-product-desc"
              className="form-textarea"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Short summary of what this product delivers and its key capabilities."
              rows={3}
            />
          </div>

          <p className="field-hint">
            The product is saved immediately and becomes available to the matching engine.
          </p>
        </div>

        <div className="modal-footer">
          <button className="btn-secondary" onClick={onCancel} disabled={submitting}>Cancel</button>
          <button className="btn-primary" onClick={handleSubmit} disabled={submitting}>
            {submitting ? 'Saving…' : 'Add Product'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Delete / Deactivate Confirmation ──────────────────────────────────────

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
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>

        <div className="modal-body">
          <div className="alert-warning" style={{ marginBottom: serverError ? '0.85rem' : '0' }}>
            Removing <strong>{product.name}</strong> will stop it from participating in future bid
            matching. Historical bid analyses that already reference it are preserved.
          </div>
          {serverError && (
            <div className="alert-error" style={{ marginBottom: 0 }}>
              {serverError}
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button className="btn-secondary" onClick={onCancel} disabled={busy}>Cancel</button>
          {canReactivate && (
            <button className="btn-secondary" onClick={onReactivate} disabled={busy}>
              {busy ? 'Working…' : 'Deactivate Only'}
            </button>
          )}
          <button className="btn-danger" onClick={onConfirm} disabled={busy}>
            {busy ? 'Removing…' : 'Remove Product'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Capability Summary ─────────────────────────────────────────────────────

function CapabilitySummary({ product }: { product: Product }) {
  const parts = [
    product.capabilities.length > 0 ? `${product.capabilities.length} capabilities` : null,
    product.keywords.length > 0     ? `${product.keywords.length} signals`          : null,
  ].filter(Boolean) as string[];

  if (parts.length === 0) {
    return <span className="pm-knowledge-summary" style={{ fontStyle: 'italic' }}>No matching knowledge</span>;
  }
  return <span className="pm-knowledge-summary">{parts.join(' · ')}</span>;
}

// ── Main Component ─────────────────────────────────────────────────────────

/**
 * Products — simplified management view.
 * Displays product name, description, status.
 * Actions: Add, Activate, Deactivate/Remove.
 * No capability/keyword editors exposed here.
 */
export const ProductsView: React.FC<ProductsViewProps> = ({
  products,
  loading,
  onCreate,
  onDelete,
  onReactivate,
}) => {
  const [search, setSearch]               = useState('');
  const [statusFilter, setStatusFilter]   = useState<StatusFilter>('all');
  const [showAdd, setShowAdd]             = useState(false);
  const [deleteTarget, setDeleteTarget]   = useState<Product | null>(null);
  const [busy, setBusy]                   = useState(false);
  const [deleteError, setDeleteError]     = useState<string | null>(null);
  const [pageError, setPageError]         = useState<string | null>(null);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return products.filter((p) => {
      if (statusFilter === 'active'   && !p.active) return false;
      if (statusFilter === 'inactive' &&  p.active) return false;
      if (!term) return true;
      return (
        p.name.toLowerCase().includes(term) ||
        (p.description ?? '').toLowerCase().includes(term)
      );
    });
  }, [products, search, statusFilter]);

  const activeCount   = products.filter((p) => p.active).length;
  const inactiveCount = products.length - activeCount;

  const handleCreate = async (name: string, description: string) => {
    setBusy(true);
    setPageError(null);
    try {
      await onCreate({ name, description: description || null });
      setShowAdd(false);
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
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : 'The product could not be reactivated.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card-panel">
      <div className="panel-header">
        <div>
          <h2 className="panel-title">Products</h2>
          <p className="panel-subtitle">
            Products the matching engine evaluates bids against · {activeCount} active
            {inactiveCount > 0 ? ` · ${inactiveCount} inactive` : ''}
          </p>
        </div>
        <button className="btn-primary btn-sm" onClick={() => setShowAdd(true)}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          Add Product
        </button>
      </div>

      {pageError && <div className="alert-error">{pageError}</div>}

      <div className="pm-toolbar">
        <div className="search-input-wrapper">
          <svg className="search-icon-inside" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            className="search-input"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search products…"
            aria-label="Search products"
          />
        </div>
        <select
          className="filter-select"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
          aria-label="Filter by status"
        >
          <option value="all">All ({products.length})</option>
          <option value="active">Active ({activeCount})</option>
          <option value="inactive">Inactive ({inactiveCount})</option>
        </select>
      </div>

      {loading ? (
        <div className="empty-state">
          <div className="empty-desc">Loading products…</div>
        </div>
      ) : products.length === 0 ? (
        <div className="empty-state">
          <div className="empty-title">No products configured</div>
          <div className="empty-desc">
            Add a product to give the matching engine something to evaluate bids against.
          </div>
          <button className="btn-primary btn-sm" onClick={() => setShowAdd(true)} style={{ marginTop: '0.25rem' }}>
            Add Product
          </button>
        </div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">
          <div className="empty-title">No products match your filters</div>
          <div className="empty-desc">Try a different search term or status filter.</div>
        </div>
      ) : (
        <div className="product-grid">
          {filtered.map((product) => (
            <div
              key={product.id}
              className={`product-card${product.active ? '' : ' product-card-inactive'}`}
            >
              <div className="product-card-head">
                <h3 className="product-card-name">{product.name}</h3>
                <span className={product.active ? 'badge badge-confirmed' : 'badge badge-inactive'}>
                  {product.active ? 'Active' : 'Inactive'}
                </span>
              </div>

              <p className="product-card-desc">
                {product.description || (
                  <span className="unanalysed-note">No description added</span>
                )}
              </p>

              <div className="product-card-foot">
                <CapabilitySummary product={product} />
                {product.active ? (
                  <button
                    className="btn-danger btn-sm"
                    onClick={() => { setDeleteError(null); setDeleteTarget(product); }}
                  >
                    Remove
                  </button>
                ) : (
                  <button
                    className="btn-secondary btn-sm"
                    onClick={async () => {
                      setPageError(null);
                      try { await onReactivate(product.id); }
                      catch (err) {
                        setPageError(err instanceof Error ? err.message : 'Could not reactivate.');
                      }
                    }}
                  >
                    Activate
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
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
    </div>
  );
};
