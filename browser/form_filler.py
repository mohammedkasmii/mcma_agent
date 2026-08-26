"""
browser/form_filler.py — Header & Demographic Form Filling Controller
======================================================================
Fills main form text inputs, select dropdowns, and checkboxes on the MCMA mission form.
"""

from typing import Dict, Any
from browser.dom_helpers import (
    safe_fill_input,
    safe_select_option,
    safe_toggle_checkbox,
    trigger_mcma_calculations,
)


async def fill_main_form(
    page,
    text_fields: Dict[str, Any],
    select_fields: Dict[str, Any],
    checkboxes: Dict[str, bool],
):
    """
    Fills header inputs, demographic fields, dropdowns, and checkboxes.
    """
    # 1. Text Fields
    print("[*] Filling main form text fields...")
    for field_id, value in text_fields.items():
        if value is not None and str(value).strip() != "":
            selector = f"#{field_id}"
            filled = await safe_fill_input(page, selector, str(value))
            if filled:
                print(f"    [✓] Filled text field #{field_id} = {str(value)[:40]}...")
            elif field_id in ("ValeurVenale", "ValeurVenaleEstime"):
                alt_id = "ValeurVenaleEstime" if field_id == "ValeurVenale" else "ValeurVenale"
                alt_filled = await safe_fill_input(page, f"#{alt_id}", str(value))
                if alt_filled:
                    print(f"    [✓] Filled text field #{alt_id} = {str(value)[:40]}...")
                else:
                    print(f"    [!] Field #{field_id} skipped (not on page)")
            else:
                print(f"    [!] Field #{field_id} not present/visible (skipped)")

    # Trigger initial calculations
    await trigger_mcma_calculations(page)

    # 2. Select Dropdowns
    print("[*] Selecting dropdown options...")
    for field_id, value in select_fields.items():
        if value is not None and str(value).strip() != "":
            selector = f"#{field_id}"
            selected = await safe_select_option(page, selector, str(value))
            if selected:
                print(f"    [✓] Selected #{field_id} = {value}")
            else:
                print(f"    [!] Dropdown #{field_id} not present/visible (skipped)")

    # 3. Checkboxes
    print("[*] Toggling checkboxes...")
    for field_id, is_checked in checkboxes.items():
        selector = f"#{field_id}"
        toggled = await safe_toggle_checkbox(page, selector, is_checked)
        if toggled:
            print(f"    [✓] Toggled checkbox #{field_id} -> {is_checked}")
        else:
            print(f"    [!] Checkbox #{field_id} not present/visible (skipped)")

    await page.wait_for_timeout(500)
