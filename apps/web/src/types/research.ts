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

// ---------------------------------------------------------------------------
// Literature review (FR-12)
// ---------------------------------------------------------------------------

export interface LiteratureReviewRequest {
  paper_ids: string[];
  title?: string;
  focus?: string;
  sections?: string[];
  per_paper_top_k?: number;
}

export interface ReviewCitation {
  paper_id: string;
  paper_title: string;
  page_number: number | null;
  chunk_id: string | null;
}

export interface ReviewSection {
  heading: string;
  content: string;
  citations: ReviewCitation[];
  /** True when the retrieved context could not support this section. */
  insufficient_context: boolean;
}

export interface LiteratureReviewResponse {
  title: string;
  papers: ComparePaperRef[];
  sections: ReviewSection[];
  references: ComparePaperRef[];
  citations: string[];
}
