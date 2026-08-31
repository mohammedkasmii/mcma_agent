"""
mcma.portal.mode_normal_live -- the SinAuto Mode Normal DOM mechanics,
recovered from 9a2c57c.

That commit was run by the developer against real MCMA dossiers and
successfully added rubriques, clicked the real row checkmarks and
triggered the portal's own calculations. It is therefore the authority on
HOW the portal is driven -- not the mock, and not this architecture's
earlier guesses.

Everything here is a faithful port. Where the golden code looked
over-engineered, that is the point: `safe_fill_input` dispatches
input/change/keyup AND calls inline onkeyup/onchange AND fires jQuery
triggers because this legacy portal needed all of it before its
calculated fields updated. `safe_select_option` destroys and reinitialises
Select2 because the native <select> is otherwise invisible to Playwright.
Simplifying either to a plain .fill()/.select_option() is how this stops
working against the real page.

WHAT THIS MODULE IS NOT. It holds no authorization, no lease, no identity
or workflow gate, and no plan. It is given a Playwright page and told what
to type. VerifiedMissionWriter keeps every safety decision, and calls in
here only once it has already decided a mutation is permitted -- the
golden commits define portal mechanics, never authorization.

Final actions are absent by construction: nothing here clicks Valider,
Cloture, Enregistrer or GED, and mcma.portal.final_endpoints blocks them
at the network layer regardless.
"""

from __future__ import annotations

# --------------------------------------------------------------------- #
# Selector families -- golden, in golden order.
# --------------------------------------------------------------------- #
# Order matters: the unsuffixed id first, then name-based fallbacks. The
# real portal exposes ONE editing row at a time with unsuffixed ids, which
# is why the golden code could address #MontantHT directly. Suffixed forms
# (#MontantHT_<tempId>) are a mock invention and appear nowhere in
# 9a2c57c.

VEH_REPARE_SELECTOR = "#VehRepareI"

AJOUTER_SELECTOR = (
    "a.btn-success:has-text('Ajouter'), a:has-text('Ajouter +'), a[onclick*='addRow']"
)
AJOUTER_CLICK_FALLBACK_JS = "const b = document.querySelector('a.btn-success'); if(b) b.click();"
AJOUTER_DATATABLE_FALLBACK_JS = (
    "if (typeof edataTable_RapportDet !== 'undefined') edataTable_RapportDet.addRow();"
)

ID_RUBRIQUE_SELECTOR = "#IdRubrique, table select[name*='IdRubrique'], select[name*='IdRubrique']"
MONTANT_HT_SELECTOR = "#MontantHT, table input[name*='MontantHT'], input[name*='MontantHT']"
TAXE_SELECTOR = "#Taxe, table input[name*='Taxe'], input[name*='Taxe']"

# Method A: the checkmark lives in the 7th column of the row that holds
# the editable field.
CHECKMARK_COLUMN_SELECTOR = (
    "table tr:has(#MontantHT) td:nth-child(7) a, "
    "table tr:has(#MontantHT) td:nth-child(7), "
    "table tbody tr:first-child td:nth-child(7) a, "
    "table tbody tr:first-child td:nth-child(7)"
)

# Golden waits. Kept as named constants rather than inlined magic numbers,
# but NOT shortened: they exist because the portal redraws its table over
# AJAX and the next rubrique cannot be typed into a table that is still
# rebuilding.
WAIT_AFTER_AJOUTER_MS = 1000
WAIT_BEFORE_CHECKMARK_MS = 600
WAIT_AFTER_CHECKMARK_MS = 2000


# --------------------------------------------------------------------- #
# Scripts -- verbatim from 9a2c57c.
# --------------------------------------------------------------------- #

FILL_INPUT_JS = """(el, val) => {
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
}"""

FILL_INPUT_FALLBACK_JS = """(el, val) => {
    el.value = val;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
    if (typeof el.onkeyup === 'function') el.onkeyup();
    if (typeof el.onchange === 'function') el.onchange();
    if (window.jQuery) window.jQuery(el).trigger('keyup').trigger('change');
}"""

SELECT_OPTION_JS = """([sel, val]) => {
    const el = document.querySelector(sel);
    if (!el) return 'not_found';

    const hasSelect2 = (typeof jQuery !== 'undefined') && jQuery(sel).data('select2');

    if (hasSelect2) {
        try { jQuery(sel).select2('destroy'); } catch(e) {}
    }

    el.value = val;

    if (el.value != val) {
        for (let opt of el.options) {
            if (opt.value == val) {
                opt.selected = true;
                el.value = val;
                break;
            }
        }
    }

    el.dispatchEvent(new Event('change', { bubbles: true }));

    if (hasSelect2 && typeof jQuery !== 'undefined') {
        try {
            jQuery(sel).select2();
            jQuery(sel).trigger('change');
        } catch(e) {}
    }

    return el.value == val ? 'ok' : 'mismatch';
}"""

# Method B: closest row of the editable field, seventh cell, its clickable
# descendant. Runs even when Method A appeared to succeed -- the golden
# code did both, and a click that lands twice on an already-saved row is
# harmless while a missed save is not.
CHECKMARK_JS = """() => {
    const ht = document.querySelector("#MontantHT") || document.querySelector("#IdRubrique");
    const row = ht ? ht.closest("tr") : document.querySelector("table tbody tr");
    if (row) {
        const tds = row.querySelectorAll("td");
        if (tds.length >= 7) {
            const btn = tds[6].querySelector("a, button, i, span") || tds[6];
            btn.click();
            return true;
        }
    }
    return false;
}"""

# The portal's OWN calculation functions. Guarded with typeof because the
# golden code guarded them; an absent function must not throw mid-write.
#
# One deliberate omission from the golden source: it also wrote
# #MontantChargeMutuelle and #MontantChargeSocietaire directly.
# BUSINESS_RULES.md B.3 forbids that -- the split is the portal's to
# compute -- so those two selectors appear here only in the read sweep
# below, never as a write. The golden commit defines mechanics, not
# business rules.
TRIGGER_CALCULATIONS_JS = """() => {
    if (typeof CalculerMontantDommage === 'function') {
        try { CalculerMontantDommage(); } catch(e) {}
    }
    if (typeof CalculerMntArrete === 'function') {
        try { CalculerMntArrete(); } catch(e) {}
    }
    if (typeof CalculerMontantTTC === 'function') {
        try { CalculerMontantTTC(); } catch(e) {}
    }
    if (typeof CalculerMontantVetuste === 'function') {
        try { CalculerMontantVetuste(); } catch(e) {}
    }

    const calcSelectors = [
        '#ValeurVenale', '#MontantEpave', '#MontantReparation',
        '#MontantTVA', '#MontantVetusteTotal', '#MontantFranchise',
        '#MontantRemise', '#MontantArrete', '#BaseIndemnite', '#MontantDommage'
    ];
    calcSelectors.forEach(sel => {
        const el = document.querySelector(sel);
        if (el) {
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            if (typeof el.onkeyup === 'function') {
                try { el.onkeyup(); } catch(e) {}
            }
            if (typeof el.onchange === 'function') {
                try { el.onchange(); } catch(e) {}
            }
            if (window.jQuery) {
                try { window.jQuery(el).trigger('keyup').trigger('change'); } catch(e) {}
            }
        }
    });

    return {
        montantArrete: document.querySelector('#MontantArrete')?.value || null,
        baseIndemnite: document.querySelector('#BaseIndemnite')?.value || null,
        montantDommage: document.querySelector('#MontantDommage')?.value || null
    };
}"""

# Read-only sweep of the summary the portal computed. Never written.
READ_FINANCIAL_SUMMARY_JS = """() => {
    const read = sel => {
        const el = document.querySelector(sel);
        return el ? (el.value !== undefined ? el.value : el.textContent) : null;
    };
    return {
        montant_reparation: read('#MontantReparation'),
        total_tva: read('#MontantTVA'),
        total_ttc: read('#MontantTTC'),
        vetuste: read('#MontantVetusteTotal'),
        franchise: read('#MontantFranchise'),
        remise: read('#MontantRemise'),
        montant_arrete: read('#MontantArrete'),
        base_indemnite: read('#BaseIndemnite'),
        charge_mutuelle: read('#MontantChargeMutuelle'),
        charge_societaire: read('#MontantChargeSocietaire')
    };
}"""


# --------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------- #


class ModeNormalLiveDriver:
    """Live-tested SinAuto Mode Normal interaction recovered from 9a2c57c."""

    def __init__(self, page):
        self._page = page

    # -- primitives ------------------------------------------------------

    async def safe_fill_input(self, selector: str, value: str, timeout_ms: int = 2000) -> bool:
        """Golden safe_fill_input. Playwright fill when the element is
        visible, a direct value assignment when it is not, and then the
        full event cascade in both cases -- .fill() alone does not run the
        portal's inline onkeyup/onchange handlers or its jQuery bindings,
        which is what makes the calculated fields update."""
        if not value or str(value).strip() == "":
            return False
        locator = self._page.locator(selector).first
        if await locator.count() == 0:
            return False
        try:
            if await locator.is_visible():
                await locator.fill(str(value), timeout=timeout_ms)
            else:
                await locator.evaluate("(el, val) => { el.value = val; }", str(value))
            await locator.evaluate(FILL_INPUT_JS, str(value))
            return True
        except Exception:
            try:
                await locator.evaluate(FILL_INPUT_FALLBACK_JS, str(value))
                return True
            except Exception:
                return False

    async def safe_select_option(self, selector: str, value: str, timeout_ms: int = 2000) -> bool:
        """Golden safe_select_option. Select2 hides the native <select>,
        so it is destroyed, the value set and verified against the option
        list, change dispatched, and Select2 reinitialised."""
        if not value or str(value).strip() == "":
            return False
        locator = self._page.locator(selector).first
        if await locator.count() == 0:
            return False
        try:
            result = await self._page.evaluate(SELECT_OPTION_JS, [selector, str(value)])
            if result == "ok":
                return True
        except Exception:
            pass
        try:
            if await locator.is_visible():
                await locator.select_option(str(value), timeout=timeout_ms)
                return True
        except Exception:
            pass
        return False

    async def ensure_vehicle_repairable(self) -> bool:
        """#VehRepareI must be checked or the rubriques table is not
        displayed at all."""
        locator = self._page.locator(VEH_REPARE_SELECTOR).first
        if await locator.count() == 0:
            return False
        try:
            if await locator.is_checked():
                return True
        except Exception:
            pass
        try:
            await locator.check(timeout=2000)
            return True
        except Exception:
            try:
                await locator.evaluate(
                    "(el) => { el.checked = true; "
                    "el.dispatchEvent(new Event('change', { bubbles: true })); "
                    "if (window.jQuery) { try { window.jQuery(el).trigger('change'); } catch(e) {} } }"
                )
                return True
            except Exception:
                return False

    async def click_ajouter(self) -> None:
        """Golden add-row control, with both golden fallbacks: a bare
        .btn-success click, then the DataTable API."""
        button = self._page.locator(AJOUTER_SELECTOR).first
        if await button.count() > 0:
            try:
                await button.scroll_into_view_if_needed(timeout=1500)
                await button.click(timeout=2500, force=True)
            except Exception:
                await self._page.evaluate(AJOUTER_CLICK_FALLBACK_JS)
        else:
            await self._page.evaluate(AJOUTER_DATATABLE_FALLBACK_JS)
        await self._page.wait_for_timeout(WAIT_AFTER_AJOUTER_MS)

    async def fill_new_row(self, rubrique_id: str, montant_ht: str, taxe: str) -> None:
        await self.safe_select_option(ID_RUBRIQUE_SELECTOR, rubrique_id)
        await self.safe_fill_input(MONTANT_HT_SELECTOR, montant_ht)
        # Golden guard: a zero tax is not typed at all.
        if taxe and str(taxe) != "0":
            await self.safe_fill_input(TAXE_SELECTOR, taxe)
        await self._page.wait_for_timeout(WAIT_BEFORE_CHECKMARK_MS)

    async def click_row_checkmark(self) -> None:
        """Both golden methods, in golden order. Method A is a Playwright
        click on the 7th column; Method B is the JS equivalent, and the
        golden code ran it unconditionally afterwards rather than only on
        failure -- a duplicate click on a saved row is harmless, a missed
        save is not."""
        column = self._page.locator(CHECKMARK_COLUMN_SELECTOR).first
        if await column.count() > 0:
            try:
                await column.click(timeout=2000, force=True)
            except Exception:
                pass
        await self._page.evaluate(CHECKMARK_JS)
        await self._page.wait_for_timeout(WAIT_AFTER_CHECKMARK_MS)

    # -- composed operation ---------------------------------------------

    async def add_rubrique_row(self, rubrique_id: str, montant_ht: str, taxe: str) -> None:
        """The complete golden add-a-row lifecycle.

        Deliberately NOT gated on a network response. The golden Mode
        Normal write was the DOM interaction; it never observed
        createRapportDefDet, and that endpoint appears nowhere in the
        golden commits -- only in this repository's mock. Requiring it
        would fail a write that actually succeeded."""
        await self.ensure_vehicle_repairable()
        await self.click_ajouter()
        await self.fill_new_row(rubrique_id, montant_ht, taxe)
        await self.click_row_checkmark()

    async def trigger_native_calculations(self) -> dict:
        """Invokes the portal's own calculation functions and returns what
        it computed. Never writes the charge split."""
        return await self._page.evaluate(TRIGGER_CALCULATIONS_JS)

    async def read_financial_summary(self) -> dict:
        return await self._page.evaluate(READ_FINANCIAL_SUMMARY_JS)
