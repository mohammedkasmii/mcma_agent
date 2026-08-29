"""
INC-00 §6.11 — root README clearly states baseline filling and both fill
endpoints are permanently disabled during the rebuild.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_readme_declares_baseline_filling_disabled():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "permanently disabled" in text.lower(), (
        "README must prominently state that baseline form filling is permanently disabled"
    )
    assert "/api/v1/fill-dossier" in text, "README must name the disabled fill endpoint"
    assert "/api/v1/fill-dossier-from-wexia" in text, (
        "README must name the disabled Wexia fill endpoint"
    )
    assert "run_dossier.py" in text and "disabled" in text.lower(), (
        "README must mark run_dossier.py instructions as disabled/historical"
    )
