"""REAL_DPAPI_WINDOWS_ROUNDTRIP_PENDING_LOCAL_TEST

Windows-only. Everything else in the suite proves the SHAPE of job-input
encryption with a substitute transform, because DPAPI does not exist on
Linux CI -- so nothing there has actually called CryptProtectData. This
file is the part that has to run on a Windows machine, and it needs no
agency network, no portal session and no credentials.

    python -m pytest tests/execution/jobs/test_inputs_dpapi_windows.py -v

It skips on any other platform rather than pretending it ran.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="REAL_DPAPI_WINDOWS_ROUNDTRIP_PENDING_LOCAL_TEST: Windows DPAPI only",
)

SECRET = b"SUPER_SECRET_CLIENT_12345 / 62259-A-50 / 12345.67"


def test_a_separate_encryptor_instance_decrypts_what_another_protected():
    """The restart property, against real DPAPI: instance A protects,
    instance B unprotects, under the same Windows account. If this fails,
    resuming a job after restarting the application would not work."""
    from mcma.execution.inputs import DpapiCurrentUserEncryptor

    ciphertext = DpapiCurrentUserEncryptor().encrypt(SECRET)
    assert DpapiCurrentUserEncryptor().decrypt(ciphertext) == SECRET


def test_the_ciphertext_does_not_contain_the_plaintext():
    from mcma.execution.inputs import DpapiCurrentUserEncryptor

    ciphertext = DpapiCurrentUserEncryptor().encrypt(SECRET)
    assert ciphertext != SECRET
    assert SECRET not in ciphertext
    assert b"SUPER_SECRET_CLIENT_12345" not in ciphertext
    assert b"62259-A-50" not in ciphertext


def test_the_production_factory_returns_the_real_encryptor_here():
    """On Windows there is no excuse for a weaker backend, so the factory
    must hand back the DPAPI one without any opt-in."""
    from mcma.execution.inputs import DpapiCurrentUserEncryptor, get_input_encryptor

    assert isinstance(get_input_encryptor(), DpapiCurrentUserEncryptor)


def test_tampered_ciphertext_fails_rather_than_returning_wrong_bytes():
    from mcma.core.dpapi import DpapiUnavailable
    from mcma.execution.inputs import DpapiCurrentUserEncryptor

    ciphertext = bytearray(DpapiCurrentUserEncryptor().encrypt(SECRET))
    ciphertext[len(ciphertext) // 2] ^= 0xFF
    with pytest.raises((DpapiUnavailable, OSError, ValueError)):
        DpapiCurrentUserEncryptor().decrypt(bytes(ciphertext))


def test_current_user_and_local_machine_are_genuinely_different_scopes():
    """The scope argument must actually reach DPAPI. If both scopes
    produced interchangeable ciphertext, choosing CURRENT_USER for job
    inputs would be decoration rather than protection."""
    from mcma.core.dpapi import DpapiScope, protect, unprotect

    as_user = protect(SECRET, DpapiScope.CURRENT_USER)
    as_machine = protect(SECRET, DpapiScope.LOCAL_MACHINE)

    assert as_user != as_machine
    assert unprotect(as_user, DpapiScope.CURRENT_USER) == SECRET
    assert unprotect(as_machine, DpapiScope.LOCAL_MACHINE) == SECRET


def test_a_whole_dossier_survives_the_round_trip():
    """Realistic size and content: DPAPI has length limits worth knowing
    about before a real dossier meets them."""
    import json

    from mcma.execution.inputs import DpapiCurrentUserEncryptor

    dossier = {
        "dossier": {"id_sinistre": "699001", "insured": "BENALI Youssef"},
        "vehicule": {"license_plate": "62259-A-50"},
        "chiffrages": [{"id": f"CH-{i}", "total_cost": 1234.56} for i in range(200)],
    }
    payload = json.dumps(dossier, sort_keys=True).encode("utf-8")

    encryptor = DpapiCurrentUserEncryptor()
    assert encryptor.decrypt(encryptor.encrypt(payload)) == payload
