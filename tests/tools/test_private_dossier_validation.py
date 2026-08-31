"""Correction batch (Fable-review-2 MEDIUM finding) -- the private
dossier validation tool must redact any JSON key that doesn't look like
a schema field name (a dict used as a value-keyed map would otherwise
leak the value verbatim into the "redacted" report). Synthetic data
only -- this tool is never exercised against input_dossier/ in automated
tests."""

from tools.private_dossier_validation import (
    _DYNAMIC_KEY_PLACEHOLDER,
    _collect_key_paths,
    _looks_like_a_schema_key,
)


def test_ordinary_schema_keys_are_not_redacted():
    assert _looks_like_a_schema_key("dossier") is True
    assert _looks_like_a_schema_key("mileage_km") is True
    assert _looks_like_a_schema_key("_internal") is True


def test_value_shaped_keys_are_redacted():
    assert _looks_like_a_schema_key("claim-REF-98765") is False
    assert _looks_like_a_schema_key("2026-01-01") is False
    assert _looks_like_a_schema_key("11111-A-11") is False  # a registration-plate-shaped string
    assert _looks_like_a_schema_key("a" * 100) is False  # implausibly long for a schema key


def test_dict_keyed_by_a_claim_reference_never_leaks_the_reference():
    paths = _collect_key_paths({"dossier": {"claim-REF-98765": {"amount": 100}}})
    assert paths == {"dossier", f"dossier.{_DYNAMIC_KEY_PLACEHOLDER}", f"dossier.{_DYNAMIC_KEY_PLACEHOLDER}.amount"}
    assert "claim-REF-98765" not in paths
    assert not any("REF" in p for p in paths)


def test_dict_keyed_by_a_registration_plate_never_leaks_the_plate():
    paths = _collect_key_paths({"vehicule": {"11111-A-11": {"status": "ok"}}})
    assert "11111-A-11" not in paths
    assert any(_DYNAMIC_KEY_PLACEHOLDER in p for p in paths)


def test_normal_nested_schema_still_reports_real_field_paths():
    paths = _collect_key_paths({"dossier": {"mileage_km": 5000, "assureur": {"nom": "x"}}})
    assert "dossier.mileage_km" in paths
    assert "dossier.assureur.nom" in paths
    assert _DYNAMIC_KEY_PLACEHOLDER not in "".join(paths)
