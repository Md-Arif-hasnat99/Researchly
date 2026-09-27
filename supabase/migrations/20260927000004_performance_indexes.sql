-- Part 19 — query indexes for the ORDER BY the app actually issues.
--
-- Every index in the schema so far is single-column, but the list
-- endpoints all filter on one column *and* sort on another. Postgres
-- cannot use a single-column index to satisfy both, so each of these
-- queries has been filtering and then sorting the user's whole set in
-- memory (a "scan, filter, sort" plan that degrades linearly with a
-- user's library size). The composite index below serves filter + sort
-- from one ordered scan.
--
-- Plain CREATE INDEX, not CONCURRENTLY: the Supabase CLI runs each
-- migration inside a transaction, where CONCURRENTLY is not allowed.
-- These tables are small, so the brief ACCESS EXCLUSIVE lock is fine.
-- The indexes are additive — the single-column indexes stay, because
-- they still serve the point lookups and joins that use them.

-- GET /api/papers — .eq("user_id").order("created_at", desc=True)
create index if not exists papers_user_id_created_at_idx
    on public.papers (user_id, created_at desc);

-- GET /api/chat/conversations — .eq("user_id").order("updated_at", desc=True)
create index if not exists conversations_user_id_updated_at_idx
    on public.conversations (user_id, updated_at desc);

-- GET /api/chat/conversations/{id} — .eq("conversation_id").order("created_at")
create index if not exists messages_conversation_id_created_at_idx
    on public.messages (conversation_id, created_at);

-- GET /api/papers/{id}/chunks — .eq("paper_id").order("chunk_index")
-- Also serves the per-paper ordering a chunk dump needs, so a paper's
-- chunks never come back interleaved with another's.
create index if not exists paper_chunks_paper_id_chunk_index_idx
    on public.paper_chunks (paper_id, chunk_index);
