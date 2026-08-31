"""
mcma.portal.pec_live -- the SinAuto Garage Conventionné (PEC) DOM
mechanics, recovered from 8e5e4e6.

That commit was run by the developer against real MCMA PEC missions and
successfully edited their rows. It is the authority on how the portal is
driven.

PEC is structurally different from Mode Normal and is kept separate on
purpose. It never ADDS a row: Table 2 (#DevisDetTableVal) already
contains the garage's lines, and the job is to find each planned rubrique
among them and edit it in place. That is why matching, not row creation,
is most of this file.

The matching is all-or-nothing BEFORE the first pencil click. Half-editing
a dossier because the fourth rubrique turned out to have no row is worse
than editing none of it, and the portal offers no undo.

WHAT THIS MODULE IS NOT. No authorization, no lease, no identity or
workflow gate, no plan. VerifiedMissionWriter keeps all of that and calls
in here only once a mutation is permitted. Final actions are absent by
construction -- nothing here clicks Valider Devis, #DEVISDET_Btn,
Enregistrer or GED.
"""

from __future__ import annotations

from mcma.domain.normalize import normalize_text

TABLE_SELECTOR = "#DevisDetTableVal"

# Golden alias table (8e5e4e6). The garage's displayed labels do not match
# the MCMA catalog wording exactly, and this is the recovered mapping that
# worked against real dossiers.
RUBRIQUE_MATCH_ALIASES = {
    "1": [
        "fournitures carrosserie origines",
        "fournitures carrosserie origine",
        "pieces carrosserie origines",
        "pieces carrosserie origine",
        "fournitures carrosserie oem",
        "pieces origines",
    ],
    "2": [
        "fournitures carrosserie adaptables",
        "fournitures carrosserie adaptable",
        "pieces carrosserie adaptables",
        "pieces carrosserie adaptable",
        "pieces adaptables",
    ],
    "3": [
        "total pieces occasions recuperables",
        "total pieces occasions",
        "pieces occasions recuperables",
        "fournitures carrosserie recuperables",
        "fournitures carrosserie occasions",
        "pieces recuperables",
        "pieces occasions",
    ],
}

# Minimum length before a substring relation is allowed to match. Golden
# value: below this, short labels match almost anything.
SUBSTRING_MIN_LENGTH = 4

WAIT_AFTER_PENCIL_MS = 500
WAIT_AFTER_FILL_MS = 500
WAIT_AFTER_SAVE_MS = 2000
UPDATE_RESPONSE_TIMEOUT_MS = 5000

# --------------------------------------------------------------------- #
# Scripts -- verbatim from 8e5e4e6.
# --------------------------------------------------------------------- #

ENUMERATE_ROWS_JS = """() => {
    const rows = document.querySelectorAll('#DevisDetTableVal tbody tr');
    const out = [];
    rows.forEach((tr, index) => {
        const tds = tr.querySelectorAll('td');
        const cell = i => (tds[i] ? (tds[i].innerText || '').trim() : '');
        out.push({
            index: index,
            rubrique_label: cell(0),
            current_ht: cell(1),
            current_taxe: cell(2),
            current_ttc: cell(3),
            has_edit_btn: !!tr.querySelector(
                'a.edit-row, a#Modifier, a[onclick*="editRow"], i.fa-pencil'
            )
        });
    });
    return out;
}"""

# Re-locate by DISPLAYED LABEL, never by a stored index. The table is
# redrawn after every save, so a row reference from before the redraw is
# a reference to something that no longer exists.
RELOCATE_ROW_JS = """(targetLabel) => {
    const norm = s => (s || '').toString().normalize('NFD')
        .replace(/[\\u0300-\\u036f]/g, '').toLowerCase()
        .replace(/[^a-z0-9]+/g, ' ').trim();
    const rows = document.querySelectorAll('#DevisDetTableVal tbody tr');
    const want = norm(targetLabel);
    for (let i = 0; i < rows.length; i++) {
        const tds = rows[i].querySelectorAll('td');
        const label = tds[0] ? (tds[0].innerText || '').trim() : '';
        if (norm(label) === want) return i;
    }
    return -1;
}"""

CLICK_PENCIL_JS = """(idx) => {
    const row = document.querySelectorAll('#DevisDetTableVal tbody tr')[idx];
    if (!row) return { ok: false, error: 'Row disappeared' };
    let editBtn = row.querySelector(
        'a.edit-row, a#Modifier, a[onclick*="editRow"], a[title*="Modifier"], i.fa-pencil'
    );
    if (!editBtn) return { ok: false, error: 'No edit control found in row' };
    const clickable = editBtn.closest('a') || editBtn;
    clickable.click();
    return { ok: true };
}"""

# Unsuffixed ids. The portal exposes ONE editing row at a time, which is
# why the golden code addressed them directly. Suffixed forms
# (#MontantHTValide_<id>) exist only in this repository's mock.
FILL_ROW_JS = """(args) => {
    const { ht, taxe, tauxVet, mtVet } = args;
    const res = {};

    function setVal(sel, val) {
        const el = document.querySelector(sel);
        if (!el) return { found: false, selector: sel };
        el.value = val;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: '0' }));
        if (typeof el.onkeyup === 'function') { try { el.onkeyup(); } catch(e) {} }
        if (typeof el.onchange === 'function') { try { el.onchange(); } catch(e) {} }
        if (window.jQuery) {
            try { window.jQuery(el).trigger('input').trigger('change').trigger('keyup'); } catch(e) {}
        }
        return { found: true, val: val, readBack: el.value };
    }

    res.ht = setVal('#MontantHTValide', ht);
    res.taxe = setVal('#TaxeValide', taxe);
    if (tauxVet && tauxVet !== '0.00' && tauxVet !== '0') {
        res.tauxVet = setVal('#TauxVetusteValide', tauxVet);
    }
    if (mtVet && mtVet !== '0.00' && mtVet !== '0') {
        res.mtVet = setVal('#MontantVetusteValide', mtVet);
    }

    const ttcEl = document.querySelector('#MontantTTCValide');
    res.ttc_computed = ttcEl ? ttcEl.value : null;
    return res;
}"""

CLICK_SAVE_JS = """(idx) => {
    const row = document.querySelectorAll('#DevisDetTableVal tbody tr')[idx];
    if (!row) return { ok: false, error: 'Row disappeared' };

    let saveBtn = row.querySelector(
        'a.save-row, a:has(.fa-check), a[onclick*="saveRow"], a[title*="Enregistrer"], i.fa-check'
    );
    if (saveBtn) {
        const clickable = saveBtn.closest('a') || saveBtn;
        clickable.click();
        return { ok: true };
    }
    return { ok: false, error: 'No checkmark/save button found in row' };
}"""

CLICK_SAVE_FALLBACK_JS = """(idx) => {
    const row = document.querySelectorAll('#DevisDetTableVal tbody tr')[idx];
    if (row) {
        const btn = row.querySelector(
            'a.save-row, a:has(.fa-check), a[onclick*="saveRow"], i.fa-check'
        );
        if (btn) (btn.closest('a') || btn).click();
    }
}"""

TRIGGER_CALCULATIONS_JS = """() => {
    const results = {};
    if (typeof DevisCalculerMontantCharge === 'function') {
        try { DevisCalculerMontantCharge(); results.devisCalc = 'executed'; }
        catch(e) { results.devisCalc = 'error'; }
    } else {
        results.devisCalc = 'not_present';
    }

    if (typeof CalculerMntArrete === 'function') {
        try { CalculerMntArrete(); results.arrete = 'executed'; } catch(e) {}
    }

    const selectors = [
        '#DevisMontantTTC', '#DevisMontantTVA', '#DevisMontantVetusteTotal',
        '#DevisMontantFranchise', '#DevisMontantRemise', '#DevisPartResponsabilite',
        '#DevisTvaRecupI', '#MontantReparation'
    ];
    selectors.forEach(sel => {
        const el = document.querySelector(sel);
        if (el) {
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            if (window.jQuery) {
                try { window.jQuery(el).trigger('keyup').trigger('change'); } catch(e) {}
            }
        }
    });

    return results;
}"""

READ_FINANCIAL_SUMMARY_JS = """() => {
    const read = sel => {
        const el = document.querySelector(sel);
        return el ? (el.value !== undefined ? el.value : el.textContent) : null;
    };
    return {
        total_tva: read('#DevisMontantTVA'),
        total_ttc: read('#DevisMontantTTC'),
        vetuste: read('#DevisMontantVetusteTotal'),
        franchise: read('#DevisMontantFranchise'),
        remise: read('#DevisMontantRemise'),
        part_responsabilite: read('#DevisPartResponsabilite'),
        tva_recuperable: read('#DevisTvaRecupI'),
        montant_arrete: read('#MontantArrete'),
        base_indemnite: read('#BaseIndemnite'),
        charge_mutuelle: read('#DevisMontantChargeMutuelle'),
        charge_societaire: read('#DevisMontantChargeSocietaire')
    };
}"""


# --------------------------------------------------------------------- #
# Matching -- golden, pure, and testable without a browser.
# --------------------------------------------------------------------- #


class UnmatchedRubrique(Exception):
    """At least one planned rubrique has no row in Table 2. Raised BEFORE
    any mutation: the whole edit is abandoned rather than half-applied."""

    def __init__(self, unmatched):
        self.unmatched = tuple(unmatched)
        super().__init__(
            f"{len(self.unmatched)} planned rubrique(s) could not be matched to a "
            f"Table 2 row: {sorted(self.unmatched)} — zero writes"
        )


def match_single_rubrique(rubrique_id: str, label: str, table_rows, used_indices):
    """Golden three-step match, in golden order: exact normalized label,
    then a known alias for that rubrique id, then a substring relation of
    at least SUBSTRING_MIN_LENGTH characters.

    `used_indices` is what stops two planned rubriques consuming the same
    portal row -- without it, two lines whose labels both loosely resemble
    one row would silently overwrite each other."""
    wanted = normalize_text(label)

    for row in table_rows:
        if row["index"] in used_indices:
            continue
        if wanted and wanted == normalize_text(row["rubrique_label"]):
            return row, f"exact_label ({wanted!r})"

    for row in table_rows:
        if row["index"] in used_indices:
            continue
        row_label = normalize_text(row["rubrique_label"])
        for alias in RUBRIQUE_MATCH_ALIASES.get(str(rubrique_id), ()):
            normalized_alias = normalize_text(alias)
            if normalized_alias and (
                normalized_alias == row_label
                or normalized_alias in row_label
                or row_label in normalized_alias
            ):
                return row, f"known_alias ({alias!r})"

    for row in table_rows:
        if row["index"] in used_indices:
            continue
        row_label = normalize_text(row["rubrique_label"])
        if len(wanted) >= SUBSTRING_MIN_LENGTH and (
            wanted in row_label or row_label in wanted
        ):
            return row, f"substring ({wanted!r} ~ {row_label!r})"

    return None, None


def match_all_rubriques(planned, table_rows):
    """All-or-nothing preflight. `planned` is a sequence of
    (rubrique_id, label). Raises UnmatchedRubrique if ANY one fails --
    before a single pencil is clicked."""
    matches = []
    used_indices = set()
    unmatched = []

    for rubrique_id, label in planned:
        row, method = match_single_rubrique(rubrique_id, label, table_rows, used_indices)
        if row is None:
            unmatched.append(str(rubrique_id))
            continue
        matches.append(
            {
                "rubrique_id": str(rubrique_id),
                "target_label": row["rubrique_label"],
                "target_index": row["index"],
                "match_method": method,
            }
        )
        used_indices.add(row["index"])

    if unmatched:
        raise UnmatchedRubrique(unmatched)
    return matches


# --------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------- #


class PecLiveDriver:
    """Live-tested SinAuto PEC interaction recovered from 8e5e4e6."""

    def __init__(self, page):
        self._page = page

    async def table_present(self) -> bool:
        return await self._page.locator(TABLE_SELECTOR).count() > 0

    async def enumerate_rows(self):
        return await self._page.evaluate(ENUMERATE_ROWS_JS)

    async def relocate_row(self, target_label: str) -> int:
        """Index of the row whose displayed label matches, or -1. Called
        again after every redraw -- a stale index is a wrong row."""
        return await self._page.evaluate(RELOCATE_ROW_JS, target_label)

    async def click_pencil(self, index: int) -> dict:
        result = await self._page.evaluate(CLICK_PENCIL_JS, index)
        await self._page.wait_for_timeout(WAIT_AFTER_PENCIL_MS)
        return result

    async def fill_editing_row(self, ht: str, taxe: str, taux_vetuste: str, montant_vetuste: str) -> dict:
        result = await self._page.evaluate(
            FILL_ROW_JS,
            {"ht": ht, "taxe": taxe, "tauxVet": taux_vetuste, "mtVet": montant_vetuste},
        )
        await self._page.wait_for_timeout(WAIT_AFTER_FILL_MS)
        return result

    async def click_save_and_await_update(self, index: int) -> dict:
        """Clicks the row checkmark while watching for the portal's own
        update response.

        The ONLY network fact the golden code established is that a
        response arrives whose URL CONTAINS "updateDevisDet". It matched
        on that substring and checked the status; it never asserted the
        full path, the method or a JSON body, so none of those are
        required here. A missing response is reported, not treated as
        failure -- the golden code fell back to clicking directly and
        letting the read-back decide."""
        observed = {"response_seen": False, "status": None, "clicked": False}
        try:
            async with self._page.expect_response(
                lambda r: "updateDevisDet" in r.url, timeout=UPDATE_RESPONSE_TIMEOUT_MS
            ) as response_info:
                click_result = await self._page.evaluate(CLICK_SAVE_JS, index)
                if not click_result.get("ok"):
                    observed["error"] = click_result.get("error")
                    return observed
                observed["clicked"] = True
            response = await response_info.value
            observed["response_seen"] = True
            observed["status"] = response.status
        except Exception:
            if not observed["clicked"]:
                await self._page.evaluate(CLICK_SAVE_FALLBACK_JS, index)
                observed["clicked"] = True
        await self._page.wait_for_timeout(WAIT_AFTER_SAVE_MS)
        return observed

    async def trigger_native_calculations(self) -> dict:
        return await self._page.evaluate(TRIGGER_CALCULATIONS_JS)

    async def read_financial_summary(self) -> dict:
        return await self._page.evaluate(READ_FINANCIAL_SUMMARY_JS)
