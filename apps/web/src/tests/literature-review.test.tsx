import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../context/AuthContext';
import { LiteratureReview } from '../pages/LiteratureReview';

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
const mockGenerate = vi.fn();

vi.mock('../lib/api', () => ({
  listPapers: () => mockListPapers(),
  generateLiteratureReview: (req: unknown) => mockGenerate(req),
}));

import type { PaperStatus } from '../types/paper';

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

const REVIEW = {
  title: 'Attention and Retrieval in NLP',
  papers: [
    { paper_id: 'p1', paper_title: 'Attention Is All You Need', publication_year: 2017 },
    { paper_id: 'p2', paper_title: 'Retrieval-Augmented Generation', publication_year: 2020 },
  ],
  sections: [
    {
      heading: 'Introduction',
      content: 'Both papers frame sequence modelling around attention mechanisms.',
      citations: [
        {
          paper_id: 'p1',
          paper_title: 'Attention Is All You Need',
          page_number: 1,
          chunk_id: 'c1',
        },
        {
          paper_id: 'p2',
          paper_title: 'Retrieval-Augmented Generation',
          page_number: 2,
          chunk_id: 'c2',
        },
      ],
      insufficient_context: false,
    },
    {
      heading: 'Research Gaps',
      content: 'The retrieved context did not provide enough material.',
      citations: [],
      insufficient_context: true,
    },
  ],
  references: [
    { paper_id: 'p1', paper_title: 'Attention Is All You Need', publication_year: 2017 },
    { paper_id: 'p2', paper_title: 'Retrieval-Augmented Generation', publication_year: 2020 },
  ],
  citations: ['c1', 'c2'],
};

function renderPage() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <LiteratureReview />
      </AuthProvider>
    </MemoryRouter>
  );
}

function selectPapers(...ids: string[]) {
  for (const id of ids) {
    fireEvent.click(screen.getByTestId(`review-paper-${id}`));
  }
}

const generateBtn = () => screen.getByRole('button', { name: /generate review|regenerate/i });

beforeEach(() => {
  vi.clearAllMocks();
  mockListPapers.mockResolvedValue({ papers: PAPERS, total: 3 });
  mockGenerate.mockResolvedValue(REVIEW);
});

describe('LiteratureReview page', () => {
  it('renders the page heading', () => {
    renderPage();
    expect(screen.getByText('Literature Review Generator')).toBeTruthy();
  });

  it('lists only ready papers and notes the rest are processing', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('review-paper-p1')).toBeTruthy());
    expect(screen.getByTestId('review-paper-p2')).toBeTruthy();
    expect(screen.queryByTestId('review-paper-p3')).toBeNull();
    expect(screen.getByText(/1 paper is still processing/i)).toBeTruthy();
  });

  it('disables generate until two papers are selected', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('review-paper-p1')).toBeTruthy());
    expect((generateBtn() as HTMLButtonElement).disabled).toBe(true);

    selectPapers('p1');
    expect((generateBtn() as HTMLButtonElement).disabled).toBe(true);

    selectPapers('p2');
    expect((generateBtn() as HTMLButtonElement).disabled).toBe(false);
  });

  it('renders section content with per-section source citations', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('review-paper-p1')).toBeTruthy());
    selectPapers('p1', 'p2');
    fireEvent.click(generateBtn());

    await waitFor(() =>
      expect(
        screen.getByText('Both papers frame sequence modelling around attention mechanisms.')
      ).toBeTruthy()
    );
    expect(screen.getByText('1. Introduction')).toBeTruthy();
    expect(screen.getByText(/Attention Is All You Need · p\.1/)).toBeTruthy();
    expect(screen.getByText(/Retrieval-Augmented Generation · p\.2/)).toBeTruthy();
  });

  it('warns that the document is an AI synthesis, not paper findings', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('review-paper-p1')).toBeTruthy());
    selectPapers('p1', 'p2');
    fireEvent.click(generateBtn());

    await waitFor(() => expect(screen.getByText(/AI-generated synthesis/i)).toBeTruthy());
  });

  it('flags sections the context could not support', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('review-paper-p1')).toBeTruthy());
    selectPapers('p1', 'p2');
    fireEvent.click(generateBtn());

    await waitFor(() => expect(screen.getByText('2. Research Gaps')).toBeTruthy());
    expect(screen.getByText(/not enough retrieved context/i)).toBeTruthy();
  });

  it('reports how many sections were grounded', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('review-paper-p1')).toBeTruthy());
    selectPapers('p1', 'p2');
    fireEvent.click(generateBtn());

    await waitFor(() => expect(screen.getByText(/1 of 2 sections grounded/i)).toBeTruthy());
  });

  it('renders the references list', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('review-paper-p1')).toBeTruthy());
    selectPapers('p1', 'p2');
    fireEvent.click(generateBtn());

    await waitFor(() => expect(screen.getByText('References')).toBeTruthy());
  });

  it('sends selected ids and optional title and focus', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('review-paper-p1')).toBeTruthy());
    selectPapers('p1', 'p2');
    fireEvent.change(screen.getByLabelText(/title/i), {
      target: { value: 'My Review' },
    });
    fireEvent.change(screen.getByLabelText(/focus/i), {
      target: { value: 'Evaluation methodology' },
    });
    fireEvent.click(generateBtn());

    await waitFor(() => expect(mockGenerate).toHaveBeenCalledTimes(1));
    expect(mockGenerate).toHaveBeenCalledWith({
      paper_ids: ['p1', 'p2'],
      title: 'My Review',
      focus: 'Evaluation methodology',
    });
  });

  it('omits blank optional fields from the request', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('review-paper-p1')).toBeTruthy());
    selectPapers('p1', 'p2');
    fireEvent.click(generateBtn());

    await waitFor(() => expect(mockGenerate).toHaveBeenCalledTimes(1));
    expect(mockGenerate).toHaveBeenCalledWith({ paper_ids: ['p1', 'p2'] });
  });

  it('surfaces API errors instead of rendering a document', async () => {
    mockGenerate.mockRejectedValue(new Error('At least two indexed papers are required.'));
    renderPage();
    await waitFor(() => expect(screen.getByTestId('review-paper-p1')).toBeTruthy());
    selectPapers('p1', 'p2');
    fireEvent.click(generateBtn());

    await waitFor(() =>
      expect(screen.getByText('At least two indexed papers are required.')).toBeTruthy()
    );
    expect(screen.queryByText('References')).toBeNull();
  });

  it('regenerating keeps the previous document visible while loading fails', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('review-paper-p1')).toBeTruthy());
    selectPapers('p1', 'p2');
    fireEvent.click(generateBtn());
    await waitFor(() => expect(screen.getByText('References')).toBeTruthy());

    mockGenerate.mockRejectedValue(new Error('Generation failed.'));
    fireEvent.click(screen.getByRole('button', { name: /regenerate/i }));
    await waitFor(() => expect(screen.getByText('Generation failed.')).toBeTruthy());
    expect(screen.queryByText('References')).toBeNull();
  });

  it('offers copy and export only after a document exists', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('review-paper-p1')).toBeTruthy());
    expect(screen.queryByRole('button', { name: /copy markdown/i })).toBeNull();

    selectPapers('p1', 'p2');
    fireEvent.click(generateBtn());
    await waitFor(() => expect(screen.getByText('References')).toBeTruthy());
    expect(screen.getByRole('button', { name: /copy markdown/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /export/i })).toBeTruthy();
  });

  it('clears the document when a paper is deselected', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('review-paper-p1')).toBeTruthy());
    selectPapers('p1', 'p2');
    fireEvent.click(generateBtn());
    await waitFor(() => expect(screen.getByText('References')).toBeTruthy());

    selectPapers('p2');
    expect(screen.queryByText('References')).toBeNull();
  });

  it('shows an empty state when no papers are indexed', async () => {
    mockListPapers.mockResolvedValue({ papers: [], total: 0 });
    renderPage();
    await waitFor(() => expect(screen.getByText('No indexed papers')).toBeTruthy());
    expect(screen.getByRole('button', { name: /research library/i })).toBeTruthy();
  });

  it('prompts for a second paper when only one is ready', async () => {
    mockListPapers.mockResolvedValue({ papers: [PAPERS[0]], total: 1 });
    renderPage();
    await waitFor(() => expect(screen.getByText('Pick at least two papers')).toBeTruthy());
  });
});
