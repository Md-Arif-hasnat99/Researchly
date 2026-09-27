-- ============================================================
-- Researchly - Part 18 Security fixes
--
-- Two defects that left the database less protected than the code
-- assumed, plus the search function they interact with.
-- ============================================================
--
-- 1. The storage policies protected a bucket the application never uses.
--    20260923000003_storage.sql provisions and guards 'research-papers',
--    but app/core/storage.py writes to BUCKET = 'papers'. Every
--    `bucket_id = 'research-papers'` predicate therefore evaluated
--    against objects the app did not create, and the bucket the app
--    really used had no policies and no size/mime limits at all. The
--    application was correct and the database was not, which is the
--    worst combination: it looks configured.
--
-- 2. search_paper_chunks_by_keyword exists twice. 20260926000001
--    created (text, int, uuid, uuid[]) with the parameter names the API
--    actually sends (filter_user_id, filter_paper_ids) and a local
--    declared `tsvector`. 20260927000002 then created a *second*
--    overload (text, uuid, uuid[], integer) with different parameter
--    names, fixing the type error. `create or replace` matches on
--    argument types, so the fix landed beside the broken function
--    instead of on it.
--
--    The consequence: the named-argument call from the API resolves to
--    the original signature, which still declares the local as
--    `tsvector` and still raises
--      ERROR: cannot cast type tsquery to tsvector
--    so keyword search fails, and hybrid search silently degrades to
--    vector-only because it treats a keyword failure as tolerable.
--
--    This migration drops the stray overload and replaces the surviving
--    one in place: the signature the API calls, with the correct
--    `tsquery` declaration, keeping the `status = 'ready'` filter that
--    the later copy had dropped.
-- ============================================================

-- ------------------------------------------------------------
-- 1. Storage: guard the bucket the application actually uses
-- ------------------------------------------------------------

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'papers',
    'papers',
    false,        -- private: every read goes through an authenticated policy
    52428800,     -- 50 MB, matching MAX_UPLOAD_MB
    array['application/pdf']
)
on conflict (id) do update
    set file_size_limit    = excluded.file_size_limit,
        allowed_mime_types = excluded.allowed_mime_types;

-- The layout is {user_id}/{paper_id}.pdf, so the first folder segment is
-- the owner. This is the same ownership gate the table policies use.
--
-- drop-if-exists first: these statements are re-runnable, which the
-- originals were not, and a policy that cannot be re-applied is a policy
-- that silently drifts from the code.
drop policy if exists "storage: owner upload" on storage.objects;
drop policy if exists "storage: owner select" on storage.objects;
drop policy if exists "storage: owner delete" on storage.objects;

create policy "storage: owner upload"
    on storage.objects for insert
    to authenticated
    with check (
        bucket_id = 'papers'
        and (storage.foldername(name))[1] = auth.uid()::text
    );

create policy "storage: owner select"
    on storage.objects for select
    to authenticated
    using (
        bucket_id = 'papers'
        and (storage.foldername(name))[1] = auth.uid()::text
    );

create policy "storage: owner delete"
    on storage.objects for delete
    to authenticated
    using (
        bucket_id = 'papers'
        and (storage.foldername(name))[1] = auth.uid()::text
    );

-- The old 'research-papers' policies used these same three names on the
-- same storage.objects table, so the drop-if-exists above replaced them.
-- The now-unused 'research-papers' bucket may remain; it holds no objects
-- and has no policies granting access.

-- ------------------------------------------------------------
-- 2. Keyword search: one function, the signature the API calls
-- ------------------------------------------------------------

-- Remove the duplicate created by 20260927000002. The argument types
-- differ from the surviving function's, so this cannot be a replace.
drop function if exists public.search_paper_chunks_by_keyword(text, uuid, uuid[], integer);

-- Same signature as 20260926000001 (text, int, uuid, uuid[]) and the
-- same return type, so this replaces in place; `create or replace`
-- cannot change either, and both are unchanged here on purpose.
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
    tsquery_english tsquery;   -- was tsvector: websearch_to_tsquery
                                -- returns tsquery and there is no implicit
                                -- cast, so every call used to fail
begin
    -- A blank or punctuation-only query has no meaningful tsquery.
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
            -- Whole-word hits for the literal query terms, so an exact
            -- model or dataset name is not diluted by its stem.
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
        -- Only ingested papers have searchable chunks. The copy created
        -- by 20260927000002 lost this clause and would match a paper
        -- whose ingestion is still running.
        and p.status = 'ready'
        -- At least one query term must be lexically present.
        and pc.search_vector @@ tsquery_english
    -- Tie-break deterministically on (title, page, chunk id) so repeated
    -- identical queries return a stable order.
    order by keyword_rank desc, p.title, pc.page_number, pc.id
    -- Clamped so a caller cannot ask for an unbounded result set.
    limit greatest(1, least(match_count, 100));
end;
$$;

comment on function public.search_paper_chunks_by_keyword(text, int, uuid, uuid[]) is
    'Full-text keyword search over paper_chunks with ownership gating; lexical rank for hybrid fusion.';

-- Re-issued because the dropped overload took its grant with it, and
-- because a replaced function keeps its privileges only if it had them.
grant execute on function public.search_paper_chunks_by_keyword(text, int, uuid, uuid[])
    to authenticated;

-- A note for whoever deploys this, not an action:
--
-- Row level security on the data tables is real but is not the primary
-- control, because every route uses the service-role key, which bypasses
-- RLS by design. The database backstop that does apply is this pair:
-- the per-user `.eq("user_id", ...)` filters in app/api, and the
-- ownership gate inside these two `security definer` functions, which
-- take the user id as a parameter and filter on it server-side.
--
-- FORCE ROW LEVEL SECURITY is deliberately NOT enabled: these functions
-- run as their owner, so forcing RLS on papers/paper_chunks would make
-- them evaluate the policies with a null auth.uid() and return nothing.
