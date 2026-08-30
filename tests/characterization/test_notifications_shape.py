"""
INC-02 — shape characterization of the notification extraction output
(browser/notifications.py fetch_all_notifications), pinned against a saved
SANITIZED synthetic fixture — never live, never a browser.

The row parsing itself runs inside page.evaluate JS, so this characterization
pins (a) the result-document shape consumed by main.py's cached-notifications
route and the dashboard, and (b) the label vocabularies, via source pins.
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
FIXTURE = HERE.parent / "fixtures" / "characterization" / "notifications_shape_synthetic.json"

TOP_KEYS = {"timestamp", "total_categories", "total_alerts", "categories"}
CATEGORY_KEYS = {"category_name", "code_alerte", "count", "items"}
ITEM_KEYS = {
    "reference",
    "id_sinistre",
    "date_survenance",
    "societaire",
    "police",
    "matricule",
    "nature",
    "statut",
    "direct_url",
}


def _fixture():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data.pop("_comment", None)
    return data


def test_notification_document_shape():
    data = _fixture()
    assert set(data.keys()) == TOP_KEYS
    assert data["total_categories"] == len(data["categories"])
    total = 0
    for cat in data["categories"]:
        assert set(cat.keys()) == CATEGORY_KEYS
        assert cat["count"] == len(cat["items"])
        total += cat["count"]
        for item in cat["items"]:
            assert set(item.keys()) == ITEM_KEYS
            assert all(isinstance(v, str) for v in item.values())
    assert data["total_alerts"] == total


def test_notification_parser_source_still_produces_this_shape():
    """Source pin: the extraction module still emits exactly the item keys and
    label vocabularies this fixture captures (regression tripwire against a
    silent shape change before INC-14 re-implements extraction)."""
    src = (ROOT / "browser" / "notifications.py").read_text(encoding="utf-8")
    for key in ITEM_KEYS:
        assert f'"{key}"' in src, f"item key {key!r} vanished from the extractor"
    for token in ('"D": "DÉCLARÉ"', '"E": "EN COURS"', '"F": "FERMÉ"',
                  '"C": "CLÔTURÉ"', '"R": "RÉOUVERT"', '"CORPOREL"'):
        assert token in src, f"label vocabulary {token} vanished from the extractor"
    for key in ("timestamp", "total_categories", "total_alerts", "categories"):
        assert f'"{key}"' in src
