/**
 * Researchly API client.
 *
 * All requests attach the Supabase JWT from the current session so the
 * FastAPI backend can verify the caller's identity.
 */

import { supabase } from './supabase';
import type { Paper, PaperListResponse } from '../types/paper';

const API_BASE = import.meta.env.VITE_API_URL as string | undefined ?? 'http://localhost:8000/api';

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

async function getAuthHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new Error('Not authenticated');
  return { Authorization: `Bearer ${token}` };
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // ignore JSON parse errors
    }
    throw new Error(detail);
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
