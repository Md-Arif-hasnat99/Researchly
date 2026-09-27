from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.papers import router as papers_router
from app.api.research import router as research_router
from app.api.search import router as search_router
from app.core.config import get_settings
from app.core.logging import logger
from app.core.middleware import RequestLoggingMiddleware

#: Machine-readable codes for the HTTP statuses the API raises itself.
#: Routes pass a code when it is more specific than the status default.
_HTTP_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_REQUESTS",
    500: "INTERNAL_SERVER_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
    504: "GATEWAY_TIMEOUT",
}


def _error_payload(status_code: int, message: str, code: str | None = None) -> dict:
    """The one error body every response uses.

    ``detail`` (FastAPI's default) and a bare ``{"error": {...}}`` both
    existed before, so the frontend had to guess which a given response
    carried — and 500s went out in the second shape, which the client did
    not read, leaving users with a bare status text instead of a message.
    """
    return {"error": {"code": code or _HTTP_CODES.get(status_code, "ERROR"), "message": message}}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info(f"Starting {settings.PROJECT_NAME} v{settings.VERSION} [{settings.ENVIRONMENT}]")
    yield
    logger.info(f"Shutting down {settings.PROJECT_NAME}")


def create_application() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description="Backend API for Researchly AI Research Assistant",
        lifespan=lifespan,
    )

    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # Let the browser read the correlation id so a failed request can
        # be reported with it.
        expose_headers=["X-Request-ID"],
    )

    # Request id + one log line per request (added last: outermost, so it
    # also sees requests that fail before reaching a route).
    app.add_middleware(RequestLoggingMiddleware)

    # Registered against Starlette's class, not FastAPI's subclass, so
    # one handler covers both: routes raise fastapi.HTTPException, while
    # the router raises starlette's own for unmatched paths (the 404 you
    # get for a URL that does not exist). The status-code keys override
    # FastAPI's built-in 404/405 handlers, which answer in `detail`.
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ):
        detail = exc.detail
        if isinstance(detail, dict) and "message" in detail:
            code = detail.get("code")
            message = str(detail["message"])
        else:
            code = None
            message = str(detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(exc.status_code, message, code),
            headers=getattr(exc, "headers", None),
        )

    app.add_exception_handler(404, http_exception_handler)
    app.add_exception_handler(405, http_exception_handler)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        # The default handler echoes the whole error list, which is a wall
        # of raw dict output. This keeps the first few field errors, in an
        # order a person can act on: which field, what is wrong with it.
        # 422 is spelled out because fastapi's status constants for it
        # have been renamed across releases, and this pin allows either.
        errors = exc.errors()
        parts: list[str] = []
        for err in errors[:5]:
            location = ".".join(str(item) for item in err.get("loc", ()) if item != "body")
            message = str(err.get("msg", "invalid value"))
            parts.append(f"{location}: {message}" if location else message)
        if len(errors) > 5:
            parts.append(f"and {len(errors) - 5} more")
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                422,
                "Request validation failed: " + "; ".join(parts),
            ),
        )

    # Global Exception Handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        # exc_info is not optional here: without a traceback this log line
        # is a symptom with no cause, and the request id in the format is
        # what ties it to the request summary logged by the middleware.
        # The id is read off the shared ASGI scope because the middleware
        # that owns the context variable has already unwound.
        request_id = getattr(request.state, "request_id", "-")
        logger.error(
            "Unhandled error processing %s %s | request_id=%s: %s",
            request.method,
            request.url.path,
            request_id,
            exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_payload(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An unexpected server error occurred.",
            ),
            # The request id must reach the client even here: a 500 is
            # exactly when someone needs the reference, and this response
            # is built outside the middleware that sets the header on
            # every other response.
            headers={"X-Request-ID": request_id},
        )

    # Mount API routers under /api
    app.include_router(health_router, prefix=settings.API_V1_STR)
    app.include_router(auth_router, prefix=settings.API_V1_STR)
    app.include_router(papers_router, prefix=settings.API_V1_STR)
    app.include_router(search_router, prefix=settings.API_V1_STR)
    app.include_router(chat_router, prefix=settings.API_V1_STR)
    app.include_router(research_router, prefix=settings.API_V1_STR)

    return app


app = create_application()
