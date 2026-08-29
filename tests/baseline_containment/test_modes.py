"""
INC-00 §6.5 — all three baseline writer functions must hard-raise before any
Playwright/page interaction. Fake page + fake in-memory logger only; nothing
is written under logs/.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

CONTAINMENT_MSG = (
    "Baseline live-write capability was permanently removed at INC-00; "
    "the only live-write path is the post-G5 VerifiedMissionWriter."
)


class FakeLogger:
    """Explicit in-memory logger so no StructuredLogger file is ever created."""

    log_path = "<in-memory>"

    def __init__(self):
        self.entries = []

    def log(self, *args, **kwargs):
        self.entries.append((args, kwargs))

    def summary(self):
        return {"errors": 0, "log_file": self.log_path}


async def _async_noop(*args, **kwargs):
    return None


def test_mode_normal_fill_hard_raises_before_playwright():
    from browser.mode_normal import fill_mode_normal

    page = MagicMock()
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(fill_mode_normal(page, {"rubriques": []}, logger=FakeLogger()))
    assert str(exc.value) == CONTAINMENT_MSG
    assert page.mock_calls == [], "the contained writer touched the page object"


def test_mode_conventionne_fill_hard_raises_before_playwright(monkeypatch):
    import browser.mode_conventionne as mc

    monkeypatch.setattr(mc, "capture_screenshot", _async_noop, raising=False)
    page = AsyncMock()
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            mc.fill_garage_conventionne(
                page,
                {"rubriques": [], "dossier_reference": "SYNTH-REF"},
                logger=FakeLogger(),
            )
        )
    assert str(exc.value) == CONTAINMENT_MSG
    assert page.mock_calls == [], "the contained writer touched the page object"


def test_mode_conventionne_edit_row_hard_raises(monkeypatch):
    import browser.mode_conventionne as mc

    monkeypatch.setattr(mc, "capture_screenshot", _async_noop, raising=False)
    page = AsyncMock()
    match = {
        "rubrique": {"IdRubrique": "1", "MontantHT": "1.00", "Taxe": "0.20"},
        "target_label": "SYNTHETIC ROW",
        "target_index": 0,
        "match_method": "test",
    }
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(mc._edit_single_row_dynamic(page, match, FakeLogger()))
    assert str(exc.value) == CONTAINMENT_MSG
    assert page.mock_calls == [], "the contained row editor touched the page object"
