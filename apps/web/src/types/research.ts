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

// ---------------------------------------------------------------------------
// Research gaps (FR-13)
// ---------------------------------------------------------------------------

/** The recurring gap types FR-13 asks the system to identify. */
export type GapCategory =
  | 'Limitation'
  | 'Unresolved Problem'
  | 'Future Work'
  | 'Dataset Limitation'
  | 'Methodological Gap';

export const GAP_CATEGORIES: GapCategory[] = [
  'Limitation',
  'Unresolved Problem',
  'Future Work',
  'Dataset Limitation',
  'Methodological Gap',
];

export interface GapRequest {
  paper_ids: string[];
  categories?: GapCategory[];
  focus?: string;
  per_paper_top_k?: number;
}

export interface GapCitation {
  paper_id: string;
  paper_title: string;
  page_number: number | null;
  chunk_id: string | null;
}

export interface ResearchGap {
  title: string;
  category: GapCategory;
  /** The gap itself, in plain language (AI analysis). */
  description: string;
  /** What the papers actually state that supports the gap. */
  evidence: string;
  /** AI-suggested direction. Not a paper finding. */
  suggested_direction: string;
  paper_ids: string[];
  citations: GapCitation[];
  /** How many distinct papers raised this gap. */
  recurrence: number;
}

export interface GapCluster {
  category: GapCategory;
  gaps: ResearchGap[];
}

export interface GapResponse {
  papers: ComparePaperRef[];
  clusters: GapCluster[];
  summary: string;
  citations: string[];
}
