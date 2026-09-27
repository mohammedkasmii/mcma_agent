import re
import sys

import pytest

from mcma.app.workstation_runner.app import (
    _current_windows_user_sid, _native_message_box, _show_message_box, single_instance_mutex_name,
)
from mcma.core.mutex import MutexAcquisitionError, create_single_instance_mutex

_SID_RE = re.compile(r"^S-1-\d+(-\d+)+$")


@pytest.mark.skipif(sys.platform != "win32", reason="real Win32 SID query only")
def test_current_windows_user_sid_returns_a_real_sid_on_windows():
    sid = _current_windows_user_sid()
    assert sid is not None
    assert _SID_RE.match(sid), sid


@pytest.mark.skipif(sys.platform != "win32", reason="real Win32 SID query only")
def test_current_windows_user_sid_is_stable_across_calls():
    assert _current_windows_user_sid() == _current_windows_user_sid()


@pytest.mark.skipif(sys.platform != "win32", reason="real Win32 SID query only")
def test_single_instance_mutex_name_uses_the_real_sid_by_default():
    """No _sid_query override -- proves the production default path really
    calls the real Win32 SID query, not a stub."""
    name = single_instance_mutex_name()
    sid = _current_windows_user_sid()
    assert sid is not None
    assert sid in name


def test_second_instance_is_refused_while_first_holds_the_mutex():
    name = single_instance_mutex_name()
    first = create_single_instance_mutex(name, _test_only_portable_backend=True)
    first.acquire()
    try:
        second = create_single_instance_mutex(name, _test_only_portable_backend=True)
        with pytest.raises(MutexAcquisitionError):
            second.acquire()
    finally:
        first.release()


def test_mutex_is_released_after_first_instance_releases():
    name = single_instance_mutex_name()
    first = create_single_instance_mutex(name, _test_only_portable_backend=True)
    first.acquire()
    first.release()
    second = create_single_instance_mutex(name, _test_only_portable_backend=True)
    second.acquire()
    second.release()


def test_single_instance_mutex_name_is_derived_from_the_sid_not_the_username_env_var(monkeypatch):
    """CLEANUP: the mutex namespace must be derived from the authenticated
    Windows user SID (a real Win32 security identifier queried from this
    process's own token), never from the USERNAME/USER environment
    variables -- those are trivially set by any process to an arbitrary
    string. mcma.core.mutex.WindowsSingleInstanceMutex places the name in a
    `Global\\` namespace -- machine-wide, not per Windows user -- so a
    second user on the same machine (fast user switching / RDP) must not
    collide with a different one, and one user must not be able to spoof
    another's mutex name via USERNAME."""
    monkeypatch.setenv("USERNAME", "attacker-controlled-name")
    name = single_instance_mutex_name(_sid_query=lambda: "S-1-5-21-111-222-333-1001")
    assert "attacker-controlled-name" not in name
    assert "S-1-5-21-111-222-333-1001" in name
    assert name != "MCMA_WorkstationRunner"


def test_single_instance_mutex_name_sanitizes_unexpected_characters():
    name = single_instance_mutex_name(_sid_query=lambda: "not a real sid\\with\\slashes")
    assert "\\" not in name
    assert " " not in name


def test_username_spoofing_never_changes_the_mutex_name_for_the_same_sid(monkeypatch):
    monkeypatch.setenv("USERNAME", "bob")
    a = single_instance_mutex_name(_sid_query=lambda: "S-1-5-21-1-1-1-1001")
    monkeypatch.setenv("USERNAME", "alice-pretending-to-be-someone-else")
    b = single_instance_mutex_name(_sid_query=lambda: "S-1-5-21-1-1-1-1001")
    assert a == b  # only the SID matters, never the mutable/spoofable username


def test_a_renamed_account_same_sid_still_maps_to_the_same_mutex_name(monkeypatch):
    """A renamed Windows account (same SID, different display username)
    must still map to the SAME mutex."""
    monkeypatch.setenv("USERNAME", "old-name")
    before_rename = single_instance_mutex_name(_sid_query=lambda: "S-1-5-21-9-9-9-1001")
    monkeypatch.setenv("USERNAME", "new-name-after-rename")
    after_rename = single_instance_mutex_name(_sid_query=lambda: "S-1-5-21-9-9-9-1001")
    assert before_rename == after_rename


def test_two_different_sids_get_different_mutex_names_and_can_both_hold_one():
    alice_name = single_instance_mutex_name(_sid_query=lambda: "S-1-5-21-1-1-1-1001")
    bob_name = single_instance_mutex_name(_sid_query=lambda: "S-1-5-21-1-1-1-1002")
    assert alice_name != bob_name
    alice_mutex = create_single_instance_mutex(alice_name, _test_only_portable_backend=True)
    bob_mutex = create_single_instance_mutex(bob_name, _test_only_portable_backend=True)
    alice_mutex.acquire()
    try:
        bob_mutex.acquire()  # must NOT raise -- different SIDs, different mutex
        bob_mutex.release()
    finally:
        alice_mutex.release()


def test_sid_query_failure_falls_back_to_a_fixed_shared_name_not_a_crash():
    """If the real SID query fails for any reason, the mutex name must
    fail closed to a fixed, shared name (matching the pre-fix behavior for
    a single-user machine) rather than raising or silently disabling the
    single-instance guarantee with a randomized name."""
    name = single_instance_mutex_name(_sid_query=lambda: None)
    assert name == single_instance_mutex_name(_sid_query=lambda: None)  # deterministic, not random
    assert isinstance(name, str) and name


def test_native_message_box_calls_user32_messageboxw_with_the_fixed_text(monkeypatch):
    calls = []

    class _FakeUser32:
        def MessageBoxW(self, hwnd, text, caption, flags):
            calls.append((hwnd, text, caption, flags))
            return 1  # IDOK

    monkeypatch.setattr(sys, "platform", "win32")
    assert _native_message_box("Titre", "Un message fixe.", _user32=_FakeUser32()) is True
    assert calls == [(None, "Un message fixe.", "Titre", calls[0][3])]


def test_native_message_box_returns_false_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    calls = []

    class _ShouldNeverBeCalledUser32:
        def MessageBoxW(self, *args):
            calls.append(args)
            return 1

    assert _native_message_box("Titre", "Un message fixe.", _user32=_ShouldNeverBeCalledUser32()) is False
    assert calls == []  # never even attempted off Windows


def test_native_message_box_returns_false_never_raises_on_failure(monkeypatch):
    class _BrokenUser32:
        def MessageBoxW(self, *args):
            raise OSError("simulated user32 failure")

    monkeypatch.setattr(sys, "platform", "win32")
    assert _native_message_box("Titre", "Un message fixe.", _user32=_BrokenUser32()) is False


class _RecordingTk:
    def __init__(self):
        self.withdrawn = False
        self.destroyed = False

    def Tk(self):
        return self

    def withdraw(self):
        self.withdrawn = True

    def destroy(self):
        self.destroyed = True


class _RecordingMessagebox:
    def __init__(self):
        self.calls = []

    def showerror(self, title, message):
        self.calls.append((title, message))


def test_show_message_box_displays_via_tkinter_messagebox_not_print(capsys):
    """Regression: the single-instance and fatal-startup messages used
    print(), which is a silent no-op under pythonw (no console, sys.stdout
    is None) -- the process would just exit invisibly."""
    tk = _RecordingTk()
    mb = _RecordingMessagebox()
    _show_message_box("Titre", "Un message fixe.", tk_module=tk, messagebox_module=mb)
    assert mb.calls == [("Titre", "Un message fixe.")]
    assert tk.withdrawn is True
    assert tk.destroyed is True
    assert capsys.readouterr().out == ""  # never falls back to print() when Tk succeeds


class _BrokenTk:
    def Tk(self):
        raise RuntimeError("no display")


def test_show_message_box_falls_back_to_native_windows_messagebox_when_tk_fails(capsys):
    """RELEASE FOLLOW-UP: if Tk itself cannot even be constructed (e.g. a
    broken/missing Tcl install), fall back to a native Win32 MessageBoxW
    via ctypes -- never straight to print(), which is silent under
    pythonw."""
    native_calls = []

    def fake_native(title, message):
        native_calls.append((title, message))
        return True

    _show_message_box(
        "Titre", "Un message fixe.", tk_module=_BrokenTk(), messagebox_module=_RecordingMessagebox(),
        _native_message_box_fn=fake_native,
    )
    assert native_calls == [("Titre", "Un message fixe.")]
    assert capsys.readouterr().out == ""  # never falls back to print() when the native box succeeded


def test_show_message_box_falls_back_to_print_when_tk_and_native_both_fail(capsys):
    _show_message_box(
        "Titre", "Un message fixe.", tk_module=_BrokenTk(), messagebox_module=_RecordingMessagebox(),
        _native_message_box_fn=lambda title, message: False,
    )
    assert "Un message fixe." in capsys.readouterr().out


def test_show_message_box_with_no_stdout_never_raises_when_every_fallback_fails(monkeypatch):
    """Under pythonw, sys.stdout is None -- print() would raise. If Tk AND
    the native fallback both fail too, this must return safely rather
    than raising, never blindly calling print()."""
    monkeypatch.setattr(sys, "stdout", None)
    _show_message_box(
        "Titre", "Un message fixe.", tk_module=_BrokenTk(), messagebox_module=_RecordingMessagebox(),
        _native_message_box_fn=lambda title, message: False,
    )  # must not raise


def test_show_message_box_never_shows_more_than_the_fixed_title_and_message(capsys):
    """No secret or raw exception text ever reaches any fallback -- only
    the exact fixed title/message the caller passed."""
    native_calls = []
    _show_message_box(
        "Titre fixe", "Message fixe sans secret.", tk_module=_BrokenTk(), messagebox_module=_RecordingMessagebox(),
        _native_message_box_fn=lambda title, message: native_calls.append((title, message)) or True,
    )
    assert native_calls == [("Titre fixe", "Message fixe sans secret.")]
