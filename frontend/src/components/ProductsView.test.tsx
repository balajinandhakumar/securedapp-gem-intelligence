import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ProductsView } from './ProductsView';
import { Product } from '../types';

const mockProducts: Product[] = [
  {
    id: 'p1',
    name: 'Patient Monitors',
    description: 'Vital signs monitoring',
    active: true,
    priority: 1,
    capabilities: [],
    keywords: [],
    technologies: [],
    categories: [{ id: 'cat-1', category: 'Medical Devices' }],
  },
  {
    id: 'p2',
    name: 'Infusion Pumps',
    description: 'Fluid delivery pumps',
    active: false,
    priority: 2,
    capabilities: [],
    keywords: [],
    technologies: [],
    categories: [{ id: 'cat-1', category: 'Medical Devices' }],
  },
];

const mockCatalogueStats: any = {
  total_products: 11,
  active_products: 10,
  total_categories: 6,
  products_with_matches: 8,
  total_matching_tenders: 142,
  product_stats: [
    { product_id: 'p1', product_name: 'Patient Monitors', matching_tenders: 45, total_matches: 60, highest_relevance_score: 0.92, highest_classification: 'MATCH', matched_states: ['MH', 'KA'] },
    { product_id: 'p2', product_name: 'Infusion Pumps', matching_tenders: 30, total_matches: 40, highest_relevance_score: 0.78, highest_classification: 'Relevant', matched_states: ['MH'] },
  ],
};

function mockFetch(stats = mockCatalogueStats) {
  return vi.fn(async (url: string) => {
    if (url.includes('/products/catalogue-stats')) {
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => stats,
      };
    }
    return { ok: false, status: 404, json: async () => ({ detail: 'Not found' }) };
  });
}

const noopDelete = async (_productId: string): Promise<{ blocked: boolean; message: string }> => ({
  blocked: false,
  message: '',
});
const noop = async () => {};
const canWriteProducts = () => true;

describe('ProductsView — catalogue statistics', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = mockFetch();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders product catalogue statistics from the backend', async () => {
    render(
      <ProductsView
        products={mockProducts}
        loading={false}
        onCreate={noop}
        onDelete={noopDelete}
        onReactivate={noop}
        onAddKeyword={noop}
        onUpdateKeyword={noop}
        onDeleteKeyword={noop}
        canWriteProducts={canWriteProducts}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('Products with matches')).toBeInTheDocument();
      expect(screen.getByText('8')).toBeInTheDocument();
      expect(screen.getByText('Matching tenders')).toBeInTheDocument();
      expect(screen.getByText('142')).toBeInTheDocument();
    });
  });

  it('displays loading state while catalogue stats are loading', () => {
    const slowFetch = vi.fn(async () => new Promise(() => {}));
    vi.stubGlobal('fetch', slowFetch);

    render(
      <ProductsView
        products={mockProducts}
        loading={false}
        onCreate={noop}
        onDelete={noopDelete}
        onReactivate={noop}
        onAddKeyword={noop}
        onUpdateKeyword={noop}
        onDeleteKeyword={noop}
        canWriteProducts={canWriteProducts}
      />
    );

    expect(screen.getByText(/loading product catalogue/i)).toBeInTheDocument();
  });

  it('shows error state and retry button when catalogue stats fail', async () => {
    const failingFetch = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    vi.stubGlobal('fetch', failingFetch);

    render(
      <ProductsView
        products={mockProducts}
        loading={false}
        onCreate={noop}
        onDelete={noopDelete}
        onReactivate={noop}
        onAddKeyword={noop}
        onUpdateKeyword={noop}
        onDeleteKeyword={noop}
        canWriteProducts={canWriteProducts}
      />
    );

    await waitFor(() => {
      expect(screen.getByText(/unable to reach the catalogue statistics endpoint/i)).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('displays product cards and supports search filtering', async () => {
    render(
      <ProductsView
        products={mockProducts}
        loading={false}
        onCreate={noop}
        onDelete={noopDelete}
        onReactivate={noop}
        onAddKeyword={noop}
        onUpdateKeyword={noop}
        onDeleteKeyword={noop}
        canWriteProducts={canWriteProducts}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('Patient Monitors')).toBeInTheDocument();
      expect(screen.getByText('Infusion Pumps')).toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText(/search product name, capability, or keyword…/i);
    fireEvent.change(searchInput, { target: { value: 'Infusion' } });

    await waitFor(() => {
      expect(screen.getByText('Infusion Pumps')).toBeInTheDocument();
    });
    // Patient Monitors should be filtered out
    expect(screen.queryByText('Patient Monitors')).not.toBeInTheDocument();
  });
});

// ── Keyword management tests ──
describe('ProductsView — keyword management', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = mockFetch();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const productWithKeywords: Product = {
    id: 'p-kw',
    name: 'Test Product',
    description: 'A test product',
    active: true,
    priority: 1,
    capabilities: [],
    keywords: [
      { id: 'kw-1', keyword: 'existing keyword', weight: 1.0, type: 'keyword', active: true },
    ],
    technologies: [],
    categories: [],
  };

  it('opens product detail drawer and displays existing keywords with Remove action', async () => {
    const onDeleteKeyword = vi.fn(async () => {});
    render(
      <ProductsView
        products={[productWithKeywords]}
        loading={false}
        onCreate={noop}
        onDelete={noopDelete}
        onReactivate={noop}
        onAddKeyword={noop}
        onUpdateKeyword={noop}
        onDeleteKeyword={onDeleteKeyword}
        canWriteProducts={() => true}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('Test Product')).toBeInTheDocument();
    });

    // Click product card to open detail drawer
    fireEvent.click(screen.getByText('Test Product'));

    await waitFor(() => {
      expect(screen.getByText('Matching Signals (1)')).toBeInTheDocument();
      expect(screen.getByText('existing keyword')).toBeInTheDocument();
      // Remove button should be visible for operators
      expect(screen.getByRole('button', { name: /remove/i })).toBeInTheDocument();
    });

    // Mock window.confirm (not implemented in jsdom) and click Remove
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    fireEvent.click(screen.getByRole('button', { name: /remove/i }));

    await waitFor(() => {
      expect(onDeleteKeyword).toHaveBeenCalledWith('p-kw', 'kw-1');
    });
  });

  it('opens Add Keyword dialog from product detail drawer', async () => {
    const onAddKeyword = vi.fn(async () => {});
    render(
      <ProductsView
        products={[productWithKeywords]}
        loading={false}
        onCreate={noop}
        onDelete={noopDelete}
        onReactivate={noop}
        onAddKeyword={onAddKeyword}
        onUpdateKeyword={noop}
        onDeleteKeyword={noop}
        canWriteProducts={() => true}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('Test Product')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Test Product'));

    await waitFor(() => {
      expect(screen.getByText('Matching Signals (1)')).toBeInTheDocument();
    });

    // Click Add Keyword button in drawer
    fireEvent.click(screen.getAllByRole('button', { name: /add keyword/i })[0]);

    await waitFor(() => {
      expect(screen.getByTestId('keyword-dialog')).toBeInTheDocument();
    });

    // Fill in keyword and submit
    const keywordInput = screen.getByPlaceholderText(/e.g. vulnerability assessment/i);
    fireEvent.change(keywordInput, { target: { value: 'new test keyword' } });
    fireEvent.click(screen.getAllByRole('button', { name: /add keyword/i })[1]);

    await waitFor(() => {
      expect(onAddKeyword).toHaveBeenCalledWith(
        'p-kw',
        expect.objectContaining({ keyword: 'new test keyword' })
      );
    });
  });

  it('VIEWER cannot add or remove keywords (canWriteProducts returns false)', async () => {
    render(
      <ProductsView
        products={[productWithKeywords]}
        loading={false}
        onCreate={noop}
        onDelete={noopDelete}
        onReactivate={noop}
        onAddKeyword={noop}
        onUpdateKeyword={noop}
        onDeleteKeyword={noop}
        canWriteProducts={() => false}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('Test Product')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Test Product'));

    await waitFor(() => {
      expect(screen.getByText('Matching Signals (1)')).toBeInTheDocument();
    });

    // VIEWER should not see Remove buttons or Add Keyword button
    expect(screen.queryByRole('button', { name: /remove/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /add keyword/i })).not.toBeInTheDocument();
  });

  it('shows re-evaluation guidance when keywords exist and user can write', async () => {
    render(
      <ProductsView
        products={[productWithKeywords]}
        loading={false}
        onCreate={noop}
        onDelete={noopDelete}
        onReactivate={noop}
        onAddKeyword={noop}
        onUpdateKeyword={noop}
        onDeleteKeyword={noop}
        canWriteProducts={() => true}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('Test Product')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Test Product'));

    await waitFor(() => {
      expect(screen.getByText(/re-evaluation note/i)).toBeInTheDocument();
    });
  });
});
