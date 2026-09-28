"""Turning internal failures into text that is safe to show a user.

Two channels carry exception text outward today: the ``error_message``
column on a paper (read back by ``GET /api/papers/{id}`` and rendered in
the library view) and the ``detail``/``message`` of an HTTP error. Both
end up in front of a browser, and both are built from strings that were
never written to be public: a storage path, a driver's message, a
library's parse error for a file the user chose to upload.

The rule applied here is narrow on purpose. These strings are *useful* —
"this file is password protected" is the difference between a user
retrying with a different PDF and a support ticket — so they are not
replaced wholesale with a generic sentence. What is removed is the part
that is about the server rather than the request: filesystem and URL
paths, and credential-shaped tokens. Anything reaching this function
has already been logged with its traceback, so nothing is lost
operationally by scrubbing the copy that ships to the client.
"""

import re

#: A filesystem or URL path: a slash-led run of path-ish characters.
_PATH_LIKE = re.compile(r"(?:[a-zA-Z]:)?[/\\][\w.\-]+(?:[/\\][\w.\-]*)+")

#: Credential-shaped blobs. A Supabase or JWT-style token is a long run
#: of base64url segments; keys pasted into a log by a misconfiguration
#: tend to look the same.
_TOKEN_LIKE = re.compile(r"\b(?:eyJ|sk-|sb_)[A-Za-z0-9_\-.]{16,}")

_MAX_LENGTH = 500


def safe_error_message(
    exc: BaseException | str,
    *,
    fallback: str = "Processing failed for an internal reason.",
    max_length: int = _MAX_LENGTH,
) -> str:
    """Return a scrubbed, length-capped description of *exc*.

    Only the first line is kept: a traceback's later lines describe
    internals, and the first line is the part that names the problem.
    """
    raw = str(exc)
    if not raw.strip():
        return fallback

    first_line = raw.strip().splitlines()[0]
    scrubbed = _TOKEN_LIKE.sub("<redacted>", first_line)
    scrubbed = _PATH_LIKE.sub("<path>", scrubbed)
    # Collapse the runs of whitespace that path removal tends to leave.
    scrubbed = " ".join(scrubbed.split())

    if not scrubbed:
        return fallback
    return scrubbed[:max_length]


def ai_rate_limit_retry_after(exc: BaseException) -> int | None:
    """Retry-After seconds when *exc* is a Gemini quota/throughput failure, else None.

    google-genai raises ClientError with code 429 for both per-minute
    throughput limits and the free tier's daily request quota. The
    provider's own RetryInfo ("Please retry in 34.3s") is the only
    number that knows which limit was hit, so it is read first and a
    60s floor is used when it is absent. Code 503 (overloaded) is also
    treated as a capacity error with a 60s fallback.
    """
    import math
    code = getattr(exc, "code", None)
    if not isinstance(code, int):
        # openai/groq errors (used by the fallback) carry the HTTP status
        # on .status_code; their .code, when present, is a string like
        # "model_not_found" and must not be mistaken for a status.
        status = getattr(exc, "status_code", None)
        code = status if isinstance(status, int) else None
    if code == 429:
        # Provider message contains "Please retry in 34.3s." — extract it.
        m = re.search(r"retry in (\d+(?:\.\d+)?)s", str(exc), re.IGNORECASE)
        if m:
            return max(1, math.ceil(float(m.group(1))) + 1)
        return 60
    if code == 503:
        return 60
    return None
