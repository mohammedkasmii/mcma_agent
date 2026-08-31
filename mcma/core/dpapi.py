"""
mcma.core.dpapi -- the one Windows DPAPI call site.

Both the session vault (mcma.portal.vault) and job-input storage
(mcma.execution.inputs) need CryptProtectData/CryptUnprotectData, and
those are sibling layers that may not import each other. The primitive
therefore lives here, in the bottom layer both may legally depend on,
rather than being written twice -- two copies of an FFI call is two
places for a buffer-handling mistake to hide.

This module deliberately knows nothing about sessions, dossiers, files or
databases. It protects bytes and returns bytes.

SCOPE IS THE CALLER'S DECISION, and an explicit argument rather than a
default, because the two callers genuinely need different answers:

  * LOCAL_MACHINE  -- any process on this machine can decrypt, so
    confidentiality rests on the filesystem ACL around the ciphertext.
    Correct where the data must survive a change of service identity.
  * CURRENT_USER   -- only the Windows account that encrypted it can
    decrypt, so obtaining the file or database is not enough. The
    narrower of the two, and the right default for anything a single
    interactive account both writes and reads.

Failures raise DpapiUnavailable with a fixed message. The plaintext, the
ciphertext and the Windows error text never appear in it: this is used
for portal session cookies and for dossier JSON holding claimant names,
registrations and amounts.
"""

from __future__ import annotations

import sys
from enum import Enum

_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_CRYPTPROTECT_LOCAL_MACHINE = 0x4


class DpapiScope(Enum):
    CURRENT_USER = "CURRENT_USER"
    LOCAL_MACHINE = "LOCAL_MACHINE"


class DpapiUnavailable(Exception):
    """DPAPI is not available, or the operation failed. Carries no
    plaintext, no ciphertext and no Windows error text."""


def is_available() -> bool:
    return sys.platform == "win32"


def protect(data: bytes, scope: DpapiScope) -> bytes:
    return _crypt(data, scope=scope, protect_data=True)


def unprotect(data: bytes, scope: DpapiScope) -> bytes:
    return _crypt(data, scope=scope, protect_data=False)


def _crypt(data: bytes, *, scope: DpapiScope, protect_data: bool) -> bytes:
    if not is_available():
        raise DpapiUnavailable("Windows DPAPI is not available on this platform")
    if not isinstance(data, bytes):
        raise TypeError("DPAPI operates on bytes")

    import ctypes
    import ctypes.wintypes as wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _to_blob(buf: bytes) -> DATA_BLOB:
        buf_copy = ctypes.create_string_buffer(buf, len(buf))
        return DATA_BLOB(len(buf), ctypes.cast(buf_copy, ctypes.POINTER(ctypes.c_char)))

    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    # UI_FORBIDDEN so a prompt can never appear on a machine running this
    # unattended: a blocked call must fail, not wait for a human.
    flags = _CRYPTPROTECT_UI_FORBIDDEN
    if scope is DpapiScope.LOCAL_MACHINE:
        flags |= _CRYPTPROTECT_LOCAL_MACHINE

    in_blob = _to_blob(data)
    out_blob = DATA_BLOB()
    func = crypt32.CryptProtectData if protect_data else crypt32.CryptUnprotectData
    ok = func(ctypes.byref(in_blob), None, None, None, None, flags, ctypes.byref(out_blob))
    if not ok:
        # No GetLastError text: a DPAPI failure message can quote context
        # about the data it was handed.
        raise DpapiUnavailable(
            f"DPAPI {'protect' if protect_data else 'unprotect'} failed ({scope.value})"
        )
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
