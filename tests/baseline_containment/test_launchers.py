"""
INC-00 §6.9 — Windows launchers/shortcut: no LAN URL, no IP discovery, no
run_dossier.py recommendation, no automation advertising.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(name):
    return (ROOT / name).read_text(encoding="utf-8", errors="replace")


def test_employee_bat_contains_no_lan_url_and_opens_nothing():
    text = _read("Ouvrir_MCMA_Employe.bat")
    assert "192.168.1.17" not in text, "hardcoded LAN IP still present"
    assert "start http" not in text.lower(), "the employee BAT still opens a URL"
    assert "http://" not in text.lower(), "the employee BAT still references a URL"


def test_employee_url_shortcut_is_absent():
    assert not (ROOT / "MCMA_Dashboard_Employe.url").exists(), (
        "the LAN .url shortcut must be deleted, not rewritten"
    )


def test_dashboard_launcher_has_no_ip_discovery_or_colleague_url():
    text = _read("Lancer_MCMA_Dashboard.bat")
    assert "route print" not in text.lower(), "IP discovery (route print) still present"
    assert "LOCAL_IP" not in text, "LOCAL_IP discovery variable still present"
    assert "collegues" not in text.lower(), "colleague/LAN URL still advertised"
    assert "localhost" in text.lower(), "localhost access must be kept"


def test_new_pc_setup_no_longer_recommends_run_dossier():
    text = _read("setup_new_pc.bat")
    assert "run_dossier.py" not in text, "setup still recommends the removed automation"


def test_master_launcher_no_longer_advertises_automation():
    text = _read("DEMARRER_MCMA.bat")
    assert "AUTOMATISATION" not in text.upper(), "master launcher still advertises automation"
    assert "localhost" in text.lower(), "localhost dashboard access must be kept"
