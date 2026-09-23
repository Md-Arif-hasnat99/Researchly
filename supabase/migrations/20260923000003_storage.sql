-- ============================================================
-- Researchly - Supabase Storage Configuration
-- Part 1: research-papers bucket setup
-- ============================================================

-- Create the research-papers bucket (private by default)
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'research-papers',
    'research-papers',
    false,
    52428800,  -- 50 MB limit per file
    array['application/pdf']
)
on conflict (id) do update
    set file_size_limit    = excluded.file_size_limit,
        allowed_mime_types = excluded.allowed_mime_types;

-- ============================================================
-- Storage RLS Policies
-- Only authenticated owners can upload/read/delete their files.
-- File path convention: {user_id}/{paper_id}.pdf
-- ============================================================

-- Allow users to upload files under their own user_id prefix
create policy "storage: owner upload"
    on storage.objects for insert
    to authenticated
    with check (
        bucket_id = 'research-papers'
        and (storage.foldername(name))[1] = auth.uid()::text
    );

-- Allow users to read their own uploaded files
create policy "storage: owner select"
    on storage.objects for select
    to authenticated
    using (
        bucket_id = 'research-papers'
        and (storage.foldername(name))[1] = auth.uid()::text
    );

-- Allow users to delete their own files
create policy "storage: owner delete"
    on storage.objects for delete
    to authenticated
    using (
        bucket_id = 'research-papers'
        and (storage.foldername(name))[1] = auth.uid()::text
    );
