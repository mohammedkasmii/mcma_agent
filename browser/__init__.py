"""
browser package — Browser automation, safety interception, navigation, and repair mode controllers.
"""

from browser.dom_helpers import (
    safe_fill_input,
    safe_select_option,
    safe_toggle_checkbox,
    trigger_mcma_calculations,
)
from browser.safety_interceptor import install_safety_policy
from browser.mission_navigator import search_and_open_mission, check_session_validity
from browser.form_filler import fill_main_form
from browser.mode_normal import fill_mode_normal
from browser.mode_conventionne import fill_garage_conventionne, fill_mode_conventionne
from browser.notifications import fetch_all_notifications
