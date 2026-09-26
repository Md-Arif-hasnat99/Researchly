/** Search API contracts (FR-06 semantic search, FR-14 hybrid search). */

export type SearchMode = 'vector' | 'keyword' | 'hybrid';

/**
 * Which retriever(s) surfaced a result. `vector` = semantic similarity,
 * `keyword` = literal term match. A result tagged with both is the
 * strongest evidence of relevance, since the retrievers are individually
 * weak exactly where the other is strong.
 */
export type MatchSource = 'vector' | 'keyword';

export interface SearchRequest {
  query: string;
  paper_ids?: string[];
  top_k?: number;
  similarity_threshold?: number;
  /** Defaults to `hybrid` on the server. */
  mode?: SearchMode;
}

export interface SearchResult {
  chunk_id: string;
  paper_id: string;
  paper_title: string;
  page_number: number;
  section: string | null;
  content: string;
  /**
   * Cosine similarity, or null for a keyword-only hit. Null means "no
   * vector comparison was made", not "similarity of zero".
   */
  similarity_score: number | null;
  matched_by: MatchSource[];
  /**
   * Rank-fusion score. Not comparable to `similarity_score`: it measures
   * agreement between retrievers' orderings, not semantic closeness.
   */
  fusion_score: number | null;
}

export interface SearchResponse {
  query: string;
  /**
   * The retriever that actually ran. Differs from the requested mode when
   * hybrid search fell back to vector-only because keyword search was
   * unavailable.
   */
  mode: SearchMode;
  results: SearchResult[];
  total_results: number;
}
