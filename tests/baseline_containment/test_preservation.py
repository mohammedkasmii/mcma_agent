"""
INC-00 §6.15 — characterization: the preserved read/local features keep
working. Uses only synthetic temporary data; never launches a browser and
never invokes a route that can reach the portal.
"""

import ast
import builtins
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PRESERVED_ROUTE_PATHS = (
    "/api/v1/notifications",
    "/api/v1/auth/launch-login",
)


def test_health_returns_200():
    from fastapi.testclient import TestClient
    from main import app

    resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"


def test_notification_actions_and_cache_use_only_tmp_path(monkeypatch, tmp_path):
    import main as main_mod
    from fastapi.testclient import TestClient

    monkeypatch.setattr(main_mod, "LOGS_DIR", str(tmp_path))
    client = TestClient(main_mod.app)

    # Seed only synthetic temporary JSON.
    (tmp_path / "notification_actions.json").write_text(
        json.dumps({"SYNTH-1": {"status": "TODO", "note": "", "updated_at": "01/01/2026 00:00"}}),
        encoding="utf-8",
    )
    (tmp_path / "mcma_notifications.json").write_text(
        json.dumps({"categories": []}), encoding="utf-8"
    )

    resp = client.get("/api/v1/notification-actions")
    assert resp.status_code == 200
    assert "SYNTH-1" in resp.json().get("actions", {})

    resp = client.get("/api/v1/cached-notifications")
    assert resp.status_code == 200

    resp = client.post(
        "/api/v1/notification-actions",
        json={"reference": "SYNTH-2", "status": "DONE", "note": "synthetic"},
    )
    assert resp.status_code == 200
    saved = json.loads((tmp_path / "notification_actions.json").read_text(encoding="utf-8"))
    assert "SYNTH-2" in saved, "the action write must land under tmp_path only"


def test_browser_backed_routes_remain_registered_but_are_not_invoked():
    from main import app

    registered = {getattr(r, "path", None) for r in app.routes}
    for path in PRESERVED_ROUTE_PATHS:
        assert path in registered, f"preserved read/local route was removed: {path}"


def test_preserved_modules_import_without_launch_or_write(monkeypatch):
    import playwright.async_api as pa

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("Playwright was constructed at import time")

    monkeypatch.setattr(pa, "async_playwright", _fail_if_called)

    write_opens = []
    real_open = builtins.open

    def _guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in str(mode) for flag in ("w", "a", "x", "+")):
            write_opens.append((str(file), str(mode)))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _guarded_open)

    for mod_name in ("auth_setup", "session_keeper", "get_notifications", "browser.notifications"):
        sys.modules.pop(mod_name, None)
        importlib.import_module(mod_name)

    monkeypatch.setattr(builtins, "open", real_open)
    assert write_opens == [], f"import-time write-mode filesystem opens: {write_opens}"

    import auth_setup
    import browser.notifications as notifications
    import get_notifications
    import session_keeper

    assert callable(auth_setup.manual_login)
    assert callable(session_keeper.check_session_health)
    assert session_keeper.DEFAULT_INTERVAL_MINUTES == 10
    assert callable(get_notifications.run)
    assert callable(notifications.fetch_all_notifications)


def test_menu_options_2_to_6_remain_present():
    tree = ast.parse((ROOT / "menu.py").read_text(encoding="utf-8"))
    values = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Compare)
            and len(node.comparators) == 1
            and isinstance(node.comparators[0], ast.Constant)
        ):
            values.add(node.comparators[0].value)
    for option in ("2", "3", "4", "5", "6"):
        assert option in values, f"menu option {option} branch is missing"


def test_static_dashboard_mount_remains_registered():
    from main import app

    assert any(getattr(r, "name", "") == "static" for r in app.routes), (
        "the static dashboard mount was removed"
    )
