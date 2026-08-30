"""
mcma.core.config — typed settings (single source; supersedes the duplicated
baseline constants, F28). Stub established at INC-03; later increments extend
it. Fail-closed defaults only; no secrets ever live here.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Typed runtime settings. All later settings (DB path, TLS, DPAPI vault,
    retention, subnet allowlist) are added here as typed fields with
    fail-closed defaults — never as bare stringly-typed flags."""

    # DATA_MODEL.md §9: outside any served directory (mcma.web/static are
    # served; "var" is not).
    db_path: Path = Path("var") / "mcma.sqlite3"

    # The API binds loopback until INC-18 introduces TLS-only LAN serving.
    api_host: str = "127.0.0.1"
    api_port: int = 8000


def load_settings() -> Settings:
    """Returns the typed settings. Deterministic; reads no environment and no
    files at this increment."""
    return Settings()
