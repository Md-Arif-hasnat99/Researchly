"""HTTP request logging and correlation.

Every request gets a request id — minted here, or taken from a caller's
``X-Request-ID`` when it is a safe token — which is attached to every log
line produced while handling it, echoed in the response header, and
included in the unhandled-error log. A user who reports a failed request
can quote the id from the response, and that id leads to the stack trace.

One line per request with method, path, status and duration is the
minimum an operator needs to answer "is anything failing?" and "what got
slow?" without a full tracing stack. Deliberate exclusions:

- **Bodies, query strings and headers are never logged.** They carry
  PDFs, questions about a user's research, and tokens. The path alone
  identifies the operation.
- **Health probes log at DEBUG**, so a probe every five seconds does not
  drown real traffic.

4xx responses are logged at INFO: they are usually the caller's doing
(user not signed in, validation failed) and are normal traffic. 5xx is
ERROR, because that is the server failing.

The request id travels in the log record's ``request_id`` attribute (see
the filter in :mod:`app.core.logging`) rather than in the message, so
every log line emitted while the request is in flight carries it, not
just these summary lines.
"""

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.request_context import (
    reset_request_id,
    resolve_request_id,
    set_request_id,
)

logger = logging.getLogger("researchly")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Attach a request id to the request and log one line per request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = resolve_request_id(request.headers.get("X-Request-ID"))
        # Also stored on the shared ASGI scope: the unhandled-error
        # handler sits outside this middleware, where the context
        # variable has already been reset, and still needs the id.
        request.state.request_id = request_id
        token = set_request_id(request_id)
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001
            # The registered exception handler logs the traceback; this
            # line is the request summary, carrying the same request id.
            self._log(
                request,
                status_code=500,
                duration_ms=(time.perf_counter() - started) * 1000,
                error=type(exc).__name__,
            )
            raise
        else:
            # Before the finally below resets the context variable, so
            # this line and everything logged during the request agree
            # on the id.
            response.headers["X-Request-ID"] = request_id
            self._log(
                request,
                status_code=response.status_code,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            return response
        finally:
            reset_request_id(token)

    @staticmethod
    def _log(
        request: Request,
        *,
        status_code: int,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        # The path only: query strings and bodies are not logged.
        path = request.url.path
        if path.endswith("/health") or path.endswith("/health/ready"):
            level = logging.DEBUG
        elif status_code >= 500:
            level = logging.ERROR
        else:
            level = logging.INFO
        logger.log(
            level,
            "request | %s %s status=%d duration_ms=%.1f%s",
            request.method,
            path,
            status_code,
            duration_ms,
            f" error={error}" if error else "",
        )
