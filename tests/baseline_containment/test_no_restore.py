"""
INC-00 §6.13 — no environment variable, configuration value, or CLI argument
can restore any baseline writer. Every refusal stays unconditional.
"""

import asyncio
import importlib
import inspect
import runpy
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]

CONTAINMENT_MSG = (
    "Baseline live-write capability was permanently removed at INC-00; "
    "the only live-write path is the post-G5 VerifiedMissionWriter."
)


class FakeLogger:
    log_path = "<in-memory>"

    def log(self, *args, **kwargs):
        pass

    def summary(self):
        return {"errors": 0, "log_file": self.log_path}


def _fail_if_called(*args, **kwargs):
    raise AssertionError("a contained code path executed instead of refusing")


def _run_maybe_async(func, *args, **kwargs):
    result = func(*args, **kwargs)
    if inspect.iscoroutine(result):
        asyncio.run(result)


def test_no_env_config_or_cli_can_re_enable_baseline_write(monkeypatch, tmp_path):
    # Representative "write-enabling" environment and config flips.
    monkeypatch.setenv("TEST_MODE", "0")
    monkeypatch.setenv("ENABLE_WRITES", "1")
    monkeypatch.setenv("MCMA_WRITE", "1")
    import core.config as cfg

    monkeypatch.setattr(cfg, "TEST_MODE", False, raising=False)

    # run_dossier.main — hostile CLI arguments must not matter.
    monkeypatch.setattr(sys, "argv", ["run_dossier.py", "--enable-writes"])
    sys.modules.pop("run_dossier", None)
    rd = importlib.import_module("run_dossier")
    if hasattr(rd, "find_default_json"):
        monkeypatch.setattr(rd, "find_default_json", lambda: "")
    with pytest.raises(SystemExit) as exc:
        _run_maybe_async(rd.main)
    assert str(exc.value) == CONTAINMENT_MSG

    # main.process_workflow
    import main as main_mod

    monkeypatch.setattr(main_mod, "TEMP_DIR", str(tmp_path / "temp"), raising=False)
    monkeypatch.setattr(
        main_mod, "AUTH_STATE_FILE", str(tmp_path / "absent.json"), raising=False
    )
    monkeypatch.setattr(main_mod, "async_playwright", _fail_if_called, raising=False)
    monkeypatch.setattr(main_mod, "TEST_MODE", False, raising=False)
    with pytest.raises(RuntimeError) as exc:
        _run_maybe_async(main_mod.process_workflow, {"rubriques": []})
    assert str(exc.value) == CONTAINMENT_MSG

    # Both mode writers and the row editor.
    import browser.mode_conventionne as mc
    from browser.mode_normal import fill_mode_normal

    async def _async_noop(*args, **kwargs):
        return None

    monkeypatch.setattr(mc, "capture_screenshot", _async_noop, raising=False)

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(fill_mode_normal(MagicMock(), {"rubriques": []}, logger=FakeLogger()))
    assert str(exc.value) == CONTAINMENT_MSG

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            mc.fill_garage_conventionne(
                AsyncMock(), {"rubriques": []}, test_mode=False, logger=FakeLogger()
            )
        )
    assert str(exc.value) == CONTAINMENT_MSG

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            mc._edit_single_row_dynamic(
                AsyncMock(),
                {"rubrique": {"IdRubrique": "1"}, "target_label": "X", "target_index": 0},
                FakeLogger(),
            )
        )
    assert str(exc.value) == CONTAINMENT_MSG

    # trigger.py — refusal survives env flips; no HTTP call.
    try:
        import requests

        monkeypatch.setattr(requests, "post", _fail_if_called)
    except ImportError:
        pass
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(ROOT / "trigger.py"), run_name="__main__")
    assert str(exc.value) == CONTAINMENT_MSG
