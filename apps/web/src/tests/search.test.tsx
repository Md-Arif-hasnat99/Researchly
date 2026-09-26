import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../context/AuthContext';
import { Search } from '../pages/Search';
import type { SearchResponse } from '../types/search';

vi.mock('../lib/supabase', () => ({
  supabase: {
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: null } }),
      onAuthStateChange: vi.fn().mockReturnValue({
        data: { subscription: { unsubscribe: vi.fn() } },
      }),
    },
  },
}));

const mockSearch = vi.fn();

vi.mock('../lib/api', () => ({
  searchPapers: (req: unknown) => mockSearch(req),
}));

function makeResult(overrides: Partial<SearchResponse> = {}): SearchResponse {
  return {
    query: 'ImageNet',
    mode: 'hybrid',
    total_results: 2,
    results: [
      {
        chunk_id: 'c1',
        paper_id: 'p1',
        paper_title: 'Attention Is All You Need',
        page_number: 7,
        section: 'Experiments',
        content: 'We evaluate on ImageNet using the standard split.',
        similarity_score: 0.82,
        matched_by: ['vector', 'keyword'],
        fusion_score: 0.032,
      },
      {
        chunk_id: 'c2',
        paper_id: 'p2',
        paper_title: 'Retrieval-Augmented Generation',
        page_number: 3,
        section: 'Dataset',
        content: 'The ImageNet corpus contains 1.2M images.',
        // Keyword-only: rescued by lexical match, no vector score exists.
        similarity_score: null,
        matched_by: ['keyword'],
        fusion_score: 0.016,
      },
    ],
    ...overrides,
  };
}

function renderPage(initialEntry = '/search') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <AuthProvider>
        <Search />
      </AuthProvider>
    </MemoryRouter>
  );
}

const input = () => screen.getByTestId('search-input') as HTMLInputElement;
const searchBtn = () => screen.getByRole('button', { name: /^search$/i }) as HTMLButtonElement;

async function submitQuery(q: string) {
  fireEvent.change(input(), { target: { value: q } });
  fireEvent.click(searchBtn());
}

beforeEach(() => {
  vi.clearAllMocks();
  mockSearch.mockResolvedValue(makeResult());
});

describe('Search page', () => {
  it('defaults to hybrid retrieval', () => {
    renderPage();
    expect(screen.getByTestId('search-mode-hybrid').getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByText(/combines meaning and exact wording/i)).toBeTruthy();
  });

  it('sends the chosen mode with the query', async () => {
    renderPage();
    fireEvent.click(screen.getByTestId('search-mode-keyword'));
    await submitQuery('ImageNet');

    await waitFor(() => expect(mockSearch).toHaveBeenCalled());
    expect(mockSearch.mock.calls[0][0]).toMatchObject({ query: 'ImageNet', mode: 'keyword' });
  });

  it('updates the hint when the mode changes', () => {
    renderPage();
    fireEvent.click(screen.getByTestId('search-mode-vector'));
    expect(screen.getByText(/meaning only/i)).toBeTruthy();
    fireEvent.click(screen.getByTestId('search-mode-keyword'));
    expect(screen.getByText(/literal text match/i)).toBeTruthy();
  });

  it('disables search until a query is entered', () => {
    renderPage();
    expect(searchBtn().disabled).toBe(true);
    fireEvent.change(input(), { target: { value: '   ' } });
    expect(searchBtn().disabled).toBe(true);
    fireEvent.change(input(), { target: { value: 'neural' } });
    expect(searchBtn().disabled).toBe(false);
  });

  it('does not issue a request for a whitespace-only query', async () => {
    renderPage();
    fireEvent.change(input(), { target: { value: '  ' } });
    expect(mockSearch).not.toHaveBeenCalled();
  });

  it('runs a query handed over in the URL', async () => {
    // The header search box hands its query to /search?q=...
    renderPage('/search?q=ImageNet');

    await waitFor(() => expect(mockSearch).toHaveBeenCalled());
    expect(mockSearch.mock.calls[0][0]).toMatchObject({ query: 'ImageNet' });
    expect(input().value).toBe('ImageNet');
  });

  it('sends only one request when a submitted query also rewrites the URL', async () => {
    renderPage();
    await submitQuery('ImageNet');

    await waitFor(() => expect(screen.getByText('2 results')).toBeTruthy());
    expect(mockSearch).toHaveBeenCalledTimes(1);
  });

  it('labels each result with the retrievers that found it', async () => {
    renderPage();
    await submitQuery('ImageNet');

    await waitFor(() => expect(screen.getByTestId('search-result-c1')).toBeTruthy());
    // Found by both retrievers.
    expect(
      within(screen.getByTestId('search-result-c1')).getByTestId('match-semantic')
    ).toBeTruthy();
    expect(
      within(screen.getByTestId('search-result-c1')).getByTestId('match-keyword')
    ).toBeTruthy();
    // Keyword-only: no "meaning" badge.
    const keywordOnly = screen.getByTestId('search-result-c2');
    expect(within(keywordOnly).getByTestId('match-keyword')).toBeTruthy();
    expect(within(keywordOnly).queryByTestId('match-semantic')).toBeNull();
  });

  it('shows a semantic percentage only when a vector score exists', async () => {
    renderPage();
    await submitQuery('ImageNet');

    await waitFor(() => expect(screen.getByTestId('search-result-c1')).toBeTruthy());
    expect(screen.getByText('82% semantic match')).toBeTruthy();
    // A keyword-only hit has no cosine similarity; saying "0% similar"
    // would be a false claim about a score that was never computed.
    expect(screen.getByTestId('no-similarity-score')).toBeTruthy();
    expect(screen.getByText(/surfaced by keyword search only/i)).toBeTruthy();
  });

  it('never presents a fusion score as a similarity percentage', async () => {
    renderPage();
    await submitQuery('ImageNet');

    await waitFor(() => expect(screen.getByTestId('search-result-c1')).toBeTruthy());
    // fusion_score 0.032 must not surface as "3% similar"
    expect(screen.queryByText(/3% semantic match/i)).toBeNull();
  });

  it('reports when hybrid search fell back to semantic only', async () => {
    mockSearch.mockResolvedValue(makeResult({ mode: 'vector' }));
    renderPage();
    await submitQuery('ImageNet');

    await waitFor(() => expect(screen.getByTestId('degraded-notice')).toBeTruthy());
    expect(screen.getByText(/keyword search is unavailable/i)).toBeTruthy();
  });

  it('does not show the fallback notice for a deliberate semantic search', async () => {
    mockSearch.mockResolvedValue(makeResult({ mode: 'vector' }));
    renderPage();
    fireEvent.click(screen.getByTestId('search-mode-vector'));
    await submitQuery('ImageNet');

    await waitFor(() => expect(screen.getByText('2 results')).toBeTruthy());
    // mode=vector was asked for, so nothing degraded.
    expect(screen.queryByTestId('degraded-notice')).toBeNull();
  });

  it('reports which retriever answered', async () => {
    renderPage();
    await submitQuery('ImageNet');

    await waitFor(() => expect(screen.getByText(/hybrid \(meaning \+ exact terms\)/i)).toBeTruthy());
  });

  it('explains an empty result set', async () => {
    mockSearch.mockResolvedValue({ query: 'nothing', mode: 'hybrid', results: [], total_results: 0 });
    renderPage();
    await submitQuery('nothing');

    await waitFor(() => expect(screen.getByText('No matches')).toBeTruthy());
    expect(screen.getByText(/switch to semantic mode/i)).toBeTruthy();
  });

  it('surfaces an API error', async () => {
    mockSearch.mockRejectedValue(new Error('Search failed. Please try again.'));
    renderPage();
    await submitQuery('ImageNet');

    await waitFor(() => expect(screen.getByText('Search failed. Please try again.')).toBeTruthy());
  });
});
