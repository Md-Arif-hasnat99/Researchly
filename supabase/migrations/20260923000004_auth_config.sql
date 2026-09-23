-- ============================================================
-- Researchly - Seed: Supabase Auth Configuration
-- Part 1: Configure Auth settings (apply via Supabase Dashboard or CLI)
-- ============================================================

-- NOTE: These are DECLARATIVE NOTES / DOCUMENTATION.
-- The actual Auth configuration must be applied through:
--   - Supabase Dashboard → Authentication → Providers
--   - OR `supabase config` via the Supabase CLI (config.toml)
--
-- Required Auth settings:
--
-- [auth]
-- site_url          = "http://localhost:3000"  (dev) / "https://your-domain.com" (prod)
-- additional_redirect_urls = ["http://localhost:3000/auth/callback"]
-- jwt_expiry        = 3600   (1 hour)
-- enable_signup     = true
-- minimum_password_length = 8
--
-- [auth.email]
-- enable_confirmations = false   (dev); true (prod)
-- double_confirm_changes = true
-- enable_secure_email_change = true
--
-- [auth.external]
-- # No OAuth providers enabled in MVP
-- # Enable Google OAuth in Part 2 if desired

-- Verify extensions are configured properly
do $$
begin
    if not exists (
        select 1 from pg_extension where extname = 'vector'
    ) then
        raise exception 'pgvector extension is required. Enable it in Supabase Dashboard → Database → Extensions → vector.';
    end if;

    raise notice '✅ pgvector extension is active.';
    raise notice '✅ Researchly schema migration complete.';
end;
$$;
