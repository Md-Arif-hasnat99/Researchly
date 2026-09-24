"""Tests for the papers API endpoints."""

import io
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AUTH_HEADERS = {"Authorization": "Bearer dev-token"}

_PAPER_ROW = {
    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "user_id": "00000000-0000-0000-0000-000000000000",
    "title": "attention is all you need",
    "authors": [],
    "abstract": None,
    "publication_year": None,
    "file_path": "00000000-0000-0000-0000-000000000000/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.pdf",
    "file_size": 1024,
    "total_pages": None,
    "status": "uploaded",
    "error_message": None,
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-01T00:00:00+00:00",
}


def _make_pdf(size: int = 1024) -> bytes:
    return b"%PDF-1.4 " + b"x" * (size - 9)


# ---------------------------------------------------------------------------
# Upload tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_rejects_non_pdf():
    """Non-PDF files must be rejected with 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/papers",
            headers=AUTH_HEADERS,
            files={"file": ("report.txt", b"hello world", "text/plain")},
        )
    assert response.status_code == 422
    assert "PDF" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_rejects_oversized_pdf():
    """Files larger than 50 MB must be rejected with 413."""
    fifty_mb_plus = _make_pdf(50 * 1024 * 1024 + 1)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/papers",
            headers=AUTH_HEADERS,
            files={"file": ("big.pdf", io.BytesIO(fifty_mb_plus), "application/pdf")},
        )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_upload_success():
    """Valid PDF upload should return 201 with paper data."""
    mock_result = MagicMock()
    mock_result.data = [_PAPER_ROW]

    with (
        patch("app.api.papers.upload_paper"),
        patch("app.api.papers.get_supabase_client") as mock_client,
    ):
        mock_table = MagicMock()
        mock_client.return_value.table.return_value = mock_table
        mock_table.insert.return_value.execute.return_value = mock_result

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/papers",
                headers=AUTH_HEADERS,
                files={"file": ("paper.pdf", io.BytesIO(_make_pdf()), "application/pdf")},
            )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "uploaded"
    assert data["title"] == "attention is all you need"


# ---------------------------------------------------------------------------
# List tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_papers_returns_only_users_papers():
    """GET /api/papers should return the authenticated user's papers."""
    mock_result = MagicMock()
    mock_result.data = [_PAPER_ROW]

    with patch("app.api.papers.get_supabase_client") as mock_client:
        mock_table = MagicMock()
        mock_client.return_value.table.return_value = mock_table
        mock_table.select.return_value.eq.return_value.order.return_value.execute.return_value = (
            mock_result
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/papers", headers=AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["papers"][0]["id"] == _PAPER_ROW["id"]


# ---------------------------------------------------------------------------
# Delete tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_paper_success():
    """DELETE /api/papers/{id} should return 204 on success."""
    mock_fetch = MagicMock()
    mock_fetch.data = {"id": _PAPER_ROW["id"], "file_path": _PAPER_ROW["file_path"]}

    mock_delete = MagicMock()
    mock_delete.data = None

    with (
        patch("app.api.papers.delete_paper_from_storage"),
        patch("app.api.papers.get_supabase_client") as mock_client,
    ):
        mock_table = MagicMock()
        mock_client.return_value.table.return_value = mock_table
        select_chain = mock_table.select.return_value
        select_chain.eq.return_value.eq.return_value.single.return_value.execute.return_value = (
            mock_fetch
        )
        # Second call: delete
        mock_table.delete.return_value.eq.return_value.execute.return_value = mock_delete

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete(
                f"/api/papers/{_PAPER_ROW['id']}", headers=AUTH_HEADERS
            )

    assert response.status_code == 204


@pytest.mark.asyncio
async def test_delete_paper_not_found():
    """DELETE on a non-existent paper must return 404."""
    with patch("app.api.papers.get_supabase_client") as mock_client:
        mock_table = MagicMock()
        mock_client.return_value.table.return_value = mock_table
        select_chain = mock_table.select.return_value
        select_chain.eq.return_value.eq.return_value.single.return_value.execute.side_effect = (
            Exception("not found")
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete(
                "/api/papers/00000000-0000-0000-0000-000000000001", headers=AUTH_HEADERS
            )

    assert response.status_code == 404
