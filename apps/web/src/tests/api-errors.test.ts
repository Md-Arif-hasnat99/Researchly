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

import { ApiError, listPapers } from '../lib/api';

function mockResponse(
  status: number,
  body: unknown,
  opts: { statusText?: string; headers?: Record<string, string>; jsonThrows?: boolean } = {}
): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: opts.statusText ?? '',
    headers: new Headers(opts.headers ?? {}),
    json: opts.jsonThrows
      ? () => Promise.reject(new SyntaxError('not json'))
      : () => Promise.resolve(body),
  } as unknown as Response;
}

async function expectApiError(call: () => Promise<unknown>): Promise<ApiError> {
  try {
    await call();
  } catch (err) {
    expect(err).toBeInstanceOf(ApiError);
    return err as ApiError;
  }
  throw new Error('expected the request to reject');
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('API error handling', () => {
  it('surfaces the unified error message and code', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      mockResponse(404, { error: { code: 'NOT_FOUND', message: 'Paper not found.' } })
    ));

    const err = await expectApiError(() => listPapers());
    expect(err.message).toBe('Paper not found.');
    expect(err.code).toBe('NOT_FOUND');
    expect(err.status).toBe(404);
    expect(err.requestId).toBeUndefined();
  });

  it('appends the server request id to 5xx messages so users can report it', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      mockResponse(500, { error: { code: 'INTERNAL_SERVER_ERROR', message: 'An unexpected server error occurred.' } }, {
        headers: { 'x-request-id': 'ab12cd34ef56ab78' },
      })
    ));

    const err = await expectApiError(() => listPapers());
    expect(err.message).toBe('An unexpected server error occurred. (ref: ab12cd34ef56ab78)');
    expect(err.requestId).toBe('ab12cd34ef56ab78');
  });

  it('does not append a ref id to client errors, which are not a support case', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      mockResponse(401, { error: { code: 'UNAUTHORIZED', message: 'Not authenticated.' } }, {
        headers: { 'x-request-id': 'beef' },
      })
    ));

    const err = await expectApiError(() => listPapers());
    expect(err.message).toBe('Not authenticated.');
  });

  it('still reads a legacy "detail" body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      mockResponse(409, { detail: 'Paper already indexed.' })
    ));

    const err = await expectApiError(() => listPapers());
    expect(err.message).toBe('Paper already indexed.');
  });

  it('falls back to the status text when the body is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      mockResponse(502, null, { statusText: 'Bad Gateway', jsonThrows: true })
    ));

    const err = await expectApiError(() => listPapers());
    expect(err.message).toBe('Bad Gateway');
  });

  it('tells the user how long to wait when the API throttles them', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      mockResponse(429, { error: { code: 'TOO_MANY_REQUESTS', message: 'Too many requests. Please wait a moment before trying again.' } }, {
        headers: { 'retry-after': '30' },
      })
    ));

    const err = await expectApiError(() => listPapers());
    expect(err.status).toBe(429);
    expect(err.code).toBe('TOO_MANY_REQUESTS');
    expect(err.retryAfterSeconds).toBe(30);
    expect(err.message).toContain('30s');
  });

  it('parses successful responses unchanged', async () => {
    const payload = { papers: [], total: 0 };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse(200, payload)));

    await expect(listPapers()).resolves.toEqual(payload);
  });
});
