/** Multi-paper research domain types (FR-10, FR-11). */

export interface CompareRequest {
  paper_ids: string[];
  aspects?: string[];
  per_paper_top_k?: number;
  focus?: string;
}

export interface CompareCell {
  paper_id: string;
  paper_title: string;
  summary: string;
  page_number: number | null;
  chunk_id: string | null;
  not_reported: boolean;
}

export interface CompareRow {
  aspect: string;
  cells: CompareCell[];
}

export interface ComparePaperRef {
  paper_id: string;
  paper_title: string;
  publication_year: number | null;
}

export interface CompareResponse {
  papers: ComparePaperRef[];
  rows: CompareRow[];
  summary: string;
  citations: string[];
}
