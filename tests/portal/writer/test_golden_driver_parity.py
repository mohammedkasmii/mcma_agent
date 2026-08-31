"""The live drivers must reproduce the golden commits, not approximate them.

`9a2c57c` (Mode Normal) and `8e5e4e6` (PEC) were run by the developer
against real MCMA dossiers and worked. Where this architecture's earlier
guesses disagree with them, they are wrong -- so these tests check two
things: that the ported scripts are byte-identical to the golden source
where it matters, and that the behaviour around them is right.

String-presence alone would not be enough, so the matching, the selector
fallback ordering, the event cascade and the save path are all driven
against fake pages.
"""

import asyncio
import subprocess

import pytest

from mcma.portal import mode_normal_live as normal
from mcma.portal import pec_live as pec

MODE_NORMAL_GOLDEN = "9a2c57c"
PEC_GOLDEN = "8e5e4e6"


def _golden(commit, path):
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"], capture_output=True, text=True
    )
    if result.returncode != 0:
        pytest.skip(f"golden commit {commit} is not present in this clone")
    return result.stdout


def _squash(text):
    """Compares JS ignoring indentation only -- token order, event names
    and guards must still match exactly."""
    return " ".join(text.split())


def _run(coro):
    return asyncio.run(coro)


def _code_only(module):
    """Module source with docstrings and comments removed.

    Scanning raw source would match the prose that EXPLAINS why a name is
    absent -- the docstring saying "no lease, no authorization" would fail
    a test asserting those words do not appear."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            docstring = ast.get_docstring(node)
            if docstring and node.body and isinstance(node.body[0], ast.Expr):
                node.body.pop(0)
                if not node.body:
                    node.body.append(ast.Pass())
    return ast.unparse(ast.fix_missing_locations(tree))


# --------------------------------------------------------------------- #
# Byte parity with the golden source
# --------------------------------------------------------------------- #


def test_mode_normal_event_cascade_is_the_golden_one():
    """.fill() alone does not run the portal's inline onkeyup/onchange or
    its jQuery bindings, which is why the calculated fields did not update
    before. Every element of the cascade must survive the port."""
    source = _golden(MODE_NORMAL_GOLDEN, "main.py")
    ported = _squash(normal.FILL_INPUT_JS)
    for fragment in (
        "el.dispatchEvent(new Event('input', { bubbles: true }));",
        "el.dispatchEvent(new Event('change', { bubbles: true }));",
        "el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: '0' }));",
        "if (typeof el.onkeyup === 'function')",
        "if (typeof el.onchange === 'function')",
        "window.jQuery(el).trigger('input').trigger('change').trigger('keyup');",
    ):
        assert _squash(fragment) in ported
        assert _squash(fragment) in _squash(source)


def test_mode_normal_select2_handling_is_the_golden_one():
    source = _squash(_golden(MODE_NORMAL_GOLDEN, "main.py"))
    ported = _squash(normal.SELECT_OPTION_JS)
    for fragment in (
        "jQuery(sel).data('select2')",
        "jQuery(sel).select2('destroy');",
        "for (let opt of el.options)",
        "jQuery(sel).select2();",
        "jQuery(sel).trigger('change');",
    ):
        assert _squash(fragment) in ported
        assert _squash(fragment) in source


def test_mode_normal_checkmark_js_is_the_golden_one():
    source = _squash(_golden(MODE_NORMAL_GOLDEN, "main.py"))
    assert _squash(normal.CHECKMARK_JS) in source


def test_mode_normal_calculation_functions_are_the_golden_ones():
    source = _squash(_golden(MODE_NORMAL_GOLDEN, "main.py"))
    ported = _squash(normal.TRIGGER_CALCULATIONS_JS)
    for function in (
        "CalculerMontantDommage", "CalculerMntArrete",
        "CalculerMontantTTC", "CalculerMontantVetuste",
    ):
        assert f"typeof {function} === 'function'" in ported
        assert f"typeof {function} === 'function'" in source


def test_the_prohibited_charge_write_was_not_ported():
    """The golden code also wrote #MontantChargeMutuelle and
    #MontantChargeSocietaire directly. BUSINESS_RULES.md B.3 forbids that
    -- the split is the portal's to compute. Mechanics are ported from the
    golden commits; business rules are not."""
    for script in (normal.TRIGGER_CALCULATIONS_JS, normal.FILL_INPUT_JS):
        assert "MontantChargeMutuelle" not in script
        assert "MontantChargeSocietaire" not in script
    # They ARE read back.
    assert "MontantChargeMutuelle" in normal.READ_FINANCIAL_SUMMARY_JS


def test_pec_scripts_are_the_golden_ones():
    source = _squash(_golden(PEC_GOLDEN, "garage_conventionne.py"))
    for fragment in (
        "res.ht = setVal('#MontantHTValide', ht);",
        "res.taxe = setVal('#TaxeValide', taxe);",
        "setVal('#TauxVetusteValide', tauxVet)",
        "setVal('#MontantVetusteValide', mtVet)",
        "a.save-row, a:has(.fa-check), a[onclick*=\"saveRow\"]",
        "a.edit-row, a#Modifier, a[onclick*=\"editRow\"]",
        "typeof DevisCalculerMontantCharge === 'function'",
    ):
        assert _squash(fragment) in _squash(pec.FILL_ROW_JS + pec.CLICK_SAVE_JS
                                           + pec.CLICK_PENCIL_JS + pec.TRIGGER_CALCULATIONS_JS)
        assert _squash(fragment) in source


def test_pec_aliases_are_the_golden_table():
    source = _golden(PEC_GOLDEN, "garage_conventionne.py")
    for rubrique_id, aliases in pec.RUBRIQUE_MATCH_ALIASES.items():
        for alias in aliases:
            assert f'"{alias}"' in source, f"alias {alias!r} is not in the golden table"


# --------------------------------------------------------------------- #
# Mode Normal behaviour
# --------------------------------------------------------------------- #


class FakeLocator:
    def __init__(self, page, selector, count=1, visible=True, checked=False):
        self._page = page
        self._selector = selector
        self._count = count
        self._visible = visible
        self._checked = checked

    @property
    def first(self):
        return self

    async def count(self):
        return self._count

    async def is_visible(self):
        return self._visible

    async def is_checked(self):
        return self._checked

    async def fill(self, value, timeout=None):
        self._page.calls.append(("fill", self._selector, value))

    async def select_option(self, value, timeout=None):
        self._page.calls.append(("select_option", self._selector, value))

    async def check(self, timeout=None):
        self._page.calls.append(("check", self._selector))

    async def click(self, timeout=None, force=None):
        self._page.calls.append(("click", self._selector))

    async def scroll_into_view_if_needed(self, timeout=None):
        return None

    async def evaluate(self, script, arg=None):
        self._page.calls.append(("locator_evaluate", self._selector, arg))
        return None


class FakePage:
    def __init__(self, counts=None, visible=True, evaluate_result=None):
        self.calls = []
        self._counts = counts or {}
        self._visible = visible
        self._evaluate_result = evaluate_result if evaluate_result is not None else "ok"

    def locator(self, selector):
        count = self._counts.get(selector, 1)
        return FakeLocator(self, selector, count=count, visible=self._visible)

    async def evaluate(self, script, arg=None):
        self.calls.append(("evaluate", script, arg))
        return self._evaluate_result

    async def wait_for_timeout(self, ms):
        self.calls.append(("wait", ms))


def test_the_unsuffixed_selectors_are_used_and_no_temp_id_appears():
    """The production path must not require #MontantHT_<tempId> or
    #normal_row_<tempId> -- those are mock inventions and appear nowhere
    in the golden commit."""
    page = FakePage()
    driver = normal.ModeNormalLiveDriver(page)
    _run(driver.fill_new_row("7", "100.00", "20.00"))

    selectors = [call[1] for call in page.calls if call[0] in ("fill", "locator_evaluate")]
    joined = " ".join(str(s) for s in selectors)
    assert "#MontantHT" in joined
    assert "_" not in joined.replace("name*=", "").replace("td:nth-child", "")


@pytest.mark.parametrize("script_or_selector", [
    normal.ID_RUBRIQUE_SELECTOR, normal.MONTANT_HT_SELECTOR, normal.TAXE_SELECTOR,
    normal.CHECKMARK_COLUMN_SELECTOR, normal.CHECKMARK_JS, normal.AJOUTER_SELECTOR,
])
def test_no_mock_only_identifier_survives_in_mode_normal(script_or_selector):
    for mock_only in ("normal_row_", "IdRubrique_", "MontantHT_", "Taxe_",
                      "sectionModeNormal", "tbodyModeNormal", "data-mock-only"):
        assert mock_only not in script_or_selector


def test_a_zero_tax_is_not_typed():
    """Golden guard: the tax field is left alone when the value is 0."""
    page = FakePage()
    driver = normal.ModeNormalLiveDriver(page)
    _run(driver.fill_new_row("7", "100.00", "0"))
    filled = [call[2] for call in page.calls if call[0] == "fill"]
    assert "100.00" in filled
    assert "0" not in filled


def test_ajouter_falls_back_to_the_datatable_api_when_absent():
    page = FakePage(counts={normal.AJOUTER_SELECTOR: 0})
    driver = normal.ModeNormalLiveDriver(page)
    _run(driver.click_ajouter())
    scripts = [call[1] for call in page.calls if call[0] == "evaluate"]
    assert normal.AJOUTER_DATATABLE_FALLBACK_JS in scripts


def test_ajouter_uses_the_golden_control_when_present():
    page = FakePage()
    driver = normal.ModeNormalLiveDriver(page)
    _run(driver.click_ajouter())
    assert ("click", normal.AJOUTER_SELECTOR) in page.calls


def test_both_checkmark_methods_run():
    """Golden order: the Playwright column click, then the JS equivalent
    unconditionally. A duplicate click on a saved row is harmless; a
    missed save is not."""
    page = FakePage()
    driver = normal.ModeNormalLiveDriver(page)
    _run(driver.click_row_checkmark())
    assert ("click", normal.CHECKMARK_COLUMN_SELECTOR) in page.calls
    assert any(call[0] == "evaluate" and call[1] == normal.CHECKMARK_JS for call in page.calls)


def test_the_row_save_does_not_require_a_network_response():
    """createRapportDefDet appears nowhere in the golden commits -- only
    in this repository's mock. The golden write WAS the DOM interaction,
    so requiring that response would fail a write that succeeded."""
    page = FakePage()
    driver = normal.ModeNormalLiveDriver(page)
    _run(driver.add_rubrique_row("7", "100.00", "20.00"))
    assert not hasattr(page, "expect_response_called")
    for script in (normal.CHECKMARK_JS, normal.FILL_INPUT_JS, normal.SELECT_OPTION_JS):
        assert "createRapportDefDet" not in script


def test_vehicle_repairable_is_checked_before_rows_are_added():
    page = FakePage()
    driver = normal.ModeNormalLiveDriver(page)
    _run(driver.add_rubrique_row("7", "100.00", "20.00"))
    checked_at = next(i for i, c in enumerate(page.calls) if c[0] == "check")
    ajouter_at = next(i for i, c in enumerate(page.calls)
                      if c[0] == "click" and c[1] == normal.AJOUTER_SELECTOR)
    assert checked_at < ajouter_at


def test_select_option_falls_back_to_playwright_when_the_script_mismatches():
    page = FakePage(evaluate_result="mismatch")
    driver = normal.ModeNormalLiveDriver(page)
    assert _run(driver.safe_select_option("#IdRubrique", "7")) is True
    assert any(call[0] == "select_option" for call in page.calls)


def test_an_empty_value_is_never_typed():
    page = FakePage()
    driver = normal.ModeNormalLiveDriver(page)
    assert _run(driver.safe_fill_input("#MontantHT", "")) is False
    assert _run(driver.safe_select_option("#IdRubrique", "  ")) is False
    assert page.calls == []


# --------------------------------------------------------------------- #
# PEC matching -- pure, and the heart of the workflow
# --------------------------------------------------------------------- #


def _rows(*labels):
    return [{"index": i, "rubrique_label": label} for i, label in enumerate(labels)]


def test_exact_label_match_wins_first():
    rows = _rows("MAIN D'OEUVRE PEINTURE", "FOURNITURES CARROSSERIE (ORIGINES)")
    row, method = pec.match_single_rubrique("12", "main d oeuvre peinture", rows, set())
    assert row["index"] == 0
    assert method.startswith("exact_label")


def test_a_known_alias_matches_when_the_label_differs():
    rows = _rows("FOURNITURES CARROSSERIE (ORIGINES)")
    row, method = pec.match_single_rubrique("1", "pieces origines", rows, set())
    assert row["index"] == 0
    assert method.startswith("known_alias")


def test_substring_matching_requires_the_golden_minimum_length():
    rows = _rows("MAIN D'OEUVRE CARROSSERIE")
    # Three characters must not match; the golden minimum is 4.
    row, _ = pec.match_single_rubrique("7", "mai", rows, set())
    assert row is None
    row, method = pec.match_single_rubrique("7", "main d oeuvre", rows, set())
    assert row is not None
    assert method.startswith("substring")


def test_used_indices_stop_two_rubriques_consuming_one_row():
    """Without this, two similar labels would silently overwrite each
    other in the same portal row."""
    rows = _rows("FOURNITURES CARROSSERIE (ORIGINES)")
    matches = []
    used = set()
    for rubrique_id, label in (("1", "pieces origines"), ("2", "pieces origines")):
        row, _ = pec.match_single_rubrique(rubrique_id, label, rows, used)
        if row is not None:
            used.add(row["index"])
            matches.append(row["index"])
    assert matches == [0]


def test_all_or_nothing_raises_before_any_mutation():
    rows = _rows("FOURNITURES CARROSSERIE (ORIGINES)")
    with pytest.raises(pec.UnmatchedRubrique) as raised:
        pec.match_all_rubriques(
            [("1", "pieces origines"), ("12", "main d oeuvre peinture")], rows
        )
    assert raised.value.unmatched == ("12",)
    assert "zero writes" in str(raised.value)


def test_a_complete_match_returns_every_planned_row():
    rows = _rows("FOURNITURES CARROSSERIE (ORIGINES)", "MAIN D'OEUVRE PEINTURE")
    matches = pec.match_all_rubriques(
        [("1", "pieces origines"), ("12", "main d oeuvre peinture")], rows
    )
    assert [m["target_index"] for m in matches] == [0, 1]
    assert {m["rubrique_id"] for m in matches} == {"1", "12"}


def test_matching_is_accent_and_case_insensitive():
    rows = _rows("Main d'Œuvre Peinture")
    row, _ = pec.match_single_rubrique("12", "MAIN D OEUVRE PEINTURE", rows, set())
    assert row is not None


# --------------------------------------------------------------------- #
# PEC driver behaviour
# --------------------------------------------------------------------- #


class FakeResponse:
    def __init__(self, status=200):
        self.status = status


class FakeResponseInfo:
    def __init__(self, response):
        self._response = response

    @property
    async def value(self):
        return self._response


class FakeExpectResponse:
    def __init__(self, page, predicate, timeout, response):
        self._page = page
        self._predicate = predicate
        self._response = response

    async def __aenter__(self):
        self._page.predicates.append(self._predicate)
        return FakeResponseInfo(self._response)

    async def __aexit__(self, *exc):
        return False


class FakePecPage(FakePage):
    def __init__(self, response=None, click_ok=True, **kwargs):
        super().__init__(**kwargs)
        self.predicates = []
        self._response = response
        self._click_ok = click_ok

    def expect_response(self, predicate, timeout=None):
        if self._response is None:
            raise TimeoutError("no update response")
        return FakeExpectResponse(self, predicate, timeout, self._response)

    async def evaluate(self, script, arg=None):
        self.calls.append(("evaluate", script, arg))
        if script in (pec.CLICK_SAVE_JS,):
            return {"ok": self._click_ok, "error": None if self._click_ok else "no button"}
        if script == pec.RELOCATE_ROW_JS:
            return 3
        return {}


def test_the_update_response_is_matched_by_substring_only():
    """The only network fact the golden code established. It never
    asserted the full path, the method or a JSON body, so none of those
    may be required."""
    page = FakePecPage(response=FakeResponse(200))
    driver = pec.PecLiveDriver(page)
    observed = _run(driver.click_save_and_await_update(0))

    assert observed["response_seen"] is True
    assert observed["status"] == 200
    predicate = page.predicates[0]

    class _R:
        url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestiongarage/updateDevisDet"

    assert predicate(_R()) is True
    # A different shape of the same endpoint still matches.
    class _R2:
        url = "https://host/x/updateDevisDet?nocache=1"

    assert predicate(_R2()) is True


def test_a_missing_update_response_still_clicks_and_reports():
    """Golden fallback: when the response never arrives, the checkmark is
    clicked directly and the read-back decides."""
    page = FakePecPage(response=None)
    driver = pec.PecLiveDriver(page)
    observed = _run(driver.click_save_and_await_update(0))
    assert observed["clicked"] is True
    assert observed["response_seen"] is False
    assert any(call[1] == pec.CLICK_SAVE_FALLBACK_JS for call in page.calls
               if call[0] == "evaluate")


def test_the_row_is_relocated_by_label_not_by_a_stored_index():
    page = FakePecPage()
    driver = pec.PecLiveDriver(page)
    assert _run(driver.relocate_row("MAIN D'OEUVRE PEINTURE")) == 3
    assert any(call[1] == pec.RELOCATE_ROW_JS for call in page.calls if call[0] == "evaluate")


@pytest.mark.parametrize("script", [
    pec.ENUMERATE_ROWS_JS, pec.RELOCATE_ROW_JS, pec.CLICK_PENCIL_JS,
    pec.FILL_ROW_JS, pec.CLICK_SAVE_JS, pec.TRIGGER_CALCULATIONS_JS,
    pec.READ_FINANCIAL_SUMMARY_JS,
])
def test_no_mock_only_identifier_survives_in_pec(script):
    for mock_only in ("row_val_", "MontantHTValide_", "TaxeValide_",
                      "data-mock-only", "_mock/pec"):
        assert mock_only not in script


def test_no_final_action_appears_in_either_driver():
    """Mechanics were ported; final actions were not."""
    for module in (normal, pec):
        source = _code_only(module)
        for forbidden in (
            "DEVISDET_Btn", "garageModifierValDevis", "validerDevis",
            "expertEnregistrerMission", "enregistrerMission",
            "cloturerMission", "expertCloturerMission", "cloturerTraitement",
            "ajouterDocument", "deleteDocument", "deleteDevisDet",
        ):
            assert forbidden not in source, f"{forbidden} leaked into {module.__name__}"
    # #Enregistrer as a control id must not appear either.
    assert "#Enregistrer" not in _code_only(normal)
    assert "#Enregistrer" not in _code_only(pec)


def test_the_drivers_hold_no_authorization_state():
    """Golden commits define portal mechanics, never authorization. A
    driver that could decide it was allowed to write would be a way around
    the identity, workflow and lease gates."""
    for module in (normal, pec):
        source = _code_only(module)
        for concept in ("lease", "account_id", "Principal", "expected_identity",
                        "JobAuthorizationError", "is_mcma"):
            assert concept not in source, f"{concept} should live in the writer, not {module.__name__}"
