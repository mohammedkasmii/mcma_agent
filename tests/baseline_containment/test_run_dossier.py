"""
INC-00 §6.1 — run_dossier.py must refuse at startup, before any browser launch.
"""

import asyncio
import importlib
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

CONTAINMENT_MSG = (
    "Baseline live-write capability was permanently removed at INC-00; "
    "the only live-write path is the post-G5 VerifiedMissionWriter."
)


def _load_run_dossier():
    sys.modules.pop("run_dossier", None)
    return importlib.import_module("run_dossier")


def _fail_if_called(*args, **kwargs):
    raise AssertionError("baseline workflow was invoked; containment refusal is missing")


def test_run_dossier_refuses_at_startup_before_browser_launch(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_dossier.py"])
    rd = _load_run_dossier()

    # Guard the baseline RED run: no input-directory scan, no data load, no workflow.
    if hasattr(rd, "find_default_json"):
        monkeypatch.setattr(rd, "find_default_json", lambda: "")
    if hasattr(rd, "load_json_data"):
        monkeypatch.setattr(rd, "load_json_data", _fail_if_called)
    if hasattr(rd, "process_workflow"):
        monkeypatch.setattr(rd, "process_workflow", _fail_if_called)

    with pytest.raises(SystemExit) as exc:
        result = rd.main()
        if inspect.iscoroutine(result):
            asyncio.run(result)
    assert str(exc.value) == CONTAINMENT_MSG


def test_run_dossier_no_longer_imports_or_exposes_process_workflow():
    rd = _load_run_dossier()
    assert not hasattr(rd, "process_workflow"), (
        "run_dossier must not expose/import the baseline process_workflow"
    )
    src = (ROOT / "run_dossier.py").read_text(encoding="utf-8")
    assert "process_workflow" not in src
    assert "from main import" not in src
