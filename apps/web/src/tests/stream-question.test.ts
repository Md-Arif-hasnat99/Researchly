import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../lib/supabase', () => ({
  supabase: {
    auth: {
      getSession: vi.fn().mockResolvedValue({
        data: { session: { access_token: 'test-token' } },
      }),
    },
  },
}));

import { ApiError, streamQuestion } from '../lib/api';

/**
 * Build a Response whose body emits the given byte chunks in order.
 *
 * Chunk boundaries are chosen to split SSE frames mid-way on purpose: a
 * real network response has no relationship to event boundaries, and a
 * parser that assumes otherwise only works in tests.
 */
function streamResponse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder();
  let i = 0;
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    headers: new Headers({ 'content-type': 'text/event-stream' }),
    body: {
      getReader: () => ({
        read: () => {
          if (i >= chunks.length) return Promise.resolve({ done: true, value: undefined });
          const value = encoder.encode(chunks[i]);
          i += 1;
          return Promise.resolve({ done: false, value });
        },
      }),
    },
    json: () => Promise.reject(new SyntaxError('not json')),
  } as unknown as Response;
}

function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

afterEach(() => {
  // Only the stubbed globals: restoreAllMocks would also drop the session
  // mock's implementation, breaking getAuthHeaders in later tests.
  vi.unstubAllGlobals();
});

describe('streamQuestion', () => {
  it('reassembles an answer from token events', async () => {
    const body =
      frame('citations', { citations: [] }) +
      frame('token', { text: 'Hello' }) +
      frame('token', { text: ', ' }) +
      frame('token', { text: 'world' }) +
      frame('done', { message_id: 'm1', reranked: true });

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(streamResponse([body])),
    );

    const res = await streamQuestion('q', undefined, undefined, undefined);

    expect(res.answer).toBe('Hello, world');
    expect(res.message_id).toBe('m1');
    expect(res.reranked).toBe(true);
  });

  it('handles frames split across network chunks', async () => {
    const full =
      frame('token', { text: 'part one' }) +
      frame('token', { text: ' part two' }) +
      frame('done', { message_id: 'm1', reranked: false });

    // Slice the payload at arbitrary points, including mid-JSON and
    // between the "event:" and "data:" lines.
    const midEvent = full.indexOf('data:');
    const chunks = [
      full.slice(0, 10),
      full.slice(10, midEvent + 4),
      full.slice(midEvent + 4, full.indexOf('\n\n') + 1),
      full.slice(full.indexOf('\n\n') + 1),
    ];

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse(chunks)));

    const res = await streamQuestion('q', undefined, undefined, undefined);
    expect(res.answer).toBe('part one part two');
    expect(res.message_id).toBe('m1');
  });

  it('reports tokens to the caller as they arrive, in order', async () => {
    const body =
      frame('token', { text: 'a' }) + frame('token', { text: 'b' }) + frame('done', { message_id: 'm1', reranked: false });

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([body])));

    const seen: string[] = [];
    await streamQuestion('q', undefined, undefined, undefined, {
      onToken: (t) => seen.push(t),
    });

    expect(seen).toEqual(['a', 'b']);
  });

  it('surfaces citations before any token', async () => {
    const citations = [{ chunk_id: 'c1', paper_id: 'p1', content: 'text' }];
    const body = frame('citations', { citations }) + frame('token', { text: 'x' });

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([body])));

    const order: string[] = [];
    const res = await streamQuestion('q', undefined, undefined, undefined, {
      onCitations: () => order.push('citations'),
      onToken: () => order.push('token'),
    });

    expect(order).toEqual(['citations', 'token']);
    expect(res.citations).toEqual(citations);
  });

  it('rejects on an in-band error event instead of resolving empty', async () => {
    const body = frame('error', { code: 'GENERATION_FAILED', message: 'Answer generation failed. Please try again.' });

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([body])));

    let caught: Error | undefined;
    const seen: string[] = [];
    // The stream itself completes normally; the failure is in the payload.
    await streamQuestion('q', undefined, undefined, undefined, {
      onError: (e) => {
        caught = e;
        seen.push('callback');
      },
    }).catch((e: Error) => {
      caught = caught ?? e;
      seen.push('reject');
    });

    // Both channels fire: the callback for observers, the rejection so a
    // caller cannot mistake sources-with-no-answer for success.
    expect(caught).toBeInstanceOf(ApiError);
    expect(caught?.message).toContain('Answer generation failed');
    expect(seen).toEqual(['callback', 'reject']);
  });

  it('rejects when sources arrive but the answer never does', async () => {
    // The reported bug: citations render, the LLM answer does not, and no
    // error is shown — because the promise resolved with an empty answer.
    const body =
      frame('citations', { citations: [{ chunk_id: 'c1' }] }) +
      frame('error', { code: 'RATE_LIMITED', message: 'The AI service is at its request limit right now. Please try again in 47s.', retry_after: 47 });

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([body])));

    let caught: unknown;
    const res = await streamQuestion('q', undefined, undefined, undefined).catch((e: unknown) => {
      caught = e;
      return null;
    });

    expect(res).toBeNull();
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).message).toContain('request limit');
  });

  it('throws an ApiError for a pre-stream failure, preserving the status', async () => {
    // A 503 before the first byte is a normal JSON error response.
    const body = JSON.stringify({ error: { code: 'SERVICE_UNAVAILABLE', message: 'unavailable' } });
    const res = {
      ok: false,
      status: 503,
      statusText: '',
      headers: new Headers({ 'x-request-id': 'req-1' }),
      json: () => Promise.resolve(JSON.parse(body)),
      body: null,
    } as unknown as Response;

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(res));

    let caught: unknown;
    try {
      await streamQuestion('q', undefined, undefined, undefined);
    } catch (e) {
      caught = e;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(503);
    // 5xx messages carry the request id so a failure can be traced.
    expect((caught as ApiError).message).toContain('req-1');
  });

  it('sends the auth header and asks for an event stream', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([frame('done', { message_id: 'm', reranked: false })])));

    await streamQuestion('why', 'conv-1', ['p1'], true);

    const call = vi.mocked(fetch).mock.calls[0];
    const init = call[1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer test-token');
    expect((init.headers as Record<string, string>).Accept).toBe('text/event-stream');
    expect(JSON.parse(init.body as string)).toEqual({
      query: 'why',
      conversation_id: 'conv-1',
      paper_ids: ['p1'],
      rerank: true,
    });
  });
});
