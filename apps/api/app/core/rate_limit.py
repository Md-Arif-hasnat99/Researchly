"""Inbound rate limiting.

Nothing in the API was metered before this: every authenticated endpoint
was callable without limit, and four of them spend money on Gemini (a
generation, a rerank, an embedding) or on a 50 MB upload. A single script
looping ``POST /api/chat`` burns the project's quota, and a single script
looping ``POST /api/papers`` fills the bucket. The limiter here is what
turns that from a bill into a 429.

**Sliding window, in process.** Each key keeps the timestamps of its
requests inside the window, and a request is allowed when fewer than the
limit remain. Chosen over a fixed window because a fixed window lets a
caller send 2x the limit across a window boundary, and over a token
bucket because "how many in the last 60 seconds" is the question an
operator actually asks.

Two costs of the in-process design, stated plainly:

- **One process means one counter.** Behind more than one worker the
  effective limit is the limit times the worker count. The fix is a
  shared store (Redis), not a change to the middleware.
- **Memory is bounded by pruning, not by a hard cap.** Keys are dropped
  when their window empties, so idle clients cost nothing; a caller
  rotating client addresses can still grow the table, which is what the
  proxy in front of the app is for.

Client identity is the socket address, which is the only value the app
can trust without doing authentication work twice. ``X-Forwarded-For`` is
read only when ``TRUST_PROXY_HEADERS`` is set, because a header the
caller can choose is a header the caller can use to get a fresh budget.
"""

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings

logger = logging.getLogger("researchly")

#: Paths that must never be metered. A liveness probe that gets a 429
#: takes the instance out of rotation, which turns a rate limit into an
#: outage.
EXEMPT_PATHS = frozenset({"/api/health", "/api/health/ready"})

#: The endpoints that cost money or bandwidth get their own budget
#: instead of the general one. Matched as prefixes so a new sub-route
#: cannot escape the limit by adding a path segment.
EXPENSIVE_PREFIXES = (
    "/api/chat",
    "/api/papers",
)

#: How many checks between sweeps for idle keys. Amortized cleanup: a
#: full sweep is O(keys), and paying it on every request is wasteful.
_PRUNE_EVERY = 64


@dataclass(frozen=True)
class Decision:
    """The outcome of one limit check, and enough detail to answer with."""

    allowed: bool
    limit: int
    remaining: int
    #: Seconds until the oldest request in the window expires. 0 when
    #: the request was allowed.
    retry_after: int
    #: Unix timestamp at which the window frees up a slot.
    reset_at: int


class SlidingWindowLimiter:
    """Count requests per key within a rolling window."""

    def __init__(
        self,
        limit: int,
        window_seconds: int,
        *,
        time_func=time.monotonic,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._time = time_func
        # A key's request timestamps, oldest first. Ordered so the least
        # recently used key can be evicted when the table is full.
        self._hits: OrderedDict[str, list[float]] = OrderedDict()
        self._checks = 0

    def _prune(self, cutoff: float) -> None:
        """Drop keys whose every request has aged out.

        Called periodically rather than per request: a full sweep is
        O(keys), and a keyspace is small, but paying it on every call
        would be wasteful. The counter keeps idle clients from costing
        memory without adding per-request overhead.
        """
        stale = [key for key, hits in self._hits.items() if not any(s > cutoff for s in hits)]
        for key in stale:
            del self._hits[key]

    def check(self, key: str) -> Decision:
        now = self._time()
        cutoff = now - self.window_seconds

        # Amortized cleanup of idle keys.
        self._checks += 1
        if self._checks % _PRUNE_EVERY == 0:
            self._prune(cutoff)

        hits = self._hits.get(key)
        if hits is None:
            hits = []
            self._hits[key] = hits
        else:
            self._hits.move_to_end(key)

        # Drop what has aged out. This is also the only thing that frees
        # memory: a key with no recent requests is removed outright.
        if hits:
            fresh = [stamp for stamp in hits if stamp > cutoff]
        else:
            fresh = []
        if not fresh:
            self._hits.pop(key, None)

        if len(fresh) >= self.limit:
            retry_after = max(1, int(fresh[0] - cutoff) + 1)
            return Decision(
                allowed=False,
                limit=self.limit,
                remaining=0,
                retry_after=retry_after,
                reset_at=int(time.time() + retry_after),
            )

        fresh.append(now)
        self._hits[key] = fresh
        return Decision(
            allowed=True,
            limit=self.limit,
            remaining=self.limit - len(fresh),
            retry_after=0,
            reset_at=int(now + self.window_seconds),
        )

    def reset(self) -> None:
        """Forget every key. Used by tests, and by an operator hook."""
        self._hits.clear()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Reject a client that sends more requests than its budget allows.

    A 429 answers with the same error envelope as every other failure, so
    the frontend needs no special case to show it, and carries
    ``Retry-After`` plus the usual ``X-RateLimit-*`` trio for anything
    that wants to back off properly.
    """

    def __init__(self, app, *, general=None, expensive=None, clock=None) -> None:
        super().__init__(app)
        settings = get_settings()
        self.enabled = settings.RATE_LIMIT_ENABLED
        self.general = general or SlidingWindowLimiter(
            settings.RATE_LIMIT_REQUESTS,
            settings.RATE_LIMIT_WINDOW_SECONDS,
            time_func=clock or time.monotonic,
        )
        self.expensive = expensive or SlidingWindowLimiter(
            settings.RATE_LIMIT_AI_REQUESTS,
            settings.RATE_LIMIT_AI_WINDOW_SECONDS,
            time_func=clock or time.monotonic,
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.enabled or self._is_exempt(request):
            return await call_next(request)

        # A CORS preflight is not the client's request; it is the browser
        # asking whether the real one is allowed. Metering it would let a
        # single page load exhaust the budget.
        if request.method == "OPTIONS":
            return await call_next(request)

        decision = self._limiter_for(request).check(self._client_key(request))
        if not decision.allowed:
            return self._too_many_requests(decision)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(decision.limit)
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        response.headers["X-RateLimit-Reset"] = str(decision.reset_at)
        return response

    @staticmethod
    def _is_exempt(request: Request) -> bool:
        return request.url.path in EXEMPT_PATHS

    def _limiter_for(self, request: Request) -> SlidingWindowLimiter:
        """Pick the budget this request spends from."""
        if request.url.path.startswith(EXPENSIVE_PREFIXES):
            return self.expensive
        return self.general

    def _client_key(self, request: Request) -> str:
        """Identify the caller for counting purposes only.

        This is not authentication and grants no access; it only decides
        whose bucket a request is charged to. The socket address is the
        honest answer, and the forwarded header is honoured solely when
        the deployment declares that a proxy overwrites it.
        """
        if get_settings().TRUST_PROXY_HEADERS:
            forwarded = request.headers.get("X-Forwarded-For", "")
            client_ip = forwarded.split(",")[0].strip() or (
                request.client.host if request.client else "unknown"
            )
        else:
            client_ip = request.client.host if request.client else "unknown"
        return client_ip or "unknown"

    @staticmethod
    def _too_many_requests(decision: Decision) -> JSONResponse:
        response = JSONResponse(
            status_code=429,
            content={
                "error": {
                    "code": "TOO_MANY_REQUESTS",
                    "message": (
                        "Too many requests. Please wait a moment before trying again."
                    ),
                }
            },
            headers={
                "Retry-After": str(decision.retry_after),
                "X-RateLimit-Limit": str(decision.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(decision.reset_at),
            },
        )
        logger.warning(
            "rate limit exceeded | limit=%d retry_after=%ds", decision.limit, decision.retry_after
        )
        return response
