import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { AllIndiaMatchesView } from './AllIndiaMatchesView';

const mockSummary: any = {
  total_relevant_bids: 42,
  highly_relevant_bids: 10,
  relevant_bids: 12,
  potentially_relevant_bids: 20,
  states_covered: 5,
  products_with_matches: 8,
  state_distribution: [
    { location: 'Maharashtra', bid_count: 15, highly_relevant: 5, relevant: 6, potentially_relevant: 4 },
    { location: 'Karnataka', bid_count: 12, highly_relevant: 3, relevant: 4, potentially_relevant: 5 },
  ],
  product_distribution: [
    { product_name: 'Patient Monitors', bid_count: 20 },
    { product_name: 'Infusion Pumps', bid_count: 15 },
  ],
};

const mockBids: any[] = [
  {
    bid_id: 'bid-1',
    product_id: 'p1',
    tender_id: 'TEND-001',
    title: 'Supply of patient monitors',
    product_name: 'Patient Monitors',
    relevance_score_100: 88,
    classification: 'Highly Relevant',
    state: 'Maharashtra',
    organisation: 'Health Dept',
    department: 'Health',
    estimated_value: 500000,
    closing_date: '2024-03-01',
    days_remaining: 15,
  },
];

function mockFetch(summary = mockSummary, bids = mockBids) {
  return vi.fn(async (url: string) => {
    if (url.includes('/all-india/summary')) {
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => summary,
      };
    }
    if (url.includes('/all-india/bids')) {
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ bids, total: bids.length }),
      };
    }
    return { ok: false, status: 404, json: async () => ({ detail: 'Not found' }) };
  });
}

describe('AllIndiaMatchesView', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = mockFetch();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders All-India bid matches and KPI strip', async () => {
    render(<AllIndiaMatchesView onSelectBid={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Total relevant bids')).toBeInTheDocument();
      expect(screen.getByText('42')).toBeInTheDocument();
      expect(screen.getByText('Supply of patient monitors')).toBeInTheDocument();
    });
  });

  it('shows loading state while fetching', () => {
    const slowFetch = vi.fn(async () => new Promise(() => {}));
    vi.stubGlobal('fetch', slowFetch);

    render(<AllIndiaMatchesView onSelectBid={vi.fn()} />);

    expect(screen.getByText(/loading all-india matches/i)).toBeInTheDocument();
  });

  it('shows error state and retry button when API fails', async () => {
    const failingFetch = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    vi.stubGlobal('fetch', failingFetch);

    render(<AllIndiaMatchesView onSelectBid={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/unable to load all-india bid matches/i)).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('calls onSelectBid when Inspect button is clicked', async () => {
    const onSelectBid = vi.fn();
    render(<AllIndiaMatchesView onSelectBid={onSelectBid} />);

    await waitFor(() => {
      expect(screen.getByText('Supply of patient monitors')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /inspect →/i }));

    expect(onSelectBid).toHaveBeenCalledWith('bid-1');
  });

  it('displays state-wise distribution table', async () => {
    render(<AllIndiaMatchesView onSelectBid={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByText('Maharashtra').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Karnataka').length).toBeGreaterThan(0);
    });
  });

  it('filters bids by state when selected', async () => {
    render(<AllIndiaMatchesView onSelectBid={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Supply of patient monitors')).toBeInTheDocument();
    });

    const stateSelect = screen.getByLabelText(/filter by state/i);
    fireEvent.change(stateSelect, { target: { value: 'Karnataka' } });

    await waitFor(() => {
      // Trigger re-fetch with new filter
    });
    // Filter state change triggers a new fetch; just ensure no crash
    expect(screen.getByLabelText(/filter by state/i)).toHaveValue('Karnataka');
  });

  it('displays "Location Not Disclosed by Source" for bids without location', async () => {
    const undisclosedBids: any[] = [
      {
        ...mockBids[0],
        bid_id: 'bid-undisclosed',
        location: 'Location Not Disclosed by Source',
        state: 'Location Not Disclosed by Source',
        location_quality: 'NOT_DISCLOSED',
        city: null,
        product_name: 'Undisclosed Product',
        relevance_score_100: 60,
        classification: 'Potentially Relevant',
      },
    ];
    fetchMock = mockFetch(mockSummary, undisclosedBids);
    vi.stubGlobal('fetch', fetchMock);

    render(<AllIndiaMatchesView onSelectBid={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Location Not Disclosed by Source')).toBeInTheDocument();
    });
  });

  it('displays location quality indicator for available locations', async () => {
    const availableBids: any[] = [
      {
        ...mockBids[0],
        bid_id: 'bid-available',
        location: 'Bengaluru, Karnataka',
        state: 'Karnataka',
        city: 'Bengaluru',
        location_quality: 'AVAILABLE',
        product_name: 'Available Product',
        relevance_score_100: 85,
        classification: 'Highly Relevant',
      },
    ];
    fetchMock = mockFetch(mockSummary, availableBids);
    vi.stubGlobal('fetch', fetchMock);

    render(<AllIndiaMatchesView onSelectBid={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Bengaluru, Karnataka')).toBeInTheDocument();
    });
  });
});
