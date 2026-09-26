-- ============================================================
-- Researchly - keyword (full-text) search for hybrid retrieval
-- Part 14: Hybrid Search (FR-14)
-- Idempotent: uses ADD COLUMN IF NOT EXISTS / CREATE OR REPLACE
-- ============================================================
--
-- FR-14 requires combining vector search with keyword search so that
-- exact technical terms (model names, abbreviations, dataset names)
-- are retrievable. Vector search alone routinely misses these: an
-- embedding of "BERT-base fine-tuning" and "ViT-L/16 fine-tuning"
-- are close enough to score well against either query, so a search
-- for one specific name returns the other almost as readily.
--
-- This migration adds the lexical half of the hybrid pipeline:
--   1. a generated tsvector column + GIN index on paper_chunks
--   2. search_paper_chunks_by_keyword(), a rank-ordered keyword search
--
-- Fusion of the two result lists happens in the application layer
-- (app/rag/retrieval/search.py) using Reciprocal Rank Fusion, which
-- operates on ranks and therefore needs no score normalisation
-- between cosine similarity and ts_rank.


-- ------------------------------------------------------------
-- 1. Full-text search vector
-- ------------------------------------------------------------
-- Generated rather than trigger-maintained: Postgres recomputes it on
-- insert/update, so it cannot drift out of sync with `content`.
-- 'english' is passed as a literal so the expression stays IMMUTABLE
-- and is therefore allowed in a generated column. Note that this also
-- applies stemming and stop-word removal, which is why the ranking
-- below adds a separate verbatim-term boost.

alter table public.paper_chunks
    add column if not exists search_vector tsvector
    generated always as (to_tsvector('english', content)) stored;

comment on column public.paper_chunks.search_vector is
    'Generated tsvector for lexical (keyword) search; maintained by Postgres from content.';

-- GIN rather than GiST: the @@ operator used by search_paper_chunks_by_keyword
-- is GIN-friendly, and keyword search is the only consumer of this index.
create index if not exists paper_chunks_search_vector_idx
    on public.paper_chunks
    using gin (search_vector);


-- ------------------------------------------------------------
-- 2. search_paper_chunks_by_keyword
-- ------------------------------------------------------------
-- Full-text keyword search over paper_chunks, ordered by lexical
-- relevance. Mirrors the ownership gating of match_paper_chunks so
-- neither half of the hybrid pipeline can leak another user's papers.
--
-- Parameters:
--   query_text        : text   — the raw user query
--   match_count       : int    — maximum rows to return (top-K)
--   filter_user_id    : uuid   — only chunks whose parent paper belongs
--                                to this user (ownership gate)
--   filter_paper_ids  : uuid[] — optional paper-ID restriction
--
-- Returns:
--   chunk_id      uuid
--   paper_id      uuid
--   paper_title   text
--   page_number   int
--   section       text
--   content       text
--   keyword_rank  float — lexical relevance; higher is better
--
-- Ranking is ts_rank_cd(..., 32) plus a verbatim-term bonus.
--
--   * ts_rank_cd with the 32 normalisation divides by 1 + log(chunk
--     length), so a long chunk does not outrank a short, dense one
--     purely for being longer. This matters because chunks vary a lot
--     in length between a dense methods section and a sparse page.
--
--   * The verbatim bonus counts query terms that appear as whole words
--     in the chunk (\m ... \M are word boundaries). The 'english'
--     stemmer folds related words together, so a search for
--     "ImageNet" would otherwise happily match "image
--     classification" through the shared stem "imag". Whole-word
--     matching keeps a rare proper noun an exact-term hit while
--     leaving ordinary lexical ranking to ts_rank.
--
-- websearch_to_tsquery is used rather than plainto_tsquery because it
-- accepts the query syntax users actually type: quoted phrases,
-- OR, and a leading - for negation.

create or replace function public.search_paper_chunks_by_keyword(
    query_text       text,
    match_count      int    default 8,
    filter_user_id   uuid   default null,
    filter_paper_ids uuid[] default null
)
returns table (
    chunk_id     uuid,
    paper_id     uuid,
    paper_title  text,
    page_number  int,
    section      text,
    content      text,
    keyword_rank float
)
language plpgsql
stable
security definer          -- runs with definer's privileges so the service-role
set search_path = public  -- key used by the API can bypass per-user RLS
as $$
declare
    tsquery_english tsvector;
begin
    -- A blank or punctuation-only query has no meaningful tsquery.
    -- websearch_to_tsquery returns an empty tsquery for these, which
    -- would match nothing, but bailing out early also avoids
    -- regexp_split_to_array producing a single empty term below.
    if query_text is null or btrim(query_text) = '' then
        return;
    end if;

    tsquery_english := websearch_to_tsquery('english', query_text);

    return query
    select
        pc.id                                     as chunk_id,
        p.id                                      as paper_id,
        p.title                                   as paper_title,
        pc.page_number,
        pc.section,
        pc.content,
        ts_rank_cd(pc.search_vector, tsquery_english, 32)
        + 0.5 * (
            -- Whole-word hits for the literal query terms.
            select count(*)::float
            from unnest(
                regexp_split_to_array(lower(query_text), '[^[:alnum:]]+')
            ) as t(term)
            where t.term <> ''
              and pc.content ~* ('\m' || t.term || '\M')
        )                                          as keyword_rank
    from public.paper_chunks pc
    join public.papers p on p.id = pc.paper_id
    where
        -- Ownership: identical gate to match_paper_chunks
        p.user_id = filter_user_id
        and (filter_paper_ids is null or p.id = any(filter_paper_ids))
        and p.status = 'ready'
        -- At least one query term must be lexically present.
        and pc.search_vector @@ tsquery_english
    -- Tie-break deterministically on (title, page, chunk id) so repeated
    -- identical queries return a stable order.
    order by keyword_rank desc, p.title, pc.page_number, pc.id
    limit match_count;
end;
$$;

comment on function public.search_paper_chunks_by_keyword(text, int, uuid, uuid[]) is
    'Full-text keyword search over paper_chunks with ownership gating; lexical rank for hybrid fusion.';

-- Grant execute to the authenticated role, matching match_paper_chunks.
grant execute on function public.search_paper_chunks_by_keyword(
    text, int, uuid, uuid[]
) to authenticated;
