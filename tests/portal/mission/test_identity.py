"""
INC-09A -- the two-tier identity gate. Pure logic, no page/browser needed.
"""

import pytest

from mcma.domain.values import IdSinistre, InsurerReference, RegistrationPlate
from mcma.portal.identity import ExpectedIdentity, IdentityMismatch, ObservedIdentity, verify_identity

PLATE_A = RegistrationPlate("34602-B-7")
PLATE_B = RegistrationPlate("11111-A-1")
ID_SINISTRE_A = IdSinistre("534660")
ID_SINISTRE_B = IdSinistre("999999")
INSURER_REF_A = InsurerReference("REF-A")
INSURER_REF_B = InsurerReference("REF-B")


def test_matching_registration_and_id_sinistre_verifies():
    expected = ExpectedIdentity(registration=PLATE_A, id_sinistre=ID_SINISTRE_A)
    observed = ObservedIdentity(registration=PLATE_A, insurer_reference=None, id_sinistre=ID_SINISTRE_A)
    verify_identity(expected, observed)  # must not raise


def test_matching_registration_and_insurer_reference_verifies():
    expected = ExpectedIdentity(registration=PLATE_A, insurer_reference=INSURER_REF_A)
    observed = ObservedIdentity(registration=PLATE_A, insurer_reference=INSURER_REF_A, id_sinistre=None)
    verify_identity(expected, observed)  # must not raise


def test_registration_mismatch_fails_closed():
    expected = ExpectedIdentity(registration=PLATE_A, id_sinistre=ID_SINISTRE_A)
    observed = ObservedIdentity(registration=PLATE_B, insurer_reference=None, id_sinistre=ID_SINISTRE_A)
    with pytest.raises(IdentityMismatch) as exc_info:
        verify_identity(expected, observed)
    assert exc_info.value.field == "registration"


def test_id_sinistre_mismatch_fails_closed():
    expected = ExpectedIdentity(registration=PLATE_A, id_sinistre=ID_SINISTRE_A)
    observed = ObservedIdentity(registration=PLATE_A, insurer_reference=None, id_sinistre=ID_SINISTRE_B)
    with pytest.raises(IdentityMismatch) as exc_info:
        verify_identity(expected, observed)
    assert exc_info.value.field == "id_sinistre"


def test_insurer_reference_mismatch_fails_closed():
    expected = ExpectedIdentity(registration=PLATE_A, insurer_reference=INSURER_REF_A)
    observed = ObservedIdentity(registration=PLATE_A, insurer_reference=INSURER_REF_B, id_sinistre=None)
    with pytest.raises(IdentityMismatch) as exc_info:
        verify_identity(expected, observed)
    assert exc_info.value.field == "insurer_reference"


def test_observed_registration_missing_fails_closed():
    expected = ExpectedIdentity(registration=PLATE_A, id_sinistre=ID_SINISTRE_A)
    observed = ObservedIdentity(registration=None, insurer_reference=None, id_sinistre=ID_SINISTRE_A)
    with pytest.raises(IdentityMismatch) as exc_info:
        verify_identity(expected, observed)
    assert exc_info.value.field == "registration"


def test_observed_id_sinistre_missing_when_expected_requires_it_fails_closed():
    """The concrete 'never match-by-absence' regression: a missing observed
    value must never be treated as agreement, even though the failure mode
    (both effectively 'unknown') might look superficially symmetric."""
    expected = ExpectedIdentity(registration=PLATE_A, id_sinistre=ID_SINISTRE_A)
    observed = ObservedIdentity(registration=PLATE_A, insurer_reference=None, id_sinistre=None)
    with pytest.raises(IdentityMismatch) as exc_info:
        verify_identity(expected, observed)
    assert exc_info.value.field == "id_sinistre"


def test_observed_insurer_reference_missing_when_expected_requires_it_fails_closed():
    expected = ExpectedIdentity(registration=PLATE_A, insurer_reference=INSURER_REF_A)
    observed = ObservedIdentity(registration=PLATE_A, insurer_reference=None, id_sinistre=None)
    with pytest.raises(IdentityMismatch) as exc_info:
        verify_identity(expected, observed)
    assert exc_info.value.field == "insurer_reference"


def test_insurer_reference_not_checked_when_expected_does_not_supply_it():
    expected = ExpectedIdentity(registration=PLATE_A, id_sinistre=ID_SINISTRE_A)
    # observed.insurer_reference is None, but expected never asked for it --
    # must not raise on that field.
    observed = ObservedIdentity(registration=PLATE_A, insurer_reference=None, id_sinistre=ID_SINISTRE_A)
    verify_identity(expected, observed)


def test_id_sinistre_not_checked_when_expected_does_not_supply_it():
    expected = ExpectedIdentity(registration=PLATE_A, insurer_reference=INSURER_REF_A)
    observed = ObservedIdentity(registration=PLATE_A, insurer_reference=INSURER_REF_A, id_sinistre=None)
    verify_identity(expected, observed)


def test_expected_identity_requires_registration_type():
    with pytest.raises(TypeError):
        ExpectedIdentity(registration="34602-B-7", id_sinistre=ID_SINISTRE_A)  # plain str, not RegistrationPlate


def test_expected_identity_requires_at_least_one_tier1_identifier():
    with pytest.raises(ValueError):
        ExpectedIdentity(registration=PLATE_A)
