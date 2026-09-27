"""Shared fixtures for tests/app/workstation_runner/.

GUI test architecture: exactly ONE real tk.Tk() interpreter for the whole
pytest session (`tk_session_root`), withdrawn and created/destroyed once.
Every GUI test gets its own tk.Toplevel attached to that single root
(`tk_root`) instead of creating a fresh tk.Tk() per test.

Why: on this Python 3.14 / Tcl-Tk combination, creating and destroying many
independent Tk() interpreters within one process is measurably unstable --
an intermittent TclError ("can't find a usable init.tcl" / "invalid
command name tcl_findLibrary") on a LATER, otherwise-unrelated Tk() call,
reproduced repeatedly across combined runs of this package's GUI test
files, but never once in an isolated script outside pytest (including one
exercising the exact same RunnerApp/RunnerController/threading pattern),
and confirmed NOT to be a missing-file problem (init.tcl, tk.tcl and
ttk/panedwindow.tcl all verified present). A single shared interpreter with
one Toplevel per test avoids the repeated Tcl_CreateInterp/DeleteInterp
cycle entirely while still giving every test its own top-level window
(full isolation for the widgets/StringVars each test builds via
RunnerApp(root=...))."""

import tkinter as tk

import pytest


@pytest.fixture(scope="session")
def tk_session_root():
    """The ONE real tk.Tk() interpreter for the entire test session.
    Withdrawn immediately (never shown), destroyed once at session
    teardown. No test uses this directly -- every GUI test depends on
    `tk_root` (a Toplevel attached to this), never on this fixture."""
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def tk_root(tk_session_root):
    """One tk.Toplevel per test, attached to the single session-wide Tk()
    interpreter -- never a second tk.Tk(). The REAL bound destroy method
    is captured BEFORE the test (or RunnerApp construction) has any chance
    to monkeypatch `.destroy`, and is always called at teardown, so no
    real Toplevel survives its test regardless of what the test itself
    monkeypatched or triggered."""
    toplevel = tk.Toplevel(tk_session_root)
    toplevel.withdraw()
    real_destroy = toplevel.destroy
    yield toplevel
    try:
        real_destroy()
    except Exception:
        pass  # already destroyed (or never fully realized) -- safe to ignore, never re-raise in teardown
