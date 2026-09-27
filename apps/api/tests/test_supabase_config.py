"""Tests for Supabase client configuration (no live DB required)."""

from unittest.mock import MagicMock, patch


class TestSupabaseClientConfiguration:
    def test_client_factory_exists(self):
        """Verify the supabase module is importable."""
        from app.core import supabase as supabase_module

        assert hasattr(supabase_module, "get_supabase_client")
        assert hasattr(supabase_module, "get_supabase_anon_client")

    def test_client_warns_when_unconfigured(self, caplog):
        """When credentials are empty, the factory should log a warning."""
        import logging

        from app.core.supabase import get_supabase_client

        # Clear LRU cache so the function runs fresh
        get_supabase_client.cache_clear()

        with patch("app.core.supabase.get_settings") as mock_settings, \
             patch("app.core.supabase.create_client") as mock_create:

            mock_settings.return_value = MagicMock(
                SUPABASE_URL="",
                SUPABASE_SERVICE_ROLE_KEY="",
                SUPABASE_ANON_KEY="",
            )
            mock_create.return_value = MagicMock()

            with caplog.at_level(logging.WARNING, logger="researchly"):
                get_supabase_client()

        assert any("not configured" in r.message for r in caplog.records)
        get_supabase_client.cache_clear()

    def test_migration_files_exist(self):
        """Verify every migration file in the directory is present and non-empty."""
        from pathlib import Path

        migrations_dir = Path(__file__).parents[3] / "supabase" / "migrations"
        assert migrations_dir.exists(), f"Migration directory missing: {migrations_dir}"

        # Not a fixed list: the point is that whatever is committed is
        # readable and substantive, so a new migration is covered the
        # moment it is added rather than after a test edit.
        files = sorted(migrations_dir.glob("*.sql"))
        assert files, "no migration files found"

        for path in files:
            assert (
                path.stat().st_size > 100
            ), f"Migration file too small (likely empty): {path.name}"

    def test_migration_schema_has_vector_extension(self):
        """Verify the schema migration enables pgvector."""
        from pathlib import Path

        schema_sql = (
            Path(__file__).parents[3]
            / "supabase"
            / "migrations"
            / "20260923000001_initial_schema.sql"
        ).read_text()

        assert 'create extension if not exists "vector"' in schema_sql
        assert "vector(768)" in schema_sql
        assert "match_paper_chunks" in schema_sql

    def test_migration_rls_has_all_tables(self):
        """Verify RLS policies cover every protected table."""
        from pathlib import Path

        rls_sql = (
            Path(__file__).parents[3]
            / "supabase"
            / "migrations"
            / "20260923000002_rls_policies.sql"
        ).read_text()

        tables = ["profiles", "papers", "paper_chunks", "conversations", "messages", "citations"]
        for table in tables:
            assert (
                "enable row level security" in rls_sql
            ), f"RLS not enabled for {table}"
            assert table in rls_sql, f"Table {table} not mentioned in RLS policies"

    def test_storage_migration_has_bucket(self):
        """The bucket policies must guard the bucket the code writes to.

        Asserting the literal 'research-papers' here is what let a real
        defect through: the migration guarded that bucket while the
        application used BUCKET = 'papers', so every policy evaluated
        against objects the app never created.
        """
        from pathlib import Path

        from app.core.storage import BUCKET

        storage_sql = (
            Path(__file__).parents[3]
            / "supabase"
            / "migrations"
            / "20260923000003_storage.sql"
        ).read_text()
        security_sql = (
            Path(__file__).parents[3]
            / "supabase"
            / "migrations"
            / "20260927000003_security_fixes.sql"
        ).read_text()

        # The original migration provisions the bucket the app uses.
        assert f"'{BUCKET}'" in storage_sql or f"'{BUCKET}'" in security_sql
        # The corrective migration repoints the policies at it.
        assert f"bucket_id = '{BUCKET}'" in security_sql
        assert "application/pdf" in storage_sql
