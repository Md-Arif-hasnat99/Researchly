import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../context/AuthContext';
import { Chat } from '../pages/Chat';

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

const mockListConversations = vi.fn();
const mockStreamQuestion = vi.fn();
const mockListPapers = vi.fn();

vi.mock('../lib/api', () => ({
  listConversations: () => mockListConversations(),
  getConversation: vi.fn(),
  deleteConversation: vi.fn(),
  // The chat page streams; the mock replays the handlers the real client
  // would fire, so the streaming code path is what the tests exercise.
  streamQuestion: (
    q: string,
    c?: string,
    p?: string[],
    r?: boolean,
    handlers?: {
      onToken?: (t: string) => void;
      onCitations?: (cit: unknown[]) => void;
    },
  ) => mockStreamQuestion(q, c, p, r, handlers),
  listPapers: () => mockListPapers(),
}));

const PAPERS = [
  {
    id: 'p1',
    user_id: 'u1',
    title: 'Attention Is All You Need',
    authors: [],
    abstract: null,
    publication_year: 2017,
    file_path: 'u1/p1.pdf',
    file_size: 1,
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
    authors: [],
    abstract: null,
    publication_year: 2020,
    file_path: 'u1/p2.pdf',
    file_size: 1,
    total_pages: 16,
    status: 'ready' as const,
    error_message: null,
    created_at: '2026-09-20T00:00:00.000Z',
    updated_at: '2026-09-20T00:00:00.000Z',
  },
];

const ANSWER = {
  message_id: 'm1',
  conversation_id: 'c1',
  answer: 'Because one uses retrieval.',
  citations: [],
  reranked: false,
};

function renderChat() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <Chat />
      </AuthProvider>
    </MemoryRouter>
  );
}

async function send(query: string) {
  const input = screen.getByPlaceholderText(/ask a question/i) as HTMLInputElement;
  fireEvent.change(input, { target: { value: query } });
  fireEvent.submit(input.closest('form') as HTMLFormElement);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockListConversations.mockResolvedValue({ conversations: [], total: 0 });
  mockListPapers.mockResolvedValue({ papers: PAPERS, total: 2 });
  // Replays the handlers the real stream client fires, so the page's
  // streaming path is what gets exercised rather than a bare resolve.
  mockStreamQuestion.mockImplementation(
    async (
      _q: string,
      _c: string | undefined,
      _p: string[] | undefined,
      _r: boolean | undefined,
      handlers?: {
        onToken?: (t: string) => void;
        onCitations?: (cit: unknown[]) => void;
      },
    ) => {
      handlers?.onCitations?.(ANSWER.citations);
      handlers?.onToken?.(ANSWER.answer);
      return ANSWER;
    },
  );
});

describe('Chat multi-paper scoping', () => {
  it('sends an empty scope by default, which the API layer omits', async () => {
    renderChat();
    await waitFor(() => expect(mockListPapers).toHaveBeenCalled());
    await send('What is attention?');

    await waitFor(() => expect(mockStreamQuestion).toHaveBeenCalled());
    // An empty scope means "search everything"; askQuestion drops it from the
    // request body, so the backend applies its default retrieval scope.
    expect(mockStreamQuestion.mock.calls[0][2]).toEqual([]);
  });

  it('hides the scope selector when no paper is ready', async () => {
    mockListPapers.mockResolvedValue({ papers: [], total: 0 });
    renderChat();
    await waitFor(() => expect(mockListPapers).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: /scope question/i })).toBeNull();
  });

  it('opens the paper list and scopes the query to checked papers', async () => {
    renderChat();
    await waitFor(() => expect(mockListPapers).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('button', { name: /scope question/i }));
    fireEvent.click(screen.getByTestId('chat-scope-p1'));
    fireEvent.click(screen.getByTestId('chat-scope-p2'));

    await send('Compare their methods');

    await waitFor(() => expect(mockStreamQuestion).toHaveBeenCalled());
    expect(mockStreamQuestion.mock.calls[0][2]).toEqual(['p1', 'p2']);
  });

  it('scopes to a single paper when only one is checked', async () => {
    renderChat();
    await waitFor(() => expect(mockListPapers).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('button', { name: /scope question/i }));
    fireEvent.click(screen.getByTestId('chat-scope-p2'));

    await send('What is the retriever?');

    await waitFor(() => expect(mockStreamQuestion).toHaveBeenCalled());
    expect(mockStreamQuestion.mock.calls[0][2]).toEqual(['p2']);
  });

  it('clears the scope when a selected paper chip is removed', async () => {
    renderChat();
    await waitFor(() => expect(mockListPapers).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('button', { name: /scope question/i }));
    fireEvent.click(screen.getByTestId('chat-scope-p1'));
    fireEvent.click(screen.getByTestId('chat-scope-p2'));

    // Chips reflect the current selection.
    const removeChip = screen.getByLabelText(/remove Attention Is All You Need from scope/i);
    fireEvent.click(removeChip);

    await send('Compare their methods');

    await waitFor(() => expect(mockStreamQuestion).toHaveBeenCalled());
    expect(mockStreamQuestion.mock.calls[0][2]).toEqual(['p2']);
  });
});

describe('Chat reranking', () => {
  it('leaves reranking off by default', async () => {
    renderChat();
    await waitFor(() => expect(mockListPapers).toHaveBeenCalled());
    await send('What is attention?');

    await waitFor(() => expect(mockStreamQuestion).toHaveBeenCalled());
    // A rerank costs an extra model round-trip on every turn, so it is
    // never paid for without being asked for.
    expect(mockStreamQuestion.mock.calls[0][3]).toBe(false);
    expect((screen.getByTestId('chat-rerank-toggle') as HTMLInputElement).checked).toBe(false);
  });

  it('sends the rerank choice once the toggle is switched on', async () => {
    renderChat();
    await waitFor(() => expect(mockListPapers).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId('chat-rerank-toggle'));
    await send('What is attention?');

    await waitFor(() => expect(mockStreamQuestion).toHaveBeenCalled());
    expect(mockStreamQuestion.mock.calls[0][3]).toBe(true);
  });

  it('says so when the answer was built from reranked sources', async () => {
    mockStreamQuestion.mockImplementation(async (_q, _c, _p, _r, handlers) => { handlers?.onCitations?.(ANSWER.citations); handlers?.onToken?.(ANSWER.answer); return { ...ANSWER, reranked: true }; });
    renderChat();
    await waitFor(() => expect(mockListPapers).toHaveBeenCalled());
    await send('What is attention?');

    await waitFor(() => expect(screen.getByTestId('message-reranked')).toBeTruthy());
  });

  it('makes no rerank claim when the reranker fell back', async () => {
    renderChat();
    await waitFor(() => expect(mockListPapers).toHaveBeenCalled());
    await send('What is attention?');

    await waitFor(() => expect(screen.getByText('Because one uses retrieval.')).toBeTruthy());
    expect(screen.queryByTestId('message-reranked')).toBeNull();
  });
});
