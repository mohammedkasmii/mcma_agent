"""
core/config.py — Central Configuration & Settings
==================================================
Global configuration parameters for the MCMA RPA automation system.
"""

import os

# =============================================================================
# ⚠️  SAFETY / TEST MODE
#
# NOTE: The form filling agent this flag governs is DISABLED entirely. See
#       core/features.py (FORM_FILLING_ENABLED) — that flag takes precedence and
#       is the one to change. TEST_MODE only matters once form filling is unlocked.
#
# When True:
#   - Network interception blocks the mutating POST endpoints listed in
#     browser/safety_interceptor.py — final validation, closure, row-level writes,
#     and GED writes. Blocked calls fail closed (HTTP 403 + "__mcma_blocked").
#   - #Enregistrer and #DEVISDET_Btn buttons are STRICTLY NEVER CLICKED
#   - GED document upload is disabled
#   - The browser pauses on-screen for human visual review
# When False (Production mode):
#   - Live saving and form submissions are enabled
#
# History: this comment previously claimed "all mutating POST endpoints" were
# blocked. That was inaccurate — row-level writes (createRapportDefDet,
# updateDevisDet) were not intercepted. Fixed; see BLUEPRINT §11.0.
# =============================================================================
TEST_MODE: bool = True

# Platform URLs
BASE_URL: str = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/"
DASHBOARD_URL: str = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/FrontExpert/"

# Local File Paths
AUTH_STATE_FILE: str = "mcma_auth_state.json"
TEMP_DIR: str = "temp"
LOGS_DIR: str = "logs"
SCREENSHOTS_DIR: str = os.path.join(LOGS_DIR, "screenshots")
INPUT_DOSSIER_DIR: str = "input_dossier"
INPUT_DOCS_DIR: str = "input_documents"

# Timeouts & Intervals (ms/seconds)
DEFAULT_PAGE_TIMEOUT_MS: int = 30000
DEFAULT_KEEP_ALIVE_MINUTES: int = 10
