"""
INC-00 §6.6 — garage_conventionne.py compatibility bridge: both re-exported
writer aliases refuse; preserved pure helpers still import.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

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


def test_both_reexported_writer_aliases_refuse(monkeypatch):
    import browser.mode_conventionne as mc
    import garage_conventionne as gc

    async def _async_noop(*args, **kwargs):
        return None

    monkeypatch.setattr(mc, "capture_screenshot", _async_noop, raising=False)

    for writer in (gc.fill_garage_conventionne, gc.fill_mode_conventionne):
        with pytest.raises(RuntimeError) as exc:
            asyncio.run(writer(MagicMock(), {"rubriques": []}, logger=FakeLogger()))
        assert str(exc.value) == CONTAINMENT_MSG


def test_preserved_helper_exports_still_import():
    from garage_conventionne import (  # noqa: F401
        GCLogger,
        RUBRIQUE_MATCH_ALIASES,
        _match_single_rubrique,
        match_all_rubriques,
    )

    assert callable(match_all_rubriques)
    assert callable(_match_single_rubrique)
    assert isinstance(RUBRIQUE_MATCH_ALIASES, dict)
    assert GCLogger is not None
