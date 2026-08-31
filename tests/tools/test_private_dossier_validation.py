"""Correction batch (Fable-review-2 MEDIUM finding) -- the private
dossier validation tool must redact any JSON key that doesn't look like
a schema field name (a dict used as a value-keyed map would otherwise
leak the value verbatim into the "redacted" report). Synthetic data
only -- this tool is never exercised against input_dossier/ in automated
tests."""

import json

from tools.private_dossier_validation import (
    _DYNAMIC_KEY_PLACEHOLDER,
    _collect_key_paths,
    _looks_like_a_schema_key,
    validate_directory,
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


def test_routing_hints_are_reported_as_fixed_category_counts_never_raw_paths(tmp_path):
    """Pilot-integration correction: possible_account_routing_key_paths
    (a raw path list) was replaced with routing_hint_category_counts --
    fixed category names with counts only, never the matched key path
    text itself."""
    (tmp_path / "d1.json").write_text(
        json.dumps({"dossier": {"expertise_city": "x", "reference_number": "R1", "is_reform": False}}),
        encoding="utf-8",
    )
    report = validate_directory(tmp_path)
    assert "possible_account_routing_key_paths" not in report
    assert "routing_hint_category_counts" in report
    assert report["routing_hint_category_counts"]["city_or_ville"] == 1
    assert report["routing_hint_category_counts"]["named_office_oujda_or_nador"] == 0
    # routing_hint_category_counts itself is category-name -> int only --
    # the matched path text never appears THERE (unsupported_key_path_
    # counts is a SEPARATE, deliberately schema-shaped field that is
    # allowed to show real field names -- that is its documented purpose).
    assert all(isinstance(v, int) for v in report["routing_hint_category_counts"].values())
    assert "expertise_city" not in json.dumps(report["routing_hint_category_counts"])


def test_dynamic_key_never_appears_in_a_full_validate_directory_report(tmp_path):
    (tmp_path / "d1.json").write_text(
        json.dumps({"dossier": {"claim-REF-98765": {"amount": 100}, "is_reform": False}}),
        encoding="utf-8",
    )
    report = validate_directory(tmp_path)
    serialized = json.dumps(report)
    assert "claim-REF-98765" not in serialized
    assert _DYNAMIC_KEY_PLACEHOLDER in serialized
