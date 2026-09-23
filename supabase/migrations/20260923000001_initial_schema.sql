-- ============================================================
-- Researchly - Supabase SQL Migrations
-- Part 1: Database Schema, pgvector, RLS Policies
-- Run these in order in the Supabase SQL Editor or via CLI.
-- ============================================================

-- ============================================================
-- 0. Enable Required Extensions
-- ============================================================

create extension if not exists "pgcrypto";
create extension if not exists "vector";

-- ============================================================
-- 1. profiles
--    Auto-created by a trigger on auth.users
-- ============================================================

create table if not exists public.profiles (
    id          uuid primary key references auth.users (id) on delete cascade,
    name        text,
    email       text unique,
    avatar_url  text,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

comment on table public.profiles is 'Extended public profile data mirroring auth.users';

-- Trigger: keep updated_at fresh
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create or replace trigger profiles_updated_at
    before update on public.profiles
    for each row execute procedure public.set_updated_at();

-- Trigger: create profile row when a new user signs up
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
    insert into public.profiles (id, name, email, avatar_url)
    values (
        new.id,
        coalesce(new.raw_user_meta_data ->> 'full_name', new.raw_user_meta_data ->> 'name'),
        new.email,
        new.raw_user_meta_data ->> 'avatar_url'
    )
    on conflict (id) do nothing;
    return new;
end;
$$;

create or replace trigger on_auth_user_created
    after insert on auth.users
    for each row execute procedure public.handle_new_user();

-- ============================================================
-- 2. papers
-- ============================================================

create type public.paper_status as enum ('uploaded', 'processing', 'ready', 'failed');

create table if not exists public.papers (
    id                  uuid primary key default gen_random_uuid(),
    user_id             uuid not null references auth.users (id) on delete cascade,
    title               text not null default 'Untitled Paper',
    authors             text[] not null default '{}',
    abstract            text,
    publication_year    int,
    file_path           text not null,
    file_size           bigint,
    total_pages         int,
    status              public.paper_status not null default 'uploaded',
    error_message       text,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

comment on table public.papers is 'Uploaded scientific PDF papers, one row per paper per user.';

create index if not exists papers_user_id_idx on public.papers (user_id);
create index if not exists papers_status_idx  on public.papers (status);

create or replace trigger papers_updated_at
    before update on public.papers
    for each row execute procedure public.set_updated_at();

-- ============================================================
-- 3. paper_chunks
--    Stores embedded text chunks with 768-dim pgvector column
-- ============================================================

create table if not exists public.paper_chunks (
    id            uuid primary key default gen_random_uuid(),
    paper_id      uuid not null references public.papers (id) on delete cascade,
    content       text not null,
    page_number   int not null,
    section       text,
    chunk_index   int not null,
    embedding     vector(768),
    created_at    timestamptz not null default now()
);

comment on table public.paper_chunks is 'Page-level text chunks with Gemini text-embedding-004 (768-dim) vectors.';

create index if not exists paper_chunks_paper_id_idx on public.paper_chunks (paper_id);

-- IVFFlat index for cosine similarity (fast approximate nearest-neighbour search)
-- Note: build this after the first batch of embeddings are inserted for best list sizing.
create index if not exists paper_chunks_embedding_cosine_idx
    on public.paper_chunks
    using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

-- ============================================================
-- 4. conversations
-- ============================================================

create table if not exists public.conversations (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references auth.users (id) on delete cascade,
    title       text not null default 'New Conversation',
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

comment on table public.conversations is 'RAG chat conversation sessions per user.';

create index if not exists conversations_user_id_idx on public.conversations (user_id);

create or replace trigger conversations_updated_at
    before update on public.conversations
    for each row execute procedure public.set_updated_at();

-- ============================================================
-- 5. messages
-- ============================================================

create type public.message_role as enum ('user', 'assistant');

create table if not exists public.messages (
    id                uuid primary key default gen_random_uuid(),
    conversation_id   uuid not null references public.conversations (id) on delete cascade,
    role              public.message_role not null,
    content           text not null,
    created_at        timestamptz not null default now()
);

comment on table public.messages is 'User and assistant messages within a conversation.';

create index if not exists messages_conversation_id_idx on public.messages (conversation_id);
create index if not exists messages_created_at_idx      on public.messages (created_at);

-- ============================================================
-- 6. citations
--    Links each assistant message to source paper chunks
-- ============================================================

create table if not exists public.citations (
    id                uuid primary key default gen_random_uuid(),
    message_id        uuid not null references public.messages (id) on delete cascade,
    paper_id          uuid not null references public.papers (id) on delete cascade,
    chunk_id          uuid not null references public.paper_chunks (id) on delete cascade,
    page_number       int not null,
    similarity_score  float,
    created_at        timestamptz not null default now()
);

comment on table public.citations is 'Source citations mapping assistant messages to evidence chunks.';

create index if not exists citations_message_id_idx on public.citations (message_id);
create index if not exists citations_paper_id_idx   on public.citations (paper_id);

-- ============================================================
-- 7. Helper: match_paper_chunks
--    pgvector cosine similarity search used by the retrieval layer
-- ============================================================

create or replace function public.match_paper_chunks(
    query_embedding   vector(768),
    match_count       int          default 8,
    similarity_cutoff float        default 0.65,
    filter_paper_ids  uuid[]       default null
)
returns table (
    id               uuid,
    paper_id         uuid,
    content          text,
    page_number      int,
    section          text,
    chunk_index      int,
    similarity       float
)
language plpgsql as $$
begin
    return query
    select
        pc.id,
        pc.paper_id,
        pc.content,
        pc.page_number,
        pc.section,
        pc.chunk_index,
        1 - (pc.embedding <=> query_embedding) as similarity
    from public.paper_chunks pc
    where
        pc.embedding is not null
        and (filter_paper_ids is null or pc.paper_id = any(filter_paper_ids))
        and 1 - (pc.embedding <=> query_embedding) >= similarity_cutoff
    order by pc.embedding <=> query_embedding
    limit match_count;
end;
$$;

comment on function public.match_paper_chunks is
    'Cosine-similarity nearest-neighbour search against paper_chunks embeddings via pgvector.';
