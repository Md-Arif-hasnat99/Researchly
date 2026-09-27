"""Exponential backoff for calls to external services.

FR-05 requires retrying transient failures, but only the embedding path
did. Every other Gemini call (chat answers, reranking, comparison,
literature review, gap analysis) failed the user's request outright on a
single 429 or dropped connection, so one rate-limit window turned into
one lost answer. This module is the one place that decides what
"transient" means.

Two rules shape it:

**Only transient failures are retried.** A 403 from a bad API key, an
invalid argument, or a validation error will fail identically on every
attempt; burning three more seconds and three more quota units to reach
the same conclusion delays the real error and hides it. FR-05 says
retry *transient* failures, so anything else raises immediately.

**Backoff is bounded and logged.** Each failure waits ``base_delay``
doubled, and every retry is logged with its attempt number and the
exception, so a service that is flapping is visible in the logs rather
than appearing only as a slow request.

Retries are not free: a retried chat answer can cost a second request.
That is still cheaper than failing the user's request outright, which
is the alternative here.
"""

import logging
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger("researchly")

T = TypeVar("T")

#: HTTP statuses a caller should try again: request timeout, rate limit
#: and the gateway/server errors a proxy can produce while a backend is
#: briefly unhealthy.
_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})

#: Exception class names (matched across the MRO so subclasses count)
#: raised when a request never reached the server or was cut off.
#: ``google.genai`` wraps transport failures in these httpx types.
_TRANSIENT_CLASS_NAMES = frozenset(
    {
        "TimeoutError",
        "ConnectionError",
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "TimeoutException",
        "NetworkError",
        "RemoteProtocolError",
        "ProtocolError",
        "ServiceUnavailable",
    }
)


def is_transient(exc: BaseException) -> bool:
    """Whether *exc* describes a failure worth attempting again.

    Deliberately explicit rather than ``except Exception: retry``: the
    answer to "should I retry?" should be readable, and a predicate
    that is wrong in one direction loses a request while the other
    wastes quota. Matching is by status code or by the transport error
    classes that mean the request never got an answer.
    """
    code = getattr(exc, "code", None)
    if isinstance(code, int) and code in _TRANSIENT_STATUS_CODES:
        return True
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    names = {cls.__name__ for cls in type(exc).__mro__}
    return bool(names & _TRANSIENT_CLASS_NAMES)


def with_retry(
    fn: Callable[[], T],
    *,
    retries: int = 3,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] | None = None,
    retry_on: Callable[[BaseException], bool] = is_transient,
    label: str = "external call",
) -> T:
    """Call *fn()* with exponential backoff on transient failures.

    Up to ``retries + 1`` attempts, waiting ``base_delay`` then doubling
    between them. A non-transient failure, or the final attempt failing,
    raises the exception unchanged.

    Args:
        fn:        Zero-argument call. A lambda closes over arguments.
        retries:   Extra attempts after the first.
        base_delay: Delay before the first retry, in seconds.
        sleep:     Injected in tests so they do not actually wait.
            Resolved at call time when omitted, so patching
            ``time.sleep`` in a test also covers call sites that do not
            pass a sleeper of their own.
        retry_on:  Predicate deciding whether an exception is transient.
        label:     Used in the retry log line.

    Raises:
        Exception: the last failure, once retries are exhausted or the
            failure is not transient.
    """
    if sleep is None:
        sleep = time.sleep
    delay = base_delay
    attempts = retries + 1
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not retry_on(exc):
                raise
            if attempt + 1 >= attempts:
                break
            logger.warning(
                "%s failed (attempt %d/%d, %s: %s). Retrying in %.1fs",
                label,
                attempt + 1,
                attempts,
                type(exc).__name__,
                exc,
                delay,
            )
            sleep(delay)
            delay *= 2
    raise last_exc  # type: ignore[misc]
