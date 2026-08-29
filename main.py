"""
main.py — Entry Point
=====================
Builds the FastAPI application and runs it on the office LAN.

Everything else lives in its own layer:
    api/        HTTP routes
    workflows/  business orchestrations
    portal/     everything that talks to the MCMA portal
    db/         the only module that touches SQLite
    core/       config, constants, operating window, feature flags
"""

import socket
import sys

from api import create_app
from core.features import FORM_FILLING_ENABLED
from core.window import WINDOW

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

app = create_app()


def _local_ip() -> str:
    """Best-effort LAN address, for the banner employees copy from."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def main() -> None:
    import uvicorn

    ip = _local_ip()
    window = WINDOW.status()

    print("\n" + "=" * 70)
    print("  🔔  MCMA SINISTRES — CENTRE DE NOTIFICATIONS & ACTIONS")
    print("=" * 70)
    print(f"  💻  Accès sur ce PC          : http://localhost:8000")
    print(f"  👥  Accès pour vos collègues : http://{ip}:8000")
    print("-" * 70)
    print(f"  ⏰  Horaires de synchronisation : "
          f"{WINDOW.start.strftime('%H:%M')} – {WINDOW.end.strftime('%H:%M')} "
          f"(toutes les {WINDOW.poll_interval_minutes} min)")
    print(f"  🌍  Fuseau horaire              : {window['timezone']}"
          + ("  ⚠️ FALLBACK — installez tzdata" if window.get("timezone_fallback") else ""))
    print(f"  📋  Portail actuellement        : "
          f"{'OUVERT' if window['open'] else 'FERMÉ (aucune interrogation)'}")
    print(f"  🛡️  Remplissage automatique     : "
          f"{'ACTIVÉ' if FORM_FILLING_ENABLED else 'DÉSACTIVÉ'}")
    print("=" * 70)
    print("  👉  Gardez cette fenêtre ouverte pour que le serveur reste actif.\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
