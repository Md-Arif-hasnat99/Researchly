-- ============================================================
-- Researchly - Row Level Security Policies
-- Part 1: RLS Enforcement
-- ============================================================

-- ============================================================
-- Enable RLS on every user-owned table
-- ============================================================

alter table public.profiles      enable row level security;
alter table public.papers        enable row level security;
alter table public.paper_chunks  enable row level security;
alter table public.conversations enable row level security;
alter table public.messages      enable row level security;
alter table public.citations     enable row level security;

-- ============================================================
-- profiles
-- ============================================================

create policy "profiles: owner select"
    on public.profiles for select
    using (auth.uid() = id);

create policy "profiles: owner update"
    on public.profiles for update
    using (auth.uid() = id);

-- ============================================================
-- papers
-- ============================================================

create policy "papers: owner select"
    on public.papers for select
    using (auth.uid() = user_id);

create policy "papers: owner insert"
    on public.papers for insert
    with check (auth.uid() = user_id);

create policy "papers: owner update"
    on public.papers for update
    using (auth.uid() = user_id);

create policy "papers: owner delete"
    on public.papers for delete
    using (auth.uid() = user_id);

-- ============================================================
-- paper_chunks
--    Access is inherited through ownership of the parent paper
-- ============================================================

create policy "paper_chunks: owner select"
    on public.paper_chunks for select
    using (
        exists (
            select 1 from public.papers p
            where p.id = paper_chunks.paper_id
            and p.user_id = auth.uid()
        )
    );

create policy "paper_chunks: owner insert"
    on public.paper_chunks for insert
    with check (
        exists (
            select 1 from public.papers p
            where p.id = paper_chunks.paper_id
            and p.user_id = auth.uid()
        )
    );

create policy "paper_chunks: owner delete"
    on public.paper_chunks for delete
    using (
        exists (
            select 1 from public.papers p
            where p.id = paper_chunks.paper_id
            and p.user_id = auth.uid()
        )
    );

-- ============================================================
-- conversations
-- ============================================================

create policy "conversations: owner select"
    on public.conversations for select
    using (auth.uid() = user_id);

create policy "conversations: owner insert"
    on public.conversations for insert
    with check (auth.uid() = user_id);

create policy "conversations: owner update"
    on public.conversations for update
    using (auth.uid() = user_id);

create policy "conversations: owner delete"
    on public.conversations for delete
    using (auth.uid() = user_id);

-- ============================================================
-- messages
--    Access via parent conversation ownership
-- ============================================================

create policy "messages: owner select"
    on public.messages for select
    using (
        exists (
            select 1 from public.conversations c
            where c.id = messages.conversation_id
            and c.user_id = auth.uid()
        )
    );

create policy "messages: owner insert"
    on public.messages for insert
    with check (
        exists (
            select 1 from public.conversations c
            where c.id = messages.conversation_id
            and c.user_id = auth.uid()
        )
    );

create policy "messages: owner delete"
    on public.messages for delete
    using (
        exists (
            select 1 from public.conversations c
            where c.id = messages.conversation_id
            and c.user_id = auth.uid()
        )
    );

-- ============================================================
-- citations
--    Access via parent message → conversation → user chain
-- ============================================================

create policy "citations: owner select"
    on public.citations for select
    using (
        exists (
            select 1
            from public.messages m
            join public.conversations c on c.id = m.conversation_id
            where m.id = citations.message_id
            and c.user_id = auth.uid()
        )
    );

create policy "citations: owner insert"
    on public.citations for insert
    with check (
        exists (
            select 1
            from public.messages m
            join public.conversations c on c.id = m.conversation_id
            where m.id = citations.message_id
            and c.user_id = auth.uid()
        )
    );

create policy "citations: owner delete"
    on public.citations for delete
    using (
        exists (
            select 1
            from public.messages m
            join public.conversations c on c.id = m.conversation_id
            where m.id = citations.message_id
            and c.user_id = auth.uid()
        )
    );
