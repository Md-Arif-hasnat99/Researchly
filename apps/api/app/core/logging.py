import logging
import sys


class SafeStream:
    """Text stream that degrades unencodable characters instead of raising.

    Log records routinely carry user text: a question typed in any
    language, a paper title with accents, a Greek letter lifted from a
    formula. On a Windows console the default encoding is cp1252, and
    writing those characters raises UnicodeEncodeError inside the
    handler. logging swallows that, so the request survives, but the
    record is lost and a full traceback is dumped to stderr for every
    such line -- which buries the errors worth reading and can flood a
    log on a busy server.
    """

    def __init__(self, stream) -> None:
        self._stream = stream

    @property
    def encoding(self) -> str:
        return getattr(self._stream, "encoding", None) or "utf-8"

    def write(self, text: str) -> int:
        try:
            return self._stream.write(text)
        except UnicodeEncodeError:
            pass
        # The console's own encoding first, so unrepresentable characters
        # degrade to its replacement character; then ASCII, which every
        # codec can encode. utf-8 is deliberately not tried: a stream that
        # accepts utf-8 would have accepted the text unchanged above.
        for encoding in (self.encoding, "ascii"):
            try:
                safe = text.encode(encoding, "replace").decode(encoding, "replace")
            except LookupError:
                continue
            try:
                return self._stream.write(safe)
            except UnicodeEncodeError:
                continue
        return len(text)

    def flush(self) -> None:
        flush = getattr(self._stream, "flush", None)
        if flush is not None:
            flush()


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure structured console logging for the application."""
    logger = logging.getLogger("researchly")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        handler = logging.StreamHandler(SafeStream(sys.stdout))
        handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


logger = setup_logging()
