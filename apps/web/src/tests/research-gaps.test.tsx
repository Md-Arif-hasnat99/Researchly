import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../context/AuthContext';
import { ResearchGaps } from '../pages/ResearchGaps';
import type { PaperStatus } from '../types/paper';

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

const mockListPapers = vi.fn();
const mockIdentify = vi.fn();

vi.mock('../lib/api', () => ({
  listPapers: () => mockListPapers(),
  identifyResearchGaps: (req: unknown) => mockIdentify(req),
}));

function makePaper(id: string, title: string, year: number, status: PaperStatus = 'ready') {
  return {
    id,
    user_id: 'u1',
    title,
    authors: [],
    abstract: null,
    publication_year: year,
    file_path: `u1/${id}.pdf`,
    file_size: 1_000_000,
    total_pages: 12,
    status,
    error_message: null,
    created_at: '2026-09-20T00:00:00.000Z',
    updated_at: '2026-09-20T00:00:00.000Z',
  };
}

const PAPERS = [
  makePaper('p1', 'Attention Is All You Need', 2017),
  makePaper('p2', 'Retrieval-Augmented Generation', 2020),
  makePaper('p3', 'Still Indexing', 2021, 'processing'),
];

const RESULT = {
  papers: [
    { paper_id: 'p1', paper_title: 'Attention Is All You Need', publication_year: 2017 },
    { paper_id: 'p2', paper_title: 'Retrieval-Augmented Generation', publication_year: 2020 },
  ],
  clusters: [
    {
      category: 'Limitation' as const,
      gaps: [
        {
          title: 'Quadratic attention cost',
          category: 'Limitation' as const,
          description: 'Self-attention scales quadratically with sequence length.',
          evidence: 'The authors state computation grows quickly with input length.',
          suggested_direction: 'Investigate sparse or linear attention approximations.',
          paper_ids: ['p1', 'p2'],
          citations: [
            {
              paper_id: 'p1',
              paper_title: 'Attention Is All You Need',
              page_number: 6,
              chunk_id: 'c1',
            },
            {
              paper_id: 'p2',
              paper_title: 'Retrieval-Augmented Generation',
              page_number: 8,
              chunk_id: 'c2',
            },
          ],
          recurrence: 2,
        },
      ],
    },
    {
      category: 'Future Work' as const,
      gaps: [
        {
          title: 'No robustness evaluation',
          category: 'Future Work' as const,
          description: 'Robustness to distribution shift is untested.',
          evidence: '',
          suggested_direction: 'Benchmark under domain shift.',
          paper_ids: ['p1'],
          citations: [
            {
              paper_id: 'p1',
              paper_title: 'Attention Is All You Need',
              page_number: 9,
              chunk_id: 'c3',
            },
          ],
          recurrence: 1,
        },
      ],
    },
  ],
  summary: 'Both papers flag compute cost as a shared limitation.',
  citations: ['c1', 'c2', 'c3'],
};

const EMPTY_RESULT = {
  papers: [{ paper_id: 'p1', paper_title: 'Attention Is All You Need', publication_year: 2017 }],
  clusters: [],
  summary: 'No gaps found.',
  citations: [],
};

function renderPage() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <ResearchGaps />
      </AuthProvider>
    </MemoryRouter>
  );
}

function selectPapers(...ids: string[]) {
  for (const id of ids) {
    fireEvent.click(screen.getByTestId(`gap-paper-${id}`));
  }
}

const analyzeBtn = () => screen.getByRole('button', { name: /extract gaps|re-analyse/i });

beforeEach(() => {
  vi.clearAllMocks();
  mockListPapers.mockResolvedValue({ papers: PAPERS, total: 3 });
  mockIdentify.mockResolvedValue(RESULT);
});

describe('ResearchGaps page', () => {
  it('renders the page heading', () => {
    renderPage();
    expect(screen.getByText('Research Gaps & Future Directions')).toBeTruthy();
  });

  it('lists only ready papers and notes the rest are processing', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('gap-paper-p1')).toBeTruthy());
    expect(screen.queryByTestId('gap-paper-p3')).toBeNull();
    expect(screen.getByText(/1 paper is still processing/i)).toBeTruthy();
  });

  it('allows analysis with a single paper', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('gap-paper-p1')).toBeTruthy());
    expect((analyzeBtn() as HTMLButtonElement).disabled).toBe(true);
    selectPapers('p1');
    expect((analyzeBtn() as HTMLButtonElement).disabled).toBe(false);
  });

  it('labels results as AI-generated observations (FR-13)', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('gap-paper-p1')).toBeTruthy());
    selectPapers('p1');
    fireEvent.click(analyzeBtn());

    await waitFor(() => expect(screen.getByText(/AI-generated observations/i)).toBeTruthy());
  });

  it('groups gaps by category', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('gap-paper-p1')).toBeTruthy());
    selectPapers('p1');
    fireEvent.click(analyzeBtn());

    await waitFor(() => expect(screen.getByText(/2 gaps across 2 categories/)).toBeTruthy());
    // Two category clusters rendered, one per non-empty category.
    expect(screen.getByTestId('gap-category-Limitation')).toBeTruthy();
    expect(screen.getByTestId('gap-card-Quadratic attention cost')).toBeTruthy();
    expect(screen.getByTestId('gap-card-No robustness evaluation')).toBeTruthy();
  });

  it('highlights gaps that recur across papers', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('gap-paper-p1')).toBeTruthy());
    selectPapers('p1');
    fireEvent.click(analyzeBtn());

    await waitFor(() =>
      expect(screen.getByTestId('recurrence-Quadratic attention cost')).toBeTruthy()
    );
    expect(screen.getByText('Raised in 2 papers')).toBeTruthy();
  });

  it('separates stated evidence from AI inference', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('gap-paper-p1')).toBeTruthy());
    selectPapers('p1');
    fireEvent.click(analyzeBtn());

    await waitFor(() => expect(screen.getByText(/From the papers:/)).toBeTruthy());
    // Every gap carries an explicitly AI-labelled suggested direction.
    expect(screen.getAllByText(/Suggested research direction \(AI\)/).length).toBe(2);
  });

  it('renders per-gap source attribution', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('gap-paper-p1')).toBeTruthy());
    selectPapers('p1');
    fireEvent.click(analyzeBtn());

    await waitFor(() => expect(screen.getByText(/Attention Is All You Need · p\.6/)).toBeTruthy());
    expect(screen.getByText(/Retrieval-Augmented Generation · p\.8/)).toBeTruthy();
  });

  it('sends selected ids with no categories when none are chosen', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('gap-paper-p1')).toBeTruthy());
    selectPapers('p1', 'p2');
    fireEvent.click(analyzeBtn());

    await waitFor(() => expect(mockIdentify).toHaveBeenCalledTimes(1));
    expect(mockIdentify).toHaveBeenCalledWith({ paper_ids: ['p1', 'p2'] });
  });

  it('sends only the chosen categories', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('gap-paper-p1')).toBeTruthy());
    selectPapers('p1');
    fireEvent.click(screen.getByTestId('gap-category-Future Work'));
    fireEvent.click(screen.getByTestId('gap-category-Dataset Limitation'));
    fireEvent.click(analyzeBtn());

    await waitFor(() => expect(mockIdentify).toHaveBeenCalledTimes(1));
    expect(mockIdentify).toHaveBeenCalledWith({
      paper_ids: ['p1'],
      categories: ['Future Work', 'Dataset Limitation'],
    });
  });

  it('sends the optional focus', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('gap-paper-p1')).toBeTruthy());
    selectPapers('p1');
    fireEvent.change(screen.getByLabelText(/focus/i), {
      target: { value: 'reproducibility' },
    });
    fireEvent.click(analyzeBtn());

    await waitFor(() => expect(mockIdentify).toHaveBeenCalledTimes(1));
    expect(mockIdentify).toHaveBeenCalledWith({
      paper_ids: ['p1'],
      focus: 'reproducibility',
    });
  });

  it('deselecting a category removes it from the request', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('gap-paper-p1')).toBeTruthy());
    selectPapers('p1');
    const chip = screen.getByTestId('gap-category-Limitation');
    fireEvent.click(chip);
    expect(chip.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(chip);
    expect(chip.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(analyzeBtn());

    await waitFor(() => expect(mockIdentify).toHaveBeenCalledTimes(1));
    expect(mockIdentify).toHaveBeenCalledWith({ paper_ids: ['p1'] });
  });

  it('surfaces API errors instead of rendering gaps', async () => {
    mockIdentify.mockRejectedValue(new Error('No indexed content was found.'));
    renderPage();
    await waitFor(() => expect(screen.getByTestId('gap-paper-p1')).toBeTruthy());
    selectPapers('p1');
    fireEvent.click(analyzeBtn());

    await waitFor(() => expect(screen.getByText('No indexed content was found.')).toBeTruthy());
    expect(screen.queryByText('Overview')).toBeNull();
  });

  it('explains an empty result rather than showing a blank page', async () => {
    mockIdentify.mockResolvedValue(EMPTY_RESULT);
    renderPage();
    await waitFor(() => expect(screen.getByTestId('gap-paper-p1')).toBeTruthy());
    selectPapers('p1');
    fireEvent.click(analyzeBtn());

    await waitFor(() => expect(screen.getByText('No gaps identified')).toBeTruthy());
    expect(screen.getByText(/did not contain enough acknowledged limitations/i)).toBeTruthy();
  });

  it('offers export only after a result exists', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('gap-paper-p1')).toBeTruthy());
    expect(screen.queryByRole('button', { name: /export/i })).toBeNull();
    selectPapers('p1');
    fireEvent.click(analyzeBtn());
    await waitFor(() =>
      expect(screen.getByTestId('gap-card-Quadratic attention cost')).toBeTruthy()
    );
    expect(screen.getByRole('button', { name: /export/i })).toBeTruthy();
  });

  it('clears results when the paper selection changes', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('gap-paper-p1')).toBeTruthy());
    selectPapers('p1');
    fireEvent.click(analyzeBtn());
    await waitFor(() =>
      expect(screen.getByTestId('gap-card-Quadratic attention cost')).toBeTruthy()
    );

    selectPapers('p2');
    expect(screen.queryByTestId('gap-card-Quadratic attention cost')).toBeNull();
  });

  it('shows an empty state when no papers are indexed', async () => {
    mockListPapers.mockResolvedValue({ papers: [], total: 0 });
    renderPage();
    await waitFor(() => expect(screen.getByText('No indexed papers')).toBeTruthy());
    expect(screen.getByRole('button', { name: /research library/i })).toBeTruthy();
  });
});
