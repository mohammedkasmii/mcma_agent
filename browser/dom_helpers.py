"""
browser/dom_helpers.py — Safe DOM Field Interactions & Event Dispatchers
========================================================================
Robust input filling, option selection, checkbox toggling, and MCMA JavaScript
calculation event cascading.
"""

from typing import Optional, Any


async def safe_fill_input(page, selector: str, value: Any, timeout_ms: int = 2000) -> bool:
    """
    Safely fills an input field. Dispatches input, change, and keyup events
    (including inline onkeyup/onchange and jQuery triggers) so calculated fields update automatically.
    """
    if value is None or str(value).strip() == "":
        return False
    loc = page.locator(selector).first
    if await loc.count() == 0:
        return False
    try:
        if await loc.is_visible():
            await loc.fill(str(value), timeout=timeout_ms)
        else:
            await loc.evaluate("""(el, val) => {
                el.value = val;
            }""", str(value))

        # Fire full event cycle to trigger MCMA JavaScript calculations
        await loc.evaluate("""(el, val) => {
            el.value = val;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: '0' }));
            if (typeof el.onkeyup === 'function') {
                try { el.onkeyup(); } catch(e) {}
            }
            if (typeof el.onchange === 'function') {
                try { el.onchange(); } catch(e) {}
            }
            if (window.jQuery) {
                try { window.jQuery(el).trigger('input').trigger('change').trigger('keyup'); } catch(e) {}
            }
        }""", str(value))
        return True
    except Exception:
        try:
            await loc.evaluate("""(el, val) => {
                el.value = val;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
                if (typeof el.onkeyup === 'function') el.onkeyup();
                if (typeof el.onchange === 'function') el.onchange();
                if (window.jQuery) window.jQuery(el).trigger('keyup').trigger('change');
            }""", str(value))
            return True
        except Exception:
            return False


async def safe_select_option(page, selector: str, value: str) -> bool:
    """Safely selects an option from a <select> dropdown by value or label."""
    if not value or str(value).strip() == "":
        return False
    loc = page.locator(selector).first
    if await loc.count() == 0:
        return False
    try:
        try:
            await loc.select_option(value=str(value), timeout=1500)
        except Exception:
            try:
                await loc.select_option(label=str(value), timeout=1500)
            except Exception:
                await loc.evaluate("""(el, val) => {
                    for (let i = 0; i < el.options.length; i++) {
                        if (el.options[i].value == val || el.options[i].text.trim() == val.trim()) {
                            el.selectedIndex = i;
                            break;
                        }
                    }
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    if (typeof el.onchange === 'function') el.onchange();
                    if (window.jQuery) window.jQuery(el).trigger('change');
                }""", str(value))
        return True
    except Exception:
        return False


async def safe_toggle_checkbox(page, selector: str, checked: bool = True) -> bool:
    """Safely checks or unchecks a checkbox with full event dispatch."""
    loc = page.locator(selector).first
    if await loc.count() == 0:
        return False
    try:
        current_state = await loc.is_checked()
        if current_state != checked:
            try:
                await loc.set_checked(checked, timeout=1500)
            except Exception:
                await loc.evaluate("""(el, targetState) => {
                    el.checked = targetState;
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('click', { bubbles: true }));
                    if (typeof el.onclick === 'function') el.onclick();
                    if (typeof el.onchange === 'function') el.onchange();
                    if (window.jQuery) window.jQuery(el).trigger('change').trigger('click');
                }""", checked)
        return True
    except Exception:
        return False


async def trigger_mcma_calculations(page):
    """
    Executes MCMA native calculation JavaScript functions and dispatches
    events across calculation inputs.
    """
    try:
        await page.evaluate("""() => {
            if (typeof CalculerMntArrete === 'function') {
                try { CalculerMntArrete(); } catch(e) {}
            }
            if (typeof CalculerMontantDommage === 'function') {
                try { CalculerMontantDommage(); } catch(e) {}
            }
            if (typeof DevisCalculerMontantCharge === 'function') {
                try { DevisCalculerMontantCharge(); } catch(e) {}
            }
            const calcFields = [
                '#MontantReparation', '#MontantTVA', '#MontantTTC', '#TauxVetuste',
                '#MontantVetuste', '#MontantFranchise', '#PartResponsabilite',
                '#MontantRemise', '#MontantChargeSocietaire', '#MontantChargeMutuelle',
                '#DevisMontantTTC', '#DevisMontantTVA', '#DevisMontantVetusteTotal',
                '#DevisMontantFranchise', '#DevisMontantRemise',
                '#DevisMontantChargeSocietaire', '#DevisMontantChargeMutuelle'
            ];
            calcFields.forEach(sel => {
                const el = document.querySelector(sel);
                if (el) {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: '0' }));
                    if (typeof el.onkeyup === 'function') { try { el.onkeyup(); } catch(e) {} }
                    if (typeof el.onchange === 'function') { try { el.onchange(); } catch(e) {} }
                    if (window.jQuery) {
                        try { window.jQuery(el).trigger('input').trigger('change').trigger('keyup'); } catch(e) {}
                    }
                }
            });
        }""")
    except Exception:
        pass
