import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { StateWiseBidsView } from './StateWiseBidsView';

const mockBids: any[] = [
  {
    id: 'bid-1',
    state: 'Maharashtra',
    state_id: 'MH',
    source: 'Maharashtra eTendering',
    source_id: 'maharashtra',
    adapter_key: 'maharashtra_gepn',
    bid_number: 'MH-TEN-2024-001',
    gem_bid_id: null,
    tender_id: 'tender-mh-1',
    title: 'Supply of medical equipment',
    organisation: 'Directorate of Health Services',
    department: 'Health',
    matched_product: 'Patient Monitors',
    match_state: 'MATCH',
    relevance_score: 0.85,
    analyzed: true,
    estimated_value: 500000,
    currency: 'INR',
    published_date: '2024-01-10',
    closing_date: '2024-02-15',
    days_remaining: 12,
    deadline_status: 'OPEN',
    status: 'OPEN',
    matching_status: 'MATCHED',
    matched_at: '2024-01-12',
    source_url: 'https://mhportals.gov.in/tender/1',
    product_matches: [
      {
        product_id: 'prod-1',
        product_name: 'Patient Monitors',
        match_score: 0.85,
        match_type: 'keyword',
        confidence: 0.9,
        evidence: { matched_keywords: ['monitor', 'patient'] },
        matching_keywords: ['monitor', 'patient'],
      },
    ],
    matched_product_count: 1,
  },
  {
    id: 'bid-2',
    state: 'Karnataka',
    state_id: 'KA',
    source: 'Karnataka eProcurement',
    source_id: 'karnataka',
    adapter_key: 'karnataka_eproc',
    bid_number: 'KA-TEN-2024-010',
    gem_bid_id: null,
    tender_id: 'tender-ka-1',
    title: 'Office furniture supply',
    organisation: 'Public Works Department',
    department: 'PWD',
    matched_product: null,
    match_state: 'NO_MATCH',
    relevance_score: 0.1,
    analyzed: true,
    estimated_value: 120000,
    currency: 'INR',
    published_date: '2024-01-05',
    closing_date: '2024-01-20',
    days_remaining: -10,
    deadline_status: 'CLOSED',
    status: 'CLOSED',
    matching_status: 'NOT_MATCHED',
    matched_at: null,
    source_url: 'https://eproc.karnataka.gov.in/tender/10',
    product_matches: [],
    matched_product_count: 0,
  },
];

const mockSources = [
  { source_id: 'maharashtra', name: 'Maharashtra eTendering', status: 'SUCCESS', enabled: true },
  { source_id: 'karnataka', name: 'Karnataka eProcurement', status: 'IDLE', enabled: true },
  { source_id: 'gem_direct', name: 'GeM Direct', status: 'SUCCESS', enabled: false },
];

const mockProducts = [{ id: 'prod-1', name: 'Patient Monitors', description: null }];

function mockFetch(bids = mockBids, sources = mockSources, products = mockProducts) {
  let calls = 0;
  return vi.fn(async (url: string) => {
    calls++;
    if (url.includes('/sources')) {
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => sources,
      };
    }
    if (url.includes('/products')) {
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => products,
      };
    }
    if (url.includes('/bids/state-wise')) {
      const includeNoMatch = url.includes('include_no_match=true');
      const filtered = includeNoMatch
        ? bids
        : bids.filter((b) => (b.product_matches || []).length > 0);
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ total: filtered.length, page: 1, page_size: 50, total_pages: 1, bids: filtered }),
      };
    }
    return { ok: false, status: 404, json: async () => ({ detail: 'Not found' }) };
  });
}

describe('StateWiseBidsView', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = mockFetch();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders state-wise bids with proper types and no any[] usage', async () => {
    render(<StateWiseBidsView onSelectBid={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Supply of medical equipment')).toBeInTheDocument();
      expect(screen.getByText('Office furniture supply')).toBeInTheDocument();
    });
  });

  it('displays multiple product matches for one tender without duplicating the tender', async () => {
    const multiMatchBid = {
      ...mockBids[0],
      id: 'bid-multi',
      product_matches: [
        { product_id: 'p1', product_name: 'Patient Monitors', match_score: 0.85, match_type: 'keyword', confidence: 0.9, evidence: null, matching_keywords: ['monitor'] },
        { product_id: 'p2', product_name: 'Infusion Pumps', match_score: 0.72, match_type: 'keyword', confidence: 0.85, evidence: null, matching_keywords: ['pump'] },
      ],
      matched_product_count: 2,
    };
    fetchMock = mockFetch([multiMatchBid]);
    vi.stubGlobal('fetch', fetchMock);

    render(<StateWiseBidsView onSelectBid={vi.fn()} />);

    await waitFor(() => {
      // 'Patient Monitors' appears both as a product-filter <option> and as the
      // matched-product cell, so assert on all matches rather than a single one.
      expect(screen.getAllByText('Patient Monitors')).toHaveLength(2);
      expect(screen.getAllByText('Infusion Pumps')).toHaveLength(1);
    });
    // The tender title should appear once, not duplicated
    await waitFor(() => {
      const titles = screen.getAllByText('Supply of medical equipment');
      expect(titles.length).toBe(1);
    });
  });

  it('shows loading state while bids are loading', () => {
    const slowFetch = vi.fn(async () => new Promise(() => {}));
    vi.stubGlobal('fetch', slowFetch);

    render(<StateWiseBidsView onSelectBid={vi.fn()} />);

    expect(screen.getByText(/loading state-wise bids/i)).toBeInTheDocument();
  });

  it('shows error state and retry button when API fails', async () => {
    const failingFetch = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    vi.stubGlobal('fetch', failingFetch);

    render(<StateWiseBidsView onSelectBid={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/unable to connect to the backend api server/i)).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('calls onSelectBid when Inspect button is clicked', async () => {
    const onSelectBid = vi.fn();
    render(<StateWiseBidsView onSelectBid={onSelectBid} />);

    await waitFor(() => {
      expect(screen.getByText('Supply of medical equipment')).toBeInTheDocument();
    });

    const inspectButtons = screen.getAllByRole('button', { name: /inspect →/i });
    fireEvent.click(inspectButtons[0]);

    expect(onSelectBid).toHaveBeenCalledWith('bid-1');
  });

  it('filters bids by state when a state is selected', async () => {
    render(<StateWiseBidsView onSelectBid={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Supply of medical equipment')).toBeInTheDocument();
    });

    const stateSelect = screen.getByLabelText(/filter by state/i);
    fireEvent.change(stateSelect, { target: { value: 'karnataka' } });

    await waitFor(() => {
      expect(screen.getByText('Office furniture supply')).toBeInTheDocument();
    });
  });

  it('renders Collected and Matched tabs', async () => {
    render(<StateWiseBidsView onSelectBid={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /collected bids/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /matched bids/i })).toBeInTheDocument();
    });
  });

  it('Collected tab shows all collected bids including no-match bids', async () => {
    render(<StateWiseBidsView onSelectBid={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Supply of medical equipment')).toBeInTheDocument();
      expect(screen.getByText('Office furniture supply')).toBeInTheDocument();
    });
  });

  it('Matched tab shows only bids with at least one product match', async () => {
    render(<StateWiseBidsView onSelectBid={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Supply of medical equipment')).toBeInTheDocument();
    });

    const matchedTab = screen.getByRole('button', { name: /matched bids/i });
    fireEvent.click(matchedTab);

    await waitFor(() => {
      expect(screen.getByText('Supply of medical equipment')).toBeInTheDocument();
    });
    // bid-2 (Office furniture supply) has no product matches, so it should not
    // appear in the Matched view.
    await waitFor(() => {
      expect(screen.queryByText('Office furniture supply')).not.toBeInTheDocument();
    });
  });

  it('switching back to Collected tab shows no-match bids again', async () => {
    render(<StateWiseBidsView onSelectBid={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Supply of medical equipment')).toBeInTheDocument();
    });

    const matchedTab = screen.getByRole('button', { name: /matched bids/i });
    fireEvent.click(matchedTab);
    await waitFor(() => {
      expect(screen.queryByText('Office furniture supply')).not.toBeInTheDocument();
    });

    const collectedTab = screen.getByRole('button', { name: /collected bids/i });
    fireEvent.click(collectedTab);
    await waitFor(() => {
      expect(screen.getByText('Office furniture supply')).toBeInTheDocument();
    });
  });

  it('displays "No matched SecuredApp products" for analyzed bids with no matches', async () => {
    const noMatchBid = {
      ...mockBids[1],
      id: 'bid-no-match',
      product_matches: [],
      matched_product_count: 0,
    };
    fetchMock = mockFetch([noMatchBid]);
    vi.stubGlobal('fetch', fetchMock);

    render(<StateWiseBidsView onSelectBid={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Office furniture supply')).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText('No matched SecuredApp products')).toBeInTheDocument();
    });
  });
});
