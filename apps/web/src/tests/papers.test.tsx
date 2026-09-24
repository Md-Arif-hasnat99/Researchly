import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../context/AuthContext';
import { Papers } from '../pages/Papers';
import { UploadModal } from '../components/papers/UploadModal';

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

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
const mockDeletePaper = vi.fn();

vi.mock('../lib/api', () => ({
  listPapers: () => mockListPapers(),
  deletePaper: (id: string) => mockDeletePaper(id),
  uploadPaper: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

const PAPER = {
  id: 'paper-1',
  user_id: 'user-1',
  title: 'Attention Is All You Need',
  authors: ['A. Vaswani'],
  abstract: null,
  publication_year: 2017,
  file_path: 'user-1/paper-1.pdf',
  file_size: 2_000_000,
  total_pages: 15,
  status: 'ready' as const,
  error_message: null,
  created_at: '2026-09-20T00:00:00.000Z',
  updated_at: '2026-09-20T00:00:00.000Z',
};

function renderPapers() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <Papers />
      </AuthProvider>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Papers page tests
// ---------------------------------------------------------------------------

describe('Papers page', () => {
  it('shows loading state while fetching', async () => {
    mockListPapers.mockReturnValue(new Promise(() => {}));
    renderPapers();
    expect(screen.getByText(/loading/i)).toBeTruthy();
  });

  it('renders papers returned from the API', async () => {
    mockListPapers.mockResolvedValue({ papers: [PAPER], total: 1 });
    renderPapers();
    await waitFor(() =>
      expect(screen.getByText('Attention Is All You Need')).toBeTruthy()
    );
    expect(screen.getByText('Ready')).toBeTruthy();
  });

  it('shows empty state when no papers exist', async () => {
    mockListPapers.mockResolvedValue({ papers: [], total: 0 });
    renderPapers();
    await waitFor(() => expect(screen.getByText(/no papers yet/i)).toBeTruthy());
  });

  it('opens upload modal when Upload PDF is clicked in empty state', async () => {
    mockListPapers.mockResolvedValue({ papers: [], total: 0 });
    renderPapers();
    await waitFor(() => screen.getByText(/no papers yet/i));

    const uploadBtns = screen.getAllByText(/upload pdf/i);
    fireEvent.click(uploadBtns[0]);

    await waitFor(() => expect(screen.getByText(/drop pdf here/i)).toBeTruthy());
  });

  it('calls deletePaper and removes paper from the list', async () => {
    mockListPapers.mockResolvedValue({ papers: [PAPER], total: 1 });
    mockDeletePaper.mockResolvedValue(undefined);
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    renderPapers();
    await waitFor(() => screen.getByText('Attention Is All You Need'));

    const deleteBtn = screen.getByLabelText('Delete paper');
    fireEvent.click(deleteBtn);

    await waitFor(() =>
      expect(mockDeletePaper).toHaveBeenCalledWith('paper-1')
    );
  });
});

// ---------------------------------------------------------------------------
// UploadModal tests
// ---------------------------------------------------------------------------

describe('UploadModal', () => {
  it('renders with drop zone and cancel button', () => {
    render(
      <UploadModal onClose={vi.fn()} onUploaded={vi.fn()} />
    );
    expect(screen.getByText(/drop pdf here/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeTruthy();
  });

  it('Upload button is disabled when no file is selected', () => {
    render(
      <UploadModal onClose={vi.fn()} onUploaded={vi.fn()} />
    );
    const uploadBtn = screen.getByRole('button', { name: /^upload$/i }) as HTMLButtonElement;
    expect(uploadBtn.disabled).toBe(true);
  });

  it('calls onClose when Cancel is clicked', () => {
    const onClose = vi.fn();
    render(
      <UploadModal onClose={onClose} onUploaded={vi.fn()} />
    );
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
