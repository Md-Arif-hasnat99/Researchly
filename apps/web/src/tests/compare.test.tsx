import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../context/AuthContext';
import { Compare } from '../pages/Compare';

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
const mockComparePapers = vi.fn();

vi.mock('../lib/api', () => ({
  listPapers: () => mockListPapers(),
  comparePapers: (req: unknown) => mockComparePapers(req),
}));

const PAPERS = [
  {
    id: 'p1',
    user_id: 'u1',
    title: 'Attention Is All You Need',
    authors: ['A. Vaswani'],
    abstract: null,
    publication_year: 2017,
    file_path: 'u1/p1.pdf',
    file_size: 2_000_000,
    total_pages: 15,
    status: 'ready' as const,
    error_message: null,
    created_at: '2026-09-20T00:00:00.000Z',
    updated_at: '2026-09-20T00:00:00.000Z',
  },
  {
    id: 'p2',
    user_id: 'u1',
    title: 'Retrieval-Augmented Generation',
    authors: ['P. Lewis'],
    abstract: null,
    publication_year: 2020,
    file_path: 'u1/p2.pdf',
    file_size: 3_000_000,
    total_pages: 16,
    status: 'ready' as const,
    error_message: null,
    created_at: '2026-09-19T00:00:00.000Z',
    updated_at: '2026-09-19T00:00:00.000Z',
  },
  {
    id: 'p3',
    user_id: 'u1',
    title: 'Still Indexing Paper',
    authors: ['Someone'],
    abstract: null,
    publication_year: 2021,
    file_path: 'u1/p3.pdf',
    file_size: 1_000_000,
    total_pages: null,
    status: 'processing' as const,
    error_message: null,
    created_at: '2026-09-18T00:00:00.000Z',
    updated_at: '2026-09-18T00:00:00.000Z',
  },
];

const RESULT = {
  papers: [
    { paper_id: 'p1', paper_title: 'Attention Is All You Need', publication_year: 2017 },
    { paper_id: 'p2', paper_title: 'Retrieval-Augmented Generation', publication_year: 2020 },
  ],
  rows: [
    {
      aspect: 'Dataset',
      cells: [
        {
          paper_id: 'p1',
          paper_title: 'Attention Is All You Need',
          summary: 'WMT 2014 EN-DE.',
          page_number: 7,
          chunk_id: 'c1',
          not_reported: false,
        },
        {
          paper_id: 'p2',
          paper_title: 'Retrieval-Augmented Generation',
          summary: 'Natural Questions, TriviaQA.',
          page_number: 3,
          chunk_id: 'c2',
          not_reported: false,
        },
      ],
    },
    {
      aspect: 'Limitations',
      cells: [
        {
          paper_id: 'p1',
          paper_title: 'Attention Is All You Need',
          summary: 'Quadratic cost in length.',
          page_number: 11,
          chunk_id: 'c3',
          not_reported: false,
        },
        {
          paper_id: 'p2',
          paper_title: 'Retrieval-Augmented Generation',
          summary: '',
          page_number: null,
          chunk_id: null,
          not_reported: true,
        },
      ],
    },
  ],
  summary: 'The RAG paper grounds a retriever; the Transformer does not.',
  citations: ['c1', 'c2', 'c3'],
};

function renderCompare() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <Compare />
      </AuthProvider>
    </MemoryRouter>
  );
}

/** Select papers by clicking their picker toggles. */
function selectPapers(...ids: string[]) {
  for (const id of ids) {
    fireEvent.click(screen.getByTestId(`compare-paper-${id}`));
  }
}

beforeEach(() => {
  vi.clearAllMocks();
  mockListPapers.mockResolvedValue({ papers: PAPERS, total: 3 });
  mockComparePapers.mockResolvedValue(RESULT);
});

describe('Compare page', () => {
  it('renders the page heading', () => {
    renderCompare();
    expect(screen.getByText('Multi-Paper Comparative Synthesis')).toBeTruthy();
  });

  it('lists ready papers but hides non-ready ones from the picker', async () => {
    renderCompare();
    await waitFor(() => expect(screen.getByTestId('compare-paper-p1')).toBeTruthy());
    expect(screen.getByTestId('compare-paper-p2')).toBeTruthy();
    expect(screen.queryByTestId('compare-paper-p3')).toBeNull();
    expect(screen.getByText(/1 paper is still processing/i)).toBeTruthy();
  });

  it('disables compare until two papers are selected', async () => {
    renderCompare();
    await waitFor(() => expect(screen.getByTestId('compare-paper-p1')).toBeTruthy());
    const btn = screen.getByRole('button', { name: /compare/i });
    expect((btn as HTMLButtonElement).disabled).toBe(true);

    selectPapers('p1');
    expect((screen.getByRole('button', { name: /compare/i }) as HTMLButtonElement).disabled).toBe(
      true
    );

    selectPapers('p2');
    expect((screen.getByRole('button', { name: /compare/i }) as HTMLButtonElement).disabled).toBe(
      false
    );
  });

  it('renders the comparison matrix with page citations', async () => {
    renderCompare();
    await waitFor(() => expect(screen.getByTestId('compare-paper-p1')).toBeTruthy());
    selectPapers('p1', 'p2');
    fireEvent.click(screen.getByRole('button', { name: /^compare$/i }));

    await waitFor(() => expect(screen.getByText('Dataset')).toBeTruthy());
    expect(screen.getByText('WMT 2014 EN-DE.')).toBeTruthy();
    expect(screen.getByText('p.7')).toBeTruthy();
    expect(screen.getByText('Limitations')).toBeTruthy();
    expect(
      screen.getByText('The RAG paper grounds a retriever; the Transformer does not.')
    ).toBeTruthy();
  });

  it('marks missing cells as Not reported', async () => {
    renderCompare();
    await waitFor(() => expect(screen.getByTestId('compare-paper-p1')).toBeTruthy());
    selectPapers('p1', 'p2');
    fireEvent.click(screen.getByRole('button', { name: /^compare$/i }));

    await waitFor(() => expect(screen.getByText('Limitations')).toBeTruthy());
    expect(screen.getByText('Not reported')).toBeTruthy();
  });

  it('reports the grounded citation count', async () => {
    renderCompare();
    await waitFor(() => expect(screen.getByTestId('compare-paper-p1')).toBeTruthy());
    selectPapers('p1', 'p2');
    fireEvent.click(screen.getByRole('button', { name: /^compare$/i }));

    await waitFor(() => expect(screen.getByText(/3 source chunks grounded/i)).toBeTruthy());
  });

  it('sends the selected paper ids and optional focus to the API', async () => {
    renderCompare();
    await waitFor(() => expect(screen.getByTestId('compare-paper-p1')).toBeTruthy());
    selectPapers('p1', 'p2');
    fireEvent.change(screen.getByLabelText(/focus/i), {
      target: { value: 'Compare evaluation methodology' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^compare$/i }));

    await waitFor(() => expect(mockComparePapers).toHaveBeenCalledTimes(1));
    expect(mockComparePapers).toHaveBeenCalledWith({
      paper_ids: ['p1', 'p2'],
      focus: 'Compare evaluation methodology',
    });
  });

  it('omits focus from the request when left blank', async () => {
    renderCompare();
    await waitFor(() => expect(screen.getByTestId('compare-paper-p1')).toBeTruthy());
    selectPapers('p1', 'p2');
    fireEvent.click(screen.getByRole('button', { name: /^compare$/i }));

    await waitFor(() => expect(mockComparePapers).toHaveBeenCalledTimes(1));
    expect(mockComparePapers).toHaveBeenCalledWith({ paper_ids: ['p1', 'p2'] });
  });

  it('surfaces API errors instead of rendering a matrix', async () => {
    mockComparePapers.mockRejectedValue(new Error('At least 2 indexed papers are required.'));
    renderCompare();
    await waitFor(() => expect(screen.getByTestId('compare-paper-p1')).toBeTruthy());
    selectPapers('p1', 'p2');
    fireEvent.click(screen.getByRole('button', { name: /^compare$/i }));

    await waitFor(() =>
      expect(screen.getByText('At least 2 indexed papers are required.')).toBeTruthy()
    );
    expect(screen.queryByText('Dataset')).toBeNull();
  });

  it('deselects a paper when its chip is clicked again', async () => {
    renderCompare();
    await waitFor(() => expect(screen.getByTestId('compare-paper-p1')).toBeTruthy());
    selectPapers('p1');
    expect((screen.getByTestId('compare-paper-p1') as HTMLElement).getAttribute('aria-pressed')).toBe(
      'true'
    );
    selectPapers('p1');
    expect((screen.getByTestId('compare-paper-p1') as HTMLElement).getAttribute('aria-pressed')).toBe(
      'false'
    );
  });

  it('shows an empty state when no papers are indexed', async () => {
    mockListPapers.mockResolvedValue({ papers: [], total: 0 });
    renderCompare();
    await waitFor(() => expect(screen.getByText('No indexed papers')).toBeTruthy());
    expect(screen.getByRole('button', { name: /research library/i })).toBeTruthy();
  });

  it('prompts for a second paper when only one is ready', async () => {
    mockListPapers.mockResolvedValue({ papers: [PAPERS[0]], total: 1 });
    renderCompare();
    await waitFor(() => expect(screen.getByText('Pick at least two papers')).toBeTruthy());
  });

  it('offers export only once a matrix exists', async () => {
    renderCompare();
    await waitFor(() => expect(screen.getByTestId('compare-paper-p1')).toBeTruthy());
    expect(screen.queryByRole('button', { name: /export matrix/i })).toBeNull();
    selectPapers('p1', 'p2');
    fireEvent.click(screen.getByRole('button', { name: /^compare$/i }));
    await waitFor(() => expect(screen.getByText('Dataset')).toBeTruthy());
    expect(screen.getByRole('button', { name: /export matrix/i })).toBeTruthy();
  });
});
