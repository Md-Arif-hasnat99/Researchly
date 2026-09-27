"""Per-request correlation context.

A request id is generated (or accepted from the caller) at the edge of the
application and attached to every log line produced while handling that
request, so a user reporting "it broke" with a reference id can be matched
to the exact stack trace in the logs, and one slow or failing request can
be followed across modules instead of guessed at from timestamps.
"""

import re
from contextvars import ContextVar, Token
from uuid import uuid4

_request_id: ContextVar[str] = ContextVar("request_id", default="-")

#: A caller-supplied id is accepted only when it is a plain bounded token.
#: It is written into log files, so anything outside this shape is
#: replaced rather than trusted.
_ID_PATTERN = re.compile(r"\A[A-Za-z0-9_.:-]{1,64}\Z")


def new_request_id() -> str:
    return uuid4().hex[:16]


def resolve_request_id(candidate: str | None) -> str:
    """Use *candidate* if it is a safe token, otherwise mint a new id."""
    if isinstance(candidate, str) and _ID_PATTERN.match(candidate):
        return candidate
    return new_request_id()


def set_request_id(request_id: str) -> Token:
    return _request_id.set(request_id)


def reset_request_id(token: Token) -> None:
    _request_id.reset(token)


def get_request_id() -> str:
    """Current request id, or ``-`` outside a request."""
    return _request_id.get()
