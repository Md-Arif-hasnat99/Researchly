export type PaperStatus = "uploaded" | "processing" | "ready" | "failed";

export interface Paper {
  id: string;
  user_id: string;
  title: string;
  authors: string[];
  abstract?: string;
  publication_year?: number;
  file_path: string;
  file_size?: number;
  total_pages?: number;
  status: PaperStatus;
  error_message?: string;
  created_at: string;
  updated_at: string;
}

export interface PaperChunk {
  id: string;
  paper_id: string;
  content: string;
  page_number: number;
  section?: string;
  chunk_index: number;
  created_at: string;
}

export interface Citation {
  id: string;
  message_id: string;
  paper_id: string;
  chunk_id: string;
  page_number: number;
  similarity_score?: number;
  paper_title?: string;
  snippet?: string;
  created_at: string;
}

export interface Conversation {
  id: string;
  user_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  created_at: string;
}

export interface SearchQuery {
  query: string;
  paper_ids?: string[];
  top_k?: number;
  similarity_threshold?: number;
}

export interface SearchResultChunk {
  chunk_id: string;
  paper_id: string;
  paper_title: string;
  page_number: number;
  section?: string;
  content: string;
  similarity_score: number;
}

export interface SearchResponse {
  query: string;
  results: SearchResultChunk[];
  total_results: number;
}

export interface ChatRequest {
  conversation_id?: string;
  message: string;
  paper_ids?: string[];
}

export interface ChatResponse {
  conversation_id: string;
  message: Message;
  citations: Citation[];
}

export interface CompareRequest {
  paper_ids: string[];
  aspects?: string[];
}

export interface CompareAspectComparison {
  aspect: string;
  papers: Record<string, { summary: string; page_references: number[] }>;
}

export interface CompareResponse {
  paper_ids: string[];
  comparisons: CompareAspectComparison[];
  summary: string;
}

export interface LiteratureReviewRequest {
  paper_ids: string[];
  topic?: string;
}

export interface LiteratureReviewSection {
  heading: string;
  content: string;
  cited_paper_ids: string[];
}

export interface LiteratureReviewResponse {
  title: string;
  topic?: string;
  sections: LiteratureReviewSection[];
  references: { paper_id: string; title: string; authors: string[]; year?: number }[];
}

export interface ResearchGapsRequest {
  paper_ids: string[];
}

export interface ResearchGapItem {
  area: string;
  gap_description: string;
  source_paper_id: string;
  source_paper_title: string;
  page_number?: number;
  recommendation: string;
}

export interface ResearchGapsResponse {
  gaps: ResearchGapItem[];
  synthesis: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  service: string;
  timestamp: string;
}

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}
