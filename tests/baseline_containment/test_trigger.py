"""
INC-00 §6.2 — trigger.py must be a refusal-only executable making no HTTP call.
"""

import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

CONTAINMENT_MSG = (
    "Baseline live-write capability was permanently removed at INC-00; "
    "the only live-write path is the post-G5 VerifiedMissionWriter."
)


def test_trigger_refuses_with_exact_systemexit_and_no_http_call(monkeypatch):
    http_calls = []
    try:
        import requests

        def _no_post(*args, **kwargs):
            http_calls.append((args, kwargs))
            raise AssertionError("trigger.py attempted an HTTP POST; containment is missing")

        monkeypatch.setattr(requests, "post", _no_post)
    except ImportError:
        pass

    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(ROOT / "trigger.py"), run_name="__main__")
    assert str(exc.value) == CONTAINMENT_MSG
    assert http_calls == []


def test_trigger_source_has_no_requests_usage():
    src = (ROOT / "trigger.py").read_text(encoding="utf-8")
    assert "import requests" not in src
    assert "requests.post" not in src
    assert "fill-dossier" not in src
