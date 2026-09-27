"""Tests for the logging stream wrapper (no live services required)."""

import logging

import pytest

from app.core.logging import SafeStream, setup_logging


class _NarrowStream:
    """A cp1252 console, which cannot represent most of the world's text."""

    encoding = "cp1252"

    def __init__(self) -> None:
        self.written: list[str] = []

    def write(self, text: str) -> int:
        text.encode("cp1252")
        self.written.append(text)
        return len(text)

    def flush(self) -> None:
        pass


class TestSafeStream:
    def test_passes_through_encodable_text(self):
        stream = _NarrowStream()
        assert SafeStream(stream).write("hello") == 5
        assert "".join(stream.written) == "hello"

    def test_replaces_characters_the_console_cannot_encode(self):
        """A question in any language must not raise mid-log."""
        stream = _NarrowStream()
        SafeStream(stream).write("factor θ and →")
        # cp1252 renders both characters as its replacement character while
        # the rest of the message survives.
        assert "".join(stream.written) == "factor ? and ?"

    def test_does_not_raise_for_unknown_encoding(self):
        class _Weird:
            encoding = "not-a-real-codec"

            def __init__(self) -> None:
                self.written: list[str] = []

            def write(self, text: str) -> int:
                self.written.append(text)
                return len(text)

            def flush(self) -> None:
                pass

        stream = _Weird()
        SafeStream(stream).write("θ")
        assert len(stream.written) == 1

    def test_missing_encoding_attribute_defaults_to_utf8(self):
        class _Bare:
            def __init__(self) -> None:
                self.written: list[str] = []

            def write(self, text: str) -> int:
                self.written.append(text)
                return len(text)

            def flush(self) -> None:
                pass

        bare = _Bare()
        stream = SafeStream(bare)
        assert stream.encoding == "utf-8"
        assert stream.write("θ") == 1
        assert bare.written == ["θ"]

    def test_flush_is_forwarded_when_available(self):
        class _NoFlush:
            encoding = "utf-8"

            def write(self, text: str) -> int:
                return len(text)

        SafeStream(_NoFlush()).flush()  # must not raise


class TestSetupLogging:
    def test_handler_does_not_raise_on_non_ascii(self):
        """The end-to-end path: a log call with a Unicode question."""
        logger = logging.getLogger("researchly.test-nonascii")
        logger.handlers.clear()
        logger.propagate = False
        stream = _NarrowStream()
        handler = logging.StreamHandler(SafeStream(stream))
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("Evaluating case %s: %r", "c1", "Wie groß ist θ?")
        for handler_to_close in list(logger.handlers):
            handler_to_close.close()
        logger.handlers.clear()

        printed = "".join(stream.written)
        assert "Evaluating case c1" in printed

    def test_setup_logging_is_idempotent(self):
        """Repeated setup must not stack duplicate handlers."""
        logger = setup_logging()
        count = len(logger.handlers)
        again = setup_logging()
        assert again is logger
        assert len(again.handlers) == count
        assert count >= 1

    def test_respects_level(self):
        logger = setup_logging("WARNING")
        assert logger.level == logging.WARNING


@pytest.mark.parametrize("level", ["info", "nonsense"])
def test_unknown_level_falls_back_to_info(level):
    logger = setup_logging(level)
    assert logger.level == logging.INFO
