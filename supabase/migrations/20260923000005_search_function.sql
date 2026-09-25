-- ============================================================
-- Researchly - pgvector similarity search function
-- Part 6: Retrieval
-- Idempotent: uses CREATE OR REPLACE
-- ============================================================

-- match_paper_chunks
-- Performs a cosine-similarity nearest-neighbour search over
-- paper_chunks.embedding using pgvector's <=> operator.
--
-- Parameters:
--   query_embedding    : vector(768) — the query embedding from the client
--   match_count        : int         — maximum rows to return (top-K)
--   similarity_threshold: float      — minimum similarity score (0–1)
--   filter_user_id     : uuid        — only return chunks whose parent paper
--                                      belongs to this user (ownership gate)
--   filter_paper_ids   : uuid[]      — optional list of paper IDs to restrict
--                                      the search; NULL means all user papers
--
-- Returns:
--   chunk_id        uuid
--   paper_id        uuid
--   paper_title     text
--   page_number     int
--   section         text
--   content         text
--   similarity      float  — cosine similarity (1 − cosine_distance)

create or replace function public.match_paper_chunks(
    query_embedding     vector(768),
    match_count         int             default 8,
    similarity_threshold float          default 0.65,
    filter_user_id      uuid            default null,
    filter_paper_ids    uuid[]          default null
)
returns table (
    chunk_id        uuid,
    paper_id        uuid,
    paper_title     text,
    page_number     int,
    section         text,
    content         text,
    similarity      float
)
language plpgsql
security definer          -- runs with definer's privileges so the service-role
set search_path = public  -- key used by the API can bypass per-user RLS
as $$
begin
    return query
    select
        pc.id                                     as chunk_id,
        p.id                                      as paper_id,
        p.title                                   as paper_title,
        pc.page_number,
        pc.section,
        pc.content,
        (1 - (pc.embedding <=> query_embedding))  as similarity
    from public.paper_chunks pc
    join public.papers p on p.id = pc.paper_id
    where
        -- Ownership: only the requesting user's papers
        p.user_id = filter_user_id
        -- Optional paper-ID filter
        and (filter_paper_ids is null or p.id = any(filter_paper_ids))
        -- Only papers that finished ingestion
        and p.status = 'ready'
        -- Similarity threshold: discard distant vectors
        and (1 - (pc.embedding <=> query_embedding)) >= similarity_threshold
    order by pc.embedding <=> query_embedding  -- ascending distance = descending similarity
    limit match_count;
end;
$$;

-- Grant execute to the authenticated role so Supabase JS clients can also
-- call this function directly if needed (the API uses service-role).
grant execute on function public.match_paper_chunks(
    vector(768), int, float, uuid, uuid[]
) to authenticated;
