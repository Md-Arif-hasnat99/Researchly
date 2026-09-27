import asyncio

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.schemas.health import HealthResponse

router = APIRouter(prefix="/health", tags=["Health"])

#: Hard bound on each dependency probe. A health check that can hang is
#: worse than no health check: it pins a worker and reports nothing.
CHECK_TIMEOUT_S = 3.0


@router.get("", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    """Liveness: is this process up and configured.

    Touches no network. Use it as a process/uptime probe.
    """
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


async def _probe(url: str, headers: dict[str, str] | None = None) -> str:
    """Reach *url* and report what was found.

    Any HTTP answer means the dependency is reachable; only a transport
    failure, timeout, or 5xx counts as unreachable. A 401 is reported
    separately from "unreachable" because it means the service is up and
    the credentials are wrong — a different, more specific failure for an
    operator to act on.
    """
    try:
        async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_S) as client:
            response = await client.get(url, headers=headers)
    except (httpx.HTTPError, OSError):
        return "unreachable"
    if response.status_code == 200:
        return "reachable"
    if 400 <= response.status_code < 500:
        return f"unhealthy ({response.status_code})"
    return "unreachable"


async def check_supabase() -> str:
    """Probe Supabase the way the application actually talks to it.

    The root ``/rest/v1/`` endpoint serves PostgREST's schema document,
    and projects can (and this one does) answer 401 there for a key that
    is perfectly valid for data queries. Probing the root would report a
    healthy deployment as broken, so the probe runs the same kind of
    trivial read the app performs instead: a one-row query that exercises
    URL, credentials, PostgREST and the database together.
    """
    settings = get_settings()
    if not settings.SUPABASE_URL:
        return "unconfigured"
    return await _probe(
        f"{settings.SUPABASE_URL.rstrip('/')}/rest/v1/papers?select=id&limit=1",
        headers={"apikey": settings.SUPABASE_ANON_KEY or ""},
    )


async def check_gemini() -> str:
    """Probe Gemini for the models this process will actually call.

    Listing ``/models`` is not enough: that endpoint answers 200 as long
    as the *key* works, so it stayed green while every generation and
    embedding call 404'd on a model Google had retired — the deployment
    looked healthy and every request failed. This asks for the configured
    models by name, which is the thing that has to exist.
    """
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        return "unconfigured"

    headers = {"x-goog-api-key": settings.GEMINI_API_KEY}
    for model in (
        settings.GEMINI_GENERATION_MODEL,
        settings.GEMINI_EMBEDDING_MODEL,
    ):
        # The API expects the bare "models/<id>" path segment.
        name = model.split("/")[-1]
        state = await _probe(
            f"https://generativelanguage.googleapis.com/v1beta/models/{name}",
            headers=headers,
        )
        if state != "reachable":
            return f"{state} ({name})"

    return "reachable"


@router.get("/ready", response_model=HealthResponse)
async def get_readiness() -> JSONResponse:
    """Readiness: can this process actually serve requests right now.

    Probes both dependencies in parallel with a hard timeout, and returns
    503 when they cannot be used, so a deployment or load balancer stops
    routing traffic instead of feeding every request to a process whose
    database is gone.

    Supabase is required: without it every endpoint fails. Gemini being
    unconfigured is *not* a readiness failure, because the pipeline still
    serves fallback answers and retrieval-only features without it — but
    Gemini being configured and unreachable is, since configured implies
    the deployment expects generation to work.
    """
    supabase_state, gemini_state = await asyncio.gather(check_supabase(), check_gemini())

    degraded: list[str] = []
    if supabase_state != "reachable":
        degraded.append("supabase")
    if gemini_state not in {"reachable", "unconfigured"}:
        degraded.append("gemini")

    status = "ok" if not degraded else "degraded"
    payload = HealthResponse(
        status=status,
        version=get_settings().VERSION,
        service="researchly-api",
        dependencies={"supabase": supabase_state, "gemini": gemini_state},
    )
    # 503 for degraded so an orchestrator treats it as not ready; the body
    # still says which dependency failed, because a bare 503 explains
    # nothing when someone is debugging at 3am.
    return JSONResponse(
        status_code=503 if degraded else 200,
        content=payload.model_dump(),
    )
