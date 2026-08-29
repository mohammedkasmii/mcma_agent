"""
INC-00 §6.8 — API binds to loopback only; the IP-discovery/LAN banner block is gone.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _main_source():
    return (ROOT / "main.py").read_text(encoding="utf-8")


def test_api_binds_loopback_in_code():
    src = _main_source()
    assert 'host="127.0.0.1"' in src, "uvicorn must bind to loopback in code"
    assert "0.0.0.0" not in src, "a 0.0.0.0 bind is still reachable in main.py"


def test_startup_has_no_ip_discovery_or_lan_banner():
    src = _main_source()
    assert "8.8.8.8" not in src, "IP-discovery dial target still present"
    assert "local_ip" not in src, "local-IP discovery variable still present"
    assert "import socket" not in src, "socket-based IP discovery still present"
    assert "gethostbyname" not in src, "hostname-based IP discovery still present"
    assert "collègues" not in src, "colleague/LAN access banner still present"
