/**
 * Researchly API client.
 *
 * All requests attach the Supabase JWT from the current session so the
 * FastAPI backend can verify the caller's identity.
 */

import { supabase } from './supabase';
import type { Paper, PaperListResponse } from '../types/paper';
import type { ChatResponse, ConversationListResponse, ConversationDetail } from '../types/chat';

const API_BASE = import.meta.env.VITE_API_URL as string | undefined ?? 'http://localhost:8000/api';

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Error raised for any non-2xx response.
 *
 * `message` is always populated with something a user can be shown, and
 * the machine-readable fields are kept for code that needs to branch
 * (401 meaning the session expired, a 429 that should wait, a 500 that
 * can be retried). For 5xx responses the message carries the server's
 * `X-Request-ID`, so a user reporting a failure can quote an id that
 * leads straight to the stack trace in the logs.
 */
export class ApiError extends Error {
  status: number;
  code?: string;
  requestId?: string;
  /** Seconds the server asked the caller to wait, on a 429. */
  retryAfterSeconds?: number;

  constructor(
    message: string,
    status: number,
    code?: string,
    requestId?: string,
    retryAfterSeconds?: number,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

async function getAuthHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new Error('Not authenticated');
  return { Authorization: `Bearer ${token}` };
}

/**
 * Turn a non-2xx response into an {@link ApiError}.
 *
 * The API emits one error shape, {"error": {"code", "message"}};
 * "detail" is accepted as well so an older or third-party backend
 * still yields a readable message rather than a bare status text.
 */
async function toApiError(res: Response): Promise<ApiError> {
  let message = res.statusText || `Request failed with status ${res.status}`;
  let code: string | undefined;
  try {
    const body = (await res.json()) as {
      detail?: string;
      error?: { code?: string; message?: string };
    };
    message = body?.error?.message ?? body?.detail ?? message;
    code = body?.error?.code;
  } catch {
    // ignore JSON parse errors
  }
  const requestId = res.headers.get('x-request-id') ?? undefined;
  if (res.status >= 500 && requestId) {
    message = `${message} (ref: ${requestId})`;
  }
  // A throttled request carries how long to wait, so the UI can say
  // "try again in a moment" rather than showing a bare failure.
  const retryAfter = res.headers.get('retry-after');
  const retryAfterSeconds = retryAfter ? Number(retryAfter) : undefined;
  if (res.status === 429 && retryAfterSeconds !== undefined) {
    message = `${message} (try again in ${retryAfterSeconds}s)`;
  }
  return new ApiError(message, res.status, code, requestId, retryAfterSeconds);
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    throw await toApiError(res);
  }
  // 204 No Content
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Papers API
// ---------------------------------------------------------------------------

/**
 * Upload a PDF file. Returns the newly created Paper record.
 * Throws if the file is not a PDF, is over 50 MB, or the server returns an error.
 */
export async function uploadPaper(file: File): Promise<Paper> {
  const headers = await getAuthHeaders();
  const form = new FormData();
  form.append('file', file);

  const res = await fetch(`${API_BASE}/papers`, {
    method: 'POST',
    headers,   // Content-Type is set automatically by fetch for FormData
    body: form,
  });

  return handleResponse<Paper>(res);
}

/** Return all papers belonging to the authenticated user. */
export async function listPapers(): Promise<PaperListResponse> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_BASE}/papers`, { headers });
  return handleResponse<PaperListResponse>(res);
}

/** Return a single paper by ID. Throws 404 if not found / not owned. */
export async function getPaper(id: string): Promise<Paper> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_BASE}/papers/${id}`, { headers });
  return handleResponse<Paper>(res);
}

/** Delete a paper (and its storage object) by ID. */
export async function deletePaper(id: string): Promise<void> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_BASE}/papers/${id}`, {
    method: 'DELETE',
    headers,
  });
  return handleResponse<void>(res);
}

// ---------------------------------------------------------------------------
// Chat API
// ---------------------------------------------------------------------------

export async function askQuestion(
  query: string,
  conversation_id?: string,
  paper_ids?: string[],
  rerank?: boolean
): Promise<ChatResponse> {
  const headers = await getAuthHeaders();
  headers['Content-Type'] = 'application/json';
  const body: Record<string, string | number | string[] | boolean | undefined> = { query };
  if (conversation_id) body.conversation_id = conversation_id;
  if (paper_ids && paper_ids.length > 0) body.paper_ids = paper_ids;
  if (rerank !== undefined) body.rerank = rerank;

  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  return handleResponse<ChatResponse>(res);
}

// ---------------------------------------------------------------------------
// Chat API — streaming
// ---------------------------------------------------------------------------

/** Callbacks for {@link streamQuestion}, in the order the server emits them. */
export interface StreamHandlers {
  /** Sources the answer is being grounded in; sent before any text. */
  onCitations?: (citations: ChatResponse['citations']) => void;
  /** An increment of the answer. Called many times, in order. */
  onToken?: (text: string) => void;
  /** The answer is complete and persisted. */
  onDone?: (result: { message_id: string; reranked: boolean }) => void;
  /**
   * The stream failed. Thrown errors from pre-stream failures (auth, a 4xx,
   * a retrieval 503) arrive here too, as an {@link ApiError}.
   */
  onError?: (error: Error) => void;
}

/**
 * Ask a question and consume the answer as it is generated.
 *
 * Uses `fetch` + a reader rather than `EventSource`, because EventSource
 * cannot send an `Authorization` header, and this API requires one.
 *
 * The buffered endpoint is still there and is used as a fallback: this
 * returns the same answer, just earlier. Callers that do not pass
 * `handlers` get the complete answer resolved normally.
 */
export async function streamQuestion(
  query: string,
  conversation_id: string | undefined,
  paper_ids: string[] | undefined,
  rerank: boolean | undefined,
  handlers: StreamHandlers = {},
): Promise<ChatResponse> {
  const headers = await getAuthHeaders();
  headers['Content-Type'] = 'application/json';
  headers['Accept'] = 'text/event-stream';
  const body: Record<string, string | number | string[] | boolean | undefined> = { query };
  if (conversation_id) body.conversation_id = conversation_id;
  if (paper_ids && paper_ids.length > 0) body.paper_ids = paper_ids;
  if (rerank !== undefined) body.rerank = rerank;

  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });

  // A failure before the first byte is still a normal JSON error response
  // with a real status code, so it is handled exactly as elsewhere.
  if (!res.ok || !res.body) {
    const error = await toApiError(res);
    handlers.onError?.(error);
    throw error;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();

  let conversationId = conversation_id ?? '';
  let messageId = '';
  let wasReranked = false;
  let answer = '';
  let citations: ChatResponse['citations'] = [];

  // Events are separated by a blank line; a chunk can end mid-frame, so
  // the tail is carried over rather than parsed on every read.
  let buffer = '';
  // An in-band error event means the answer never came. Remember it and
  // raise it below: resolving here would leave the caller showing sources
  // with an empty answer and no explanation.
  let streamError: ApiError | null = null;
  const innerHandlers: StreamHandlers = {
    ...handlers,
    onError: (e) => {
      if (e instanceof ApiError) streamError = e;
      handlers.onError?.(e);
    },
  };
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let split: number;
      while ((split = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, split);
        buffer = buffer.slice(split + 2);
        dispatchFrame(frame, innerHandlers, (text) => {
          answer += text;
        }, (c) => { citations = c; }, (m, r) => {
          messageId = m;
          wasReranked = r;
        });
      }
    }
    if (streamError) throw streamError;
  } catch (err) {
    // A recorded in-band failure explains the outcome better than a
    // transport error that only finished it off.
    if (streamError) throw streamError;
    // The connection dropped mid-answer. Whatever arrived is kept, so the
    // user does not lose the partial response they were reading.
    const error = err instanceof Error ? err : new Error('Stream failed');
    handlers.onError?.(error);
    if (answer.length > 0) {
      return {
        conversation_id: conversationId,
        message_id: messageId,
        answer,
        citations,
        reranked: wasReranked,
      };
    }
    throw error;
  }

  return {
    conversation_id: conversationId,
    message_id: messageId,
    answer,
    citations,
    reranked: wasReranked,
  };
}

function dispatchFrame(
  frame: string,
  handlers: StreamHandlers,
  onText: (text: string) => void,
  onCitations: (citations: ChatResponse['citations']) => void,
  onDone: (messageId: string, reranked: boolean) => void,
): void {
  if (!frame.trim()) return;

  let event = 'message';
  const dataLines: string[] = [];
  for (const line of frame.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice(7).trim();
    else if (line.startsWith('data: ')) dataLines.push(line.slice(6));
  }
  if (dataLines.length === 0) return;

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(dataLines.join('\n'));
  } catch {
    return; // A partial or malformed frame is skipped, not fatal.
  }

  switch (event) {
    case 'citations':
      onCitations((payload.citations ?? []) as ChatResponse['citations']);
      handlers.onCitations?.((payload.citations ?? []) as ChatResponse['citations']);
      break;
    case 'token':
      onText(String(payload.text ?? ''));
      handlers.onToken?.(String(payload.text ?? ''));
      break;
    case 'done':
      onDone(String(payload.message_id ?? ''), Boolean(payload.reranked));
      handlers.onDone?.({
        message_id: String(payload.message_id ?? ''),
        reranked: Boolean(payload.reranked),
      });
      break;
    case 'error':
      // Reported in-band: the status line was already sent, so the
      // failure arrives as an event rather than an HTTP status.
      handlers.onError?.(new ApiError(String(payload.message ?? 'Generation failed'), 200, String(payload.code ?? '')));
      break;
    default:
      break;
  }
}

export async function listConversations(): Promise<ConversationListResponse> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_BASE}/conversations`, { headers });
  return handleResponse<ConversationListResponse>(res);
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_BASE}/conversations/${id}`, { headers });
  return handleResponse<ConversationDetail>(res);
}

export async function deleteConversation(id: string): Promise<void> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_BASE}/conversations/${id}`, {
    method: 'DELETE',
    headers,
  });
  return handleResponse<void>(res);
}
