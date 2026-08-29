"""
INC-00 §6.3 — main.process_workflow must hard-raise before any Playwright construction.
"""

import asyncio
import inspect

import pytest

CONTAINMENT_MSG = (
    "Baseline live-write capability was permanently removed at INC-00; "
    "the only live-write path is the post-G5 VerifiedMissionWriter."
)


def _fail_if_called(*args, **kwargs):
    raise AssertionError("Playwright construction was attempted; containment is missing")


def test_process_workflow_hard_raises(monkeypatch, tmp_path):
    import main as main_mod

    # RED-run guards: no repository temp directory, no real session path, no browser.
    monkeypatch.setattr(main_mod, "TEMP_DIR", str(tmp_path / "temp"), raising=False)
    monkeypatch.setattr(
        main_mod, "AUTH_STATE_FILE", str(tmp_path / "absent_auth_state.json"), raising=False
    )
    monkeypatch.setattr(main_mod, "async_playwright", _fail_if_called, raising=False)

    with pytest.raises(RuntimeError) as exc:
        result = main_mod.process_workflow({"matricule": "0000-A-0", "rubriques": []})
        if inspect.iscoroutine(result):
            asyncio.run(result)
    assert str(exc.value) == CONTAINMENT_MSG
