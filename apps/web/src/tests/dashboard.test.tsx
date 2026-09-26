import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../context/AuthContext';
import { Dashboard } from '../pages/Dashboard';

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
const mockListConversations = vi.fn();

vi.mock('../lib/api', () => ({
  listPapers: () => mockListPapers(),
  listConversations: () => mockListConversations(),
}));

const PAPERS = [
  {
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
  },
  {
    id: 'paper-2',
    user_id: 'user-1',
    title: 'BERT: Pre-training of Deep Bidirectional Transformers',
    authors: ['J. Devlin'],
    abstract: null,
    publication_year: 2018,
    file_path: 'user-1/paper-2.pdf',
    file_size: 3_000_000,
    total_pages: 16,
    status: 'ready' as const,
    error_message: null,
    created_at: '2026-09-19T00:00:00.000Z',
    updated_at: '2026-09-19T00:00:00.000Z',
  },
];

const CONVERSATIONS = { conversations: [{ id: 'conv-1', user_id: 'user-1', title: 'Test Chat', created_at: '2026-09-20T00:00:00.000Z', updated_at: '2026-09-20T00:00:00.000Z' }], total: 1 };

function renderDashboard() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <Dashboard />
      </AuthProvider>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('Dashboard page', () => {
  it('shows loading state while fetching', async () => {
    mockListPapers.mockReturnValue(new Promise(() => {}));
    mockListConversations.mockReturnValue(new Promise(() => {}));
    renderDashboard();
    expect(screen.getByText('Research Workspace')).toBeTruthy();
  });

  it('renders paper and conversation counts from the API', async () => {
    mockListPapers.mockResolvedValue({ papers: PAPERS, total: 2 });
    mockListConversations.mockResolvedValue(CONVERSATIONS);
    renderDashboard();
    await waitFor(() => expect(screen.getByText('Papers Indexed')).toBeTruthy());
    expect(screen.getByText('Chat Sessions')).toBeTruthy();
    expect(screen.getByText('Ready for Synthesis')).toBeTruthy();
  });

  it('shows empty state when no papers exist', async () => {
    mockListPapers.mockResolvedValue({ papers: [], total: 0 });
    mockListConversations.mockResolvedValue({ conversations: [], total: 0 });
    renderDashboard();
    await waitFor(() => expect(screen.getByText(/no papers yet/i)).toBeTruthy());
  });

  it('renders recent papers', async () => {
    mockListPapers.mockResolvedValue({ papers: PAPERS, total: 2 });
    mockListConversations.mockResolvedValue(CONVERSATIONS);
    renderDashboard();
    await waitFor(() => expect(screen.getByText('Attention Is All You Need')).toBeTruthy());
    expect(screen.getByText('BERT: Pre-training of Deep Bidirectional Transformers')).toBeTruthy();
  });

  it('displays ready count', async () => {
    mockListPapers.mockResolvedValue({ papers: PAPERS, total: 2 });
    mockListConversations.mockResolvedValue(CONVERSATIONS);
    renderDashboard();
    await waitFor(() => expect(screen.getAllByText('Ready').length).toBe(2));
  });

  it('has upload button linking to papers page', async () => {
    mockListPapers.mockResolvedValue({ papers: [], total: 0 });
    mockListConversations.mockResolvedValue({ conversations: [], total: 0 });
    renderDashboard();
    await waitFor(() => expect(screen.getByText('Upload Research Paper')).toBeTruthy());
  });
});