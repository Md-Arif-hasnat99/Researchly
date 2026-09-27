-- Fix the type of the tsquery variable in search_paper_chunks_by_keyword.
--
-- The function declared its local as `tsvector` but assigns it the result
-- of `websearch_to_tsquery(...)`, which returns `tsquery`. PostgreSQL has no
-- implicit cast between the two, so every call raised
--
--   ERROR: cannot cast type tsquery to tsvector
--
-- and keyword search (and therefore the keyword half of hybrid search)
-- could not work at all.
--
-- The declared type is the only defect: the surrounding expressions
-- (ts_rank_cd and the @@ operator) both take a tsquery against the
-- `search_vector` column, so changing the declaration is the whole fix.

create or replace function public.search_paper_chunks_by_keyword(
    query_text text,
    user_id     uuid,
    paper_ids   uuid[] default null,
    match_count integer default 20
)
returns table (
    chunk_id        uuid,
    paper_id        uuid,
    paper_title     text,
    page_number     integer,
    section         text,
    content         text,
    keyword_score   double precision
)
language plpgsql
stable
security definer          -- runs with definer's privileges so the service-role
set search_path = public  -- key used by the API can bypass per-user RLS
as $$
declare
    tsquery_english tsquery;
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
            -- Complements the stemmed tsvector match: an exact model or
            -- dataset name should not be diluted by its stem.
            (select coalesce(sum(
                case
                    when pc.content ~* ('\m' || term || '\M') then 1.0
                    else 0.0
                end
            ), 0.0)
             from regexp_split_to_array(lower(query_text), '\s+') as term)
            / greatest(1, array_length(
                regexp_split_to_array(lower(query_text), '\s+'), 1)
            )
        )                                        as keyword_score
    from public.paper_chunks pc
    join public.papers p on p.id = pc.paper_id
    where p.user_id = search_paper_chunks_by_keyword.user_id
      and (search_paper_chunks_by_keyword.paper_ids is null
           or pc.paper_id = any(search_paper_chunks_by_keyword.paper_ids))
      and pc.search_vector @@ tsquery_english
    order by keyword_score desc, pc.page_number asc
    limit greatest(1, least(search_paper_chunks_by_keyword.match_count, 100));
end;
$$;

-- The column types are unchanged, so existing grants still describe this
-- function's signature. Re-issuing them is harmless and keeps the
-- privileges correct if the function was recreated without them.
grant execute on function public.search_paper_chunks_by_keyword(text, uuid, uuid[], integer)
    to authenticated;
