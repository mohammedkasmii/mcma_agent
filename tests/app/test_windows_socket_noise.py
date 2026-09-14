"""The narrow Windows asyncio filter: exactly one traceback is dropped and
everything else is delegated.

The benign case is reproduced rather than described -- the test raises a
ConnectionResetError from a frame that carries asyncio's own
proactor_events.py filename and the `_call_connection_lost` name, which is
what the real cleanup callback looks like to an exception handler.

These run identically on Windows and elsewhere: sys.platform is patched
where the platform gate is what is under test, and the predicate itself is
platform-independent.
"""

from __future__ import annotations

import asyncio
import logging
import sys

import pytest

from mcma.app.windows_socket_noise import (
    WSAECONNRESET,
    is_benign_proactor_reset,
    is_proactor_events_file,
    make_exception_handler,
    quiet_benign_connection_resets,
)

PROACTOR_FILE = "C:\\Python314\\Lib\\asyncio\\proactor_events.py"


def _connection_reset(winerror: int) -> ConnectionResetError:
    """A ConnectionResetError carrying a winerror, on any platform. On
    Windows the 4-argument OSError form sets it; elsewhere winerror is not
    a real attribute, so it is set directly."""
    exc = ConnectionResetError(10054, "An existing connection was forcibly closed", None, winerror)
    if getattr(exc, "winerror", None) != winerror:
        exc.winerror = winerror
    return exc


def _raise_from(filename: str, function: str, exc: BaseException) -> BaseException:
    """Raises `exc` from a frame with the given file name and function
    name, so the traceback is shaped like the frame under test."""
    namespace: dict = {}
    exec(compile(f"def {function}(exc):\n    raise exc\n", filename, "exec"), namespace)
    try:
        namespace[function](exc)
    except BaseException as raised:  # noqa: BLE001 - returned for inspection
        return raised
    raise AssertionError("the helper did not raise")


def _benign_context() -> dict:
    raised = _raise_from(PROACTOR_FILE, "_call_connection_lost", _connection_reset(WSAECONNRESET))
    return {
        "message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost()",
        "exception": raised,
    }


class _Previous:
    def __init__(self) -> None:
        self.contexts = []

    def __call__(self, loop, context) -> None:
        self.contexts.append(context)


# --------------------------------------------------------------------- #
# The predicate
# --------------------------------------------------------------------- #


def test_the_exact_windows_cleanup_reset_is_recognised():
    assert is_benign_proactor_reset(_benign_context()) is True


def test_a_reset_with_another_winerror_is_not_ours():
    """10053 (WSAECONNABORTED) and the rest still reach the real handler."""
    for winerror in (10053, 10060, 0):
        raised = _raise_from(PROACTOR_FILE, "_call_connection_lost", _connection_reset(winerror))
        assert is_benign_proactor_reset({"exception": raised}) is False


def test_a_reset_raised_anywhere_but_the_cleanup_callback_is_not_ours():
    """A reset during a real request carries the same winerror -- the frame
    it was raised in is what separates it from teardown noise."""
    from_other_function = _raise_from(PROACTOR_FILE, "_write_ready", _connection_reset(WSAECONNRESET))
    assert is_benign_proactor_reset({"exception": from_other_function}) is False

    from_our_code = _raise_from(
        "C:\\app\\mcma\\portal\\browser.py", "_call_connection_lost", _connection_reset(WSAECONNRESET)
    )
    assert is_benign_proactor_reset({"exception": from_our_code}) is False


def test_other_exception_types_and_empty_contexts_are_not_ours():
    assert is_benign_proactor_reset({"exception": ValueError("boom")}) is False
    assert is_benign_proactor_reset({"message": "no exception at all"}) is False
    assert is_benign_proactor_reset({"exception": _connection_reset(WSAECONNRESET)}) is False  # no traceback


def test_the_matcher_tracks_the_real_asyncio_module():
    """Guards against drift: if the stdlib file this targets ever moved,
    the matcher would silently stop matching."""
    import asyncio.proactor_events as proactor_events

    assert is_proactor_events_file(proactor_events.__file__)
    assert not is_proactor_events_file("C:\\Python314\\Lib\\asyncio\\selector_events.py")


# --------------------------------------------------------------------- #
# The handler
# --------------------------------------------------------------------- #


def test_the_benign_reset_is_suppressed_and_never_delegated():
    previous = _Previous()
    make_exception_handler(previous)(asyncio.new_event_loop(), _benign_context())
    assert previous.contexts == []


@pytest.mark.parametrize(
    "context",
    [
        {"exception": ValueError("unrelated")},
        {"message": "Task exception was never retrieved"},
    ],
)
def test_everything_else_is_delegated_to_the_previous_handler(context):
    previous = _Previous()
    make_exception_handler(previous)(asyncio.new_event_loop(), context)
    assert previous.contexts == [context]


def test_another_connection_reset_is_delegated():
    previous = _Previous()
    raised = _raise_from(PROACTOR_FILE, "_call_connection_lost", _connection_reset(10053))
    context = {"exception": raised}
    make_exception_handler(previous)(asyncio.new_event_loop(), context)
    assert previous.contexts == [context]


def test_without_a_previous_handler_the_loop_default_is_used():
    class _Loop:
        def __init__(self) -> None:
            self.defaulted = []

        def default_exception_handler(self, context) -> None:
            self.defaulted.append(context)

    loop = _Loop()
    handler = make_exception_handler(None)
    context = {"exception": ValueError("unrelated")}
    handler(loop, context)
    assert loop.defaulted == [context]

    handler(loop, _benign_context())
    assert len(loop.defaulted) == 1  # the benign one was not passed on


def test_the_suppressed_reset_is_logged_at_debug_level_at_most(caplog):
    with caplog.at_level(logging.DEBUG, logger="mcma.app.windows_socket_noise"):
        make_exception_handler(None)(asyncio.new_event_loop(), _benign_context())
    records = [r for r in caplog.records if r.name == "mcma.app.windows_socket_noise"]
    assert [r.levelno for r in records] == [logging.DEBUG]

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="mcma.app.windows_socket_noise"):
        make_exception_handler(None)(asyncio.new_event_loop(), _benign_context())
    assert [r for r in caplog.records if r.name == "mcma.app.windows_socket_noise"] == []


# --------------------------------------------------------------------- #
# Install and restore, as the lifespan uses it
# --------------------------------------------------------------------- #


def test_the_filter_is_installed_for_the_body_and_removed_after(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    previous = _Previous()

    async def scenario():
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(previous)
        async with quiet_benign_connection_resets():
            installed = loop.get_exception_handler()
            assert installed is not previous
            # While installed: the benign one is dropped, a real one is not.
            installed(loop, _benign_context())
            assert previous.contexts == []
            real = {"exception": ValueError("unrelated")}
            installed(loop, real)
            assert previous.contexts == [real]
        return loop.get_exception_handler()

    assert asyncio.run(scenario()) is previous


def test_the_previous_handler_is_restored_even_when_the_body_fails(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    previous = _Previous()

    async def scenario():
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(previous)
        with pytest.raises(RuntimeError):
            async with quiet_benign_connection_resets():
                raise RuntimeError("startup failed")
        return loop.get_exception_handler()

    assert asyncio.run(scenario()) is previous


def test_a_loop_with_no_handler_is_left_with_none(monkeypatch):
    """`previous is None` means the loop's own default; restoring must put
    that back rather than leaving this module's wrapper installed."""
    monkeypatch.setattr(sys, "platform", "win32")

    async def scenario():
        loop = asyncio.get_running_loop()
        assert loop.get_exception_handler() is None
        async with quiet_benign_connection_resets():
            assert loop.get_exception_handler() is not None
        return loop.get_exception_handler()

    assert asyncio.run(scenario()) is None


def test_off_windows_the_loop_is_left_completely_untouched(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    async def scenario():
        loop = asyncio.get_running_loop()
        async with quiet_benign_connection_resets():
            return loop.get_exception_handler()

    assert asyncio.run(scenario()) is None


def test_the_event_loop_policy_is_never_touched():
    """Playwright needs the Proactor loop for subprocesses: switching policy
    is the fix this module deliberately does not use."""
    import inspect

    import mcma.app.windows_socket_noise as module

    source = inspect.getsource(module)
    for forbidden in ("WindowsSelectorEventLoopPolicy", "set_event_loop_policy", "new_event_loop"):
        assert forbidden not in source
