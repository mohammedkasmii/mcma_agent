"""
mcma.app.windows_socket_noise -- silences ONE specific piece of Windows
asyncio noise, and nothing else.

WHAT IT IS. On Windows, asyncio's Proactor transport calls
socket.shutdown() while cleaning up a connection whose peer has already
gone away (`_ProactorBasePipeTransport._call_connection_lost`). A browser
dropping an idle keep-alive connection, or closing the /events stream on
navigation, does exactly that -- so ordinary use printed a full traceback
into the operator's console after nearly every page:

    Exception in callback _ProactorBasePipeTransport._call_connection_lost()
    ...
    ConnectionResetError: [WinError 10054] Une connexion existante a du
    etre fermee par l'hote distant

The request itself already succeeded -- its 200 is logged on the line
immediately before -- so the traceback describes the teardown of a socket
that is already closed. It alarms the office and names nothing anyone can
act on.

WHAT IT DELIBERATELY IS NOT. This is not "ignore ConnectionResetError",
and not "ignore errors in asyncio callbacks". THREE conditions must all
hold before anything is dropped:

  1. the exception is a ConnectionResetError,
  2. its winerror is exactly 10054 (WSAECONNRESET),
  3. it was raised inside asyncio's own proactor_events.py, in the
     `_call_connection_lost` cleanup frame.

Everything else -- a reset raised while serving a real request, a reset
carrying a different winerror, any other exception type, a context with no
exception at all -- goes to whatever handler was installed before this one,
or to the loop's default handler. The one case that IS dropped is logged at
debug level, so it can still be seen deliberately.

The event loop POLICY is untouched. Switching to WindowsSelectorEventLoop
is the usual advice for this traceback and is not available here: Playwright
needs the Proactor loop's subprocess support to drive the browser at all.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys

logger = logging.getLogger(__name__)

#: WSAECONNRESET -- "an existing connection was forcibly closed by the
#: remote host". The only winerror this module will ever drop.
WSAECONNRESET = 10054

_CLEANUP_CALLBACK = "_call_connection_lost"
_PROACTOR_MODULE_TAIL = "asyncio/proactor_events.py"


def is_proactor_events_file(filename: str) -> bool:
    """True for asyncio's own proactor_events.py, on either separator."""
    return filename.replace("\\", "/").endswith(_PROACTOR_MODULE_TAIL)


def _raised_in_proactor_cleanup(exc: BaseException) -> bool:
    """Walks the traceback for asyncio's cleanup frame. An exception with
    no traceback, or one raised anywhere else, is not ours to drop."""
    traceback = exc.__traceback__
    while traceback is not None:
        code = traceback.tb_frame.f_code
        if code.co_name == _CLEANUP_CALLBACK and is_proactor_events_file(code.co_filename):
            return True
        traceback = traceback.tb_next
    return False


def is_benign_proactor_reset(context: dict) -> bool:
    """The full test, all three conditions. Anything this returns False for
    must still reach a real handler."""
    exc = context.get("exception")
    if not isinstance(exc, ConnectionResetError):
        return False
    if getattr(exc, "winerror", None) != WSAECONNRESET:
        return False
    return _raised_in_proactor_cleanup(exc)


def make_exception_handler(previous):
    """Wraps `previous` (the handler installed before us, or None for the
    loop's default). Delegation is the default path: the filter only ever
    removes the one benign cleanup reset from what `previous` would see."""

    def handle(loop, context):
        if is_benign_proactor_reset(context):
            # Debug, not warning: this is the noise being removed. Nothing
            # is silently discarded -- it can be read back by turning debug
            # logging on for this module.
            logger.debug(
                "ignored a benign Windows socket cleanup reset (WinError %d) "
                "from asyncio's proactor transport teardown",
                WSAECONNRESET,
            )
            return
        if previous is not None:
            previous(loop, context)
            return
        loop.default_exception_handler(context)

    return handle


def _is_windows() -> bool:
    return sys.platform == "win32"


@contextlib.asynccontextmanager
async def quiet_benign_connection_resets():
    """Installs the filter on the running loop for the life of the
    application, and puts the previous handler back on the way out --
    including when the application fails on startup.

    A no-op off Windows: the traceback this removes is raised by the
    Proactor transport, which only exists there. (The predicate would not
    match elsewhere either, since `winerror` is a Windows-only attribute.)
    """
    if not _is_windows():
        yield
        return
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    loop.set_exception_handler(make_exception_handler(previous))
    try:
        yield
    finally:
        # set_exception_handler(None) restores the loop's own default,
        # which is exactly what `previous is None` meant.
        loop.set_exception_handler(previous)
