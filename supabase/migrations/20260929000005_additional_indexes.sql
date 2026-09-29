-- Part 20 — additional composite indexes for query patterns not covered yet.
--
-- These address remaining "filter + sort" patterns that still scan+filter+sort
-- in memory because single-column indexes don't cover both operations.
--
-- Run in transaction (Supabase CLI default); not CONCURRENTLY (tables small).

-- citations join path for GET /api/chat/conversations/{id}
-- citations -> messages -> conversations -> papers -> paper_chunks
create index if not exists citations_message_id_paper_id_chunk_id_idx
    on public.citations (message_id, paper_id, chunk_id);

-- paper_chunks vector search: HNSW index (better recall/speed than IVFFlat)
-- Run AFTER data exists; pgvector HNSW requires data to build graph.
-- create index concurrently if not exists paper_chunks_embedding_hnsw_idx
--     on public.paper_chunks
--     using hnsw (embedding vector_cosine_ops)
--     with (m = 16, ef_construction = 64);

-- citations query optimization for GET /api/chat/conversations/{id}
-- Direct join on message_id (already indexed) + paper_id + chunk_id
create index if not exists citations_message_id_idx
    on public.citations (message_id);

-- papers table: index for user library listing with status filter
-- Supports queries like: user_id = ? AND status = 'ready' ORDER BY created_at
create index if not exists papers_user_id_status_created_at_idx
    on public.papers (user_id, status, created_at desc);

-- conversations: index for user's active conversations
-- Supports: user_id = ? AND status = 'active' ORDER BY updated_at
create index if not exists conversations_user_id_status_updated_at_idx
    on public.conversations (user_id, status, updated_at desc);

-- paper_chunks: composite index for paper-level queries with status
-- Supports: paper_id = ? AND status = 'ready' ORDER BY chunk_index
create index if not exists paper_chunks_paper_id_status_chunk_index_idx
    on public.paper_chunks (paper_id, status, chunk_index);