"""INC-04 — immutable value objects and the shared normalizer."""

import dataclasses

import pytest

from mcma.domain.normalize import normalize_text
from mcma.domain.values import (
    AccountId,
    IdSinistre,
    InsurerReference,
    RegistrationPlate,
    RubriqueId,
)


def test_registration_plate_normalizes_for_comparison():
    a = RegistrationPlate("36165-B-50")
    b = RegistrationPlate(" 36165 b 50 ")
    assert a.normalized == "36165B50"
    assert a == b
    assert hash(a) == hash(b)


def test_registration_plate_distinguishes_series_letters():
    assert RegistrationPlate("36165-B-50") != RegistrationPlate("36165-U-50")


def test_value_objects_are_immutable_and_reject_empty():
    plate = RegistrationPlate("11111-A-11")
    with pytest.raises(dataclasses.FrozenInstanceError):
        plate.raw = "x"
    for cls in (RegistrationPlate, InsurerReference, IdSinistre, AccountId, RubriqueId):
        with pytest.raises(ValueError):
            cls("")
        with pytest.raises(ValueError):
            cls("   ")


def test_normalize_strips_accents_punctuation_whitespace():
    assert normalize_text("  Pare-Brise  AVANT ") == "pare brise avant"
    assert normalize_text("Lunette Arrière") == "lunette arriere"
    assert normalize_text("MAIN D'ŒUVRE   Peinture!") == "main d oeuvre peinture"
    assert normalize_text(None) == ""
    assert normalize_text("") == ""


def test_plate_preserves_non_ascii_series_letters():
    """G1 review H8: Moroccan plates differing only in the Arabic series
    letter must NOT collide on the normalized comparison key."""
    a = RegistrationPlate("12345-\u0623-6")
    b = RegistrationPlate("12345-\u0628-6")
    assert a != b
    assert a.normalized != b.normalized
