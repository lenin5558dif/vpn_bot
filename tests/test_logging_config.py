import json
import logging
import os
from unittest.mock import patch

import pytest


def test_setup_logging_default():
    from app.logging_config import setup_logging
    setup_logging()
    logger = logging.getLogger("app")
    assert logger.level == logging.INFO


def test_setup_logging_custom_level():
    from app.logging_config import setup_logging
    with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
        setup_logging()
    logger = logging.getLogger("app")
    assert logger.level == logging.DEBUG


def test_json_formatter():
    from app.logging_config import JSONFormatter
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="test.py",
        lineno=1, msg="hello %s", args=("world",), exc_info=None,
    )
    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["message"] == "hello world"
    assert parsed["level"] == "INFO"
    assert "timestamp" in parsed
    assert parsed["logger"] == "test"


def test_json_formatter_with_exception():
    from app.logging_config import JSONFormatter
    formatter = JSONFormatter()
    try:
        raise ValueError("test error")
    except ValueError:
        import sys
        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname="test.py",
            lineno=1, msg="failed", args=(), exc_info=sys.exc_info(),
        )
    output = formatter.format(record)
    parsed = json.loads(output)
    assert "exception" in parsed
    assert "ValueError" in parsed["exception"]
