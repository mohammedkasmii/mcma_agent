"""
INC-00 §6.10 — no tracked BAT creates the profile=any firewall rule; the
decommission runbook exists with the exact administrator commands.
No firewall command is ever executed by these tests.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DELETE_CMD = 'netsh advfirewall firewall delete rule name="MCMA Dashboard (Port 8000)"'
SHOW_CMD = 'netsh advfirewall firewall show rule name="MCMA Dashboard (Port 8000)"'


def _tracked_bat_files():
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "*.bat"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def test_no_tracked_bat_adds_a_profile_any_firewall_rule():
    bats = _tracked_bat_files()
    assert bats, "expected tracked .bat files in the repository"
    for rel in bats:
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace").lower()
        assert not ("add rule" in text and "profile=any" in text), (
            f"{rel} still combines an add-rule command with profile=any"
        )


def test_decommission_runbook_exists_with_exact_commands():
    runbook = ROOT / "deploy" / "decommission_firewall.md"
    assert runbook.exists(), "deploy/decommission_firewall.md is missing"
    text = runbook.read_text(encoding="utf-8")
    assert DELETE_CMD in text, "exact named-rule delete command missing from runbook"
    assert SHOW_CMD in text, "exact named-rule verification command missing from runbook"
