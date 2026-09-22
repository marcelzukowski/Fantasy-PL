"""CORE-004 logging behavior with per-test logger-state restoration."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import StringIO
import json
import logging
from pathlib import Path
import subprocess
import sys

import pytest

from fpl_engine.logging import bind_context, configure_logging, get_logger


def project_loggers():
    return [
        logger for name, logger in logging.Logger.manager.loggerDict.copy().items()
        if isinstance(logger, logging.Logger)
        and (name == "fpl_engine" or name.startswith("fpl_engine."))
    ]


@pytest.fixture(autouse=True)
def isolate_logging():
    logging.getLogger("fpl_engine")
    root = logging.getLogger()
    saved = {
        logger: (logger.level, logger.disabled, logger.propagate,
                 logger.handlers[:], logger.filters[:])
        for logger in [root, *project_loggers()]
    }
    for logger in project_loggers():
        logger.handlers = []
        logger.filters = []
        logger.setLevel(logging.NOTSET)
        logger.disabled = False
        logger.propagate = True
    try:
        yield
    finally:
        for logger in [root, *project_loggers()]:
            state = saved.get(logger, (logging.NOTSET, False, True, [], []))
            level, disabled, propagate, handlers, filters = state
            for handler in logger.handlers[:]:
                if handler not in handlers:
                    logger.removeHandler(handler)
                    handler.close()
            logger.handlers = handlers
            logger.filters = filters
            logger.setLevel(level)
            logger.disabled = disabled
            logger.propagate = propagate


@pytest.mark.parametrize(
    "name, expected",
    [("fpl_engine", "fpl_engine"), ("fpl_engine.data", "fpl_engine.data"),
     ("data", "fpl_engine.data"), ("__main__", "fpl_engine.__main__"),
     ("fpl_engineering", "fpl_engine.fpl_engineering")],
)
def test_get_logger_uses_project_hierarchy(name, expected):
    logger = get_logger(name)
    assert isinstance(logger, logging.Logger)
    assert logger.name == expected
    assert logger is get_logger(name)
    assert logger.handlers == []


@pytest.mark.parametrize("name", ["", "  ", None, 12])
def test_invalid_logger_name_fails(name):
    with pytest.raises(ValueError, match="non-empty string"):
        get_logger(name)


def test_default_info_and_in_memory_stream():
    stream = StringIO()
    configure_logging(stream=stream)
    logger = get_logger("data")
    logger.debug("hidden")
    logger.info("Read %s records", 3)

    assert get_logger().level == logging.INFO
    line = stream.getvalue().strip()
    timestamp, level, name, message = line.split(" ", 3)
    assert timestamp.endswith("Z")
    assert datetime.fromisoformat(timestamp).utcoffset().total_seconds() == 0
    assert (level, name, message) == ("INFO", "fpl_engine.data", "Read 3 records")
    assert not stream.closed


def test_utc_formatter_uses_record_time():
    stream = StringIO()
    configure_logging(stream=stream)
    record = logging.LogRecord("fpl_engine.data", logging.INFO, "test.py", 1, "event", (), None)
    record.created = 0
    get_logger().handle(record)
    assert stream.getvalue() == "1970-01-01T00:00:00Z INFO fpl_engine.data event\n"


def test_default_output_is_stderr(capsys):
    configure_logging()
    get_logger().info("stderr event")
    captured = capsys.readouterr()
    assert "stderr event" in captured.err
    assert captured.out == ""


@pytest.mark.parametrize("level", ["DEBUG", "debug", logging.DEBUG, "WARNING", "ERROR", "CRITICAL"])
def test_explicit_levels(level):
    stream = StringIO()
    configure_logging(level, stream=stream)
    expected = level if isinstance(level, int) else getattr(logging, level.upper())
    logger = get_logger("features")
    assert logger.getEffectiveLevel() == expected
    logger.log(expected, "visible")
    logger.log(expected - 1, "hidden")
    assert "visible" in stream.getvalue()
    assert "hidden" not in stream.getvalue()


@pytest.mark.parametrize("level", ["INVALID", "", "NOTSET", "10", -1, 0, 11, True, 10.0, None])
def test_invalid_level_fails_without_changing_configuration(level):
    original_stream = StringIO()
    configure_logging("DEBUG", stream=original_stream)
    original_handler = get_logger().handlers[0]
    with pytest.raises(ValueError, match="Invalid project log level"):
        configure_logging(level, stream=StringIO())
    assert get_logger().handlers == [original_handler]
    assert original_handler.stream is original_stream
    assert get_logger().level == logging.DEBUG


def test_context_composes_and_is_on_record():
    stream = StringIO()
    configure_logging(stream=stream)
    records = []

    class Capture(logging.Filter):
        def filter(self, record):
            records.append(record)
            return True

    get_logger().handlers[0].addFilter(Capture())
    base = get_logger("simulation")
    fixture = bind_context(base, fixture_id="fixture-1")
    player = bind_context(fixture, player_id="player-2", target_gameweek=5)
    player.info("Sample ready")
    assert isinstance(player, logging.LoggerAdapter)
    assert records[0].fixture_id == "fixture-1"
    assert records[0].player_id == "player-2"
    assert records[0].target_gameweek == 5
    assert stream.getvalue().split(" context=", 1)[1].strip() == (
        '{"fixture_id": "fixture-1", "player_id": "player-2", "target_gameweek": 5}'
    )
    assert dict(fixture.extra) == {"fixture_id": "fixture-1"}
    assert not hasattr(base, "fixture_id")


def test_nested_context_is_copied_when_binding():
    source = {"values": [1, 2]}
    parent = bind_context(get_logger(), details=source)
    child = bind_context(parent, player_id=7)
    source["values"].append(3)
    child.extra["details"]["values"].append(4)
    assert parent.extra["details"] == {"values": [1, 2]}
    assert child.extra["details"] == {"values": [1, 2, 4]}


def test_rebinding_and_per_call_extra_have_documented_precedence():
    stream = StringIO()
    configure_logging(stream=stream)
    parent = bind_context(get_logger(), player_id=1, fixture_id=2)
    child = bind_context(parent, player_id=3)
    extra = {"player_id": 4, "entity": "player"}
    child.info("first", extra=extra)
    child.info("second")
    contexts = [json.loads(line.split(" context=", 1)[1]) for line in stream.getvalue().splitlines()]
    assert contexts == [
        {"player_id": 4, "fixture_id": 2, "entity": "player"},
        {"player_id": 3, "fixture_id": 2},
    ]
    assert parent.extra["player_id"] == 1
    assert extra == {"player_id": 4, "entity": "player"}


def test_structured_values_and_plain_logger_extra():
    stream = StringIO()
    configure_logging(stream=stream)
    timestamp = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    logger = bind_context(get_logger(), prediction_timestamp=timestamp, path=Path("docs"))
    logger.info("event", extra={"details": {"missing": None, "available": False}})
    get_logger().info("plain", extra={"provider": "example"})
    contexts = [json.loads(line.split(" context=", 1)[1]) for line in stream.getvalue().splitlines()]
    assert contexts[0] == {
        "prediction_timestamp": str(timestamp), "path": "docs",
        "details": {"missing": None, "available": False},
    }
    assert contexts[1] == {"provider": "example"}


RESERVED_FIELDS = sorted(set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"})


@pytest.mark.parametrize("key", RESERVED_FIELDS)
def test_reserved_context_field_fails_at_binding(key):
    with pytest.raises(ValueError, match="Reserved LogRecord field"):
        bind_context(get_logger(), **{key: "override"})


@pytest.mark.parametrize("extra", [{"name": "override"}, {1: "not a string"}])
def test_per_call_context_is_validated(extra):
    configure_logging(stream=StringIO())
    logger = bind_context(get_logger(), fixture_id=1)
    with pytest.raises(ValueError):
        logger.info("event", extra=extra)


def test_repeated_configuration_updates_single_handler():
    first, second = StringIO(), StringIO()
    configure_logging(stream=first)
    handler = get_logger().handlers[0]
    configure_logging(stream=first)
    configure_logging("DEBUG", stream=second)
    assert get_logger().handlers == [handler]
    get_logger("models").debug("once")
    assert first.getvalue() == ""
    assert second.getvalue().count("once") == 1
    assert not first.closed


def test_root_is_preserved_and_project_does_not_propagate():
    root_stream, project_stream = StringIO(), StringIO()
    root = logging.getLogger()
    root_handler = logging.StreamHandler(root_stream)
    root.addHandler(root_handler)
    root.setLevel(logging.DEBUG)
    before = (root.level, root.handlers[:], root.filters[:], root.disabled)
    configure_logging(stream=project_stream)
    logger = get_logger("validation")
    logger.info("project event")
    assert logger.propagate is True
    assert get_logger().propagate is False
    assert root_stream.getvalue() == ""
    root.info("host event")
    assert root_stream.getvalue().count("host event") == 1
    assert project_stream.getvalue().count("project event") == 1
    assert "host event" not in project_stream.getvalue()
    assert (root.level, root.handlers, root.filters, root.disabled) == before


def test_caller_installed_project_handler_is_preserved():
    caller_stream = StringIO()
    handler = logging.StreamHandler(caller_stream)
    get_logger().addHandler(handler)
    configure_logging(stream=StringIO())
    configure_logging(stream=StringIO())
    assert handler in get_logger().handlers
    assert len(get_logger().handlers) == 2
    get_logger().info("caller event")
    assert "caller event" in caller_stream.getvalue()


def test_exception_traceback_and_stack_info_are_preserved():
    stream = StringIO()
    configure_logging(stream=stream)
    logger = bind_context(get_logger("config"), entity="configuration")
    try:
        raise ValueError("example failure")
    except ValueError:
        logger.exception("Cannot continue", stack_info=True)
    output = stream.getvalue()
    assert "ERROR fpl_engine.config Cannot continue" in output
    assert 'context={"entity": "configuration"}' in output
    assert "Traceback (most recent call last)" in output
    assert "ValueError: example failure" in output
    assert "Stack (most recent call last)" in output


def test_import_does_not_configure_loggers(tmp_path):
    source_root = Path(__file__).resolve().parents[1] / "src"
    script = """
import logging
import sys
sys.path.insert(0, sys.argv[1])
root = logging.getLogger()
root.addHandler(logging.StreamHandler())
root.setLevel(logging.ERROR)
project = logging.getLogger('fpl_engine')
before = (root.level, root.handlers[:], project.level, project.handlers[:], project.propagate)
import fpl_engine.logging
assert (root.level, root.handlers, project.level, project.handlers, project.propagate) == before
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(source_root)],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


def test_threaded_bindings_and_configuration_do_not_duplicate_records():
    stream = StringIO()
    base = bind_context(get_logger("simulation"), fixture_id=1)

    def emit(player_id):
        configure_logging(stream=stream)
        bind_context(base, player_id=player_id).info("event")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(emit, range(20)))
    contexts = [json.loads(line.split(" context=", 1)[1]) for line in stream.getvalue().splitlines()]
    assert len(contexts) == 20
    assert {item["player_id"] for item in contexts} == set(range(20))
    assert all(item["fixture_id"] == 1 for item in contexts)
    assert dict(base.extra) == {"fixture_id": 1}
    assert len(get_logger().handlers) == 1
