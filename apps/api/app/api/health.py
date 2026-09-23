from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.health import HealthResponse

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    """Return system operational status and configured dependencies."""
    settings = get_settings()
    deps = {
        "gemini": "configured" if settings.GEMINI_API_KEY else "unconfigured",
        "supabase": "configured" if settings.SUPABASE_URL else "unconfigured",
    }
    return HealthResponse(
        status="ok",
        version=settings.VERSION,
        service="researchly-api",
        dependencies=deps,
    )
