/** Paper domain types mirroring the backend PaperResponse schema. */

export type PaperStatus = 'uploaded' | 'processing' | 'ready' | 'failed';

export interface Paper {
  id: string;
  user_id: string;
  title: string;
  authors: string[];
  abstract: string | null;
  publication_year: number | null;
  file_path: string;
  file_size: number | null;
  total_pages: number | null;
  status: PaperStatus;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface PaperListResponse {
  papers: Paper[];
  total: number;
}
