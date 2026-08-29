"""
tools package — developer and fallback command-line utilities.

Not part of the running service. Run from the project root as modules so the
project packages resolve:

    python -m tools.auth_setup          single-account OTP login (fallback;
                                        prefer the dashboard's per-account button)
    python -m tools.get_notifications   one-off alert extraction to JSON
    python -m tools.session_keeper      legacy session heartbeat / --check
    python -m tools.run_dossier         Phase 2 filling CLI (DISABLED)
    python tools/mock_server.py         offline stand-in for the MCMA portal
"""
