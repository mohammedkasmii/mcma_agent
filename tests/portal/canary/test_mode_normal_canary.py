"""The supervised Mode Normal golden canary, end to end against fakes.

No real browser and no network: a fake Playwright-shaped browser/context/
page whose every request (search POST, mission document, the portal's own
row-save XHR) is routed through the REAL canary route handler, so the
network policy is exercised in-loop. The golden DOM primitives themselves
are covered by tests/portal/writer/test_golden_driver_parity.py; here a
fake driver records the order in which the canary calls them.

All dossier data is synthetic (the redacted 8,000 MAD shape)."""

import asyncio
import inspect
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest

from mcma.domain.enums import FormFieldSelector, RepairWorkflow
from mcma.domain.rubriques import RUBRIQUE_CATALOG
from mcma.domain.values import FormFieldIntent
from mcma.mapping.wexia import parse_wexia
from mcma.planning.plan import build_mission_normal_plan
from mcma.portal import mode_normal_canary as canary_module
from mcma.portal.browser import launch_browser
from mcma.portal.capabilities import _FETCH_JSON_JS, SearchIdentifiers
from mcma.portal.identity import _OBSERVE_IDENTITY_JS, ExpectedIdentity
from mcma.portal.mission import _DETECT_WORKFLOW_JS
from mcma.portal.mode_normal_canary import (
    EDITING_ROW_COUNT_JS,
    FIELD_TAG_JS,
    PROBE_CALCULATIONS_JS,
    READ_EDITING_ROW_JS,
    READ_FIELD_JS,
    READ_RENDERED_ROWS_JS,
    READ_TOTALS_JS,
    classify_table,
    parse_portal_amount,
    run_mode_normal_golden_canary,
)
from mcma.portal.mode_normal_live import (
    ID_RUBRIQUE_SELECTOR,
    MONTANT_HT_SELECTOR,
    TAXE_SELECTOR,
    ModeNormalLiveDriver,
)
from mcma.portal.writer import PortalRowIntent, WriterPlanData, require_mcma_writer_account

HOST = "sinauto.mamda-mcma.ma"
ORIGIN = f"https://{HOST}"
SAVE_PATH = "/SinAuto_MCMA/expertise/gestionExpert/saveRubriqueRow"
PLATE = "11111-A-1"
SINISTRE = "900001"


# --------------------------------------------------------------------- #
# Synthetic plan (redacted 8,000 MAD shape)
# --------------------------------------------------------------------- #


def _payload():
    lines = [
        {"item_type": "part", "item_name": "Porte avant gauche", "part_type": "recuperation",
         "is_original": False, "subtotal": "5000.00"},
        {"item_type": "part", "item_name": "Apprêt", "part_type": "recuperation",
         "is_original": False, "subtotal": "840.00"},
        {"item_type": "labor", "item_name": "Main d'oeuvre carrosserie", "operation_type": "carrosserie",
         "subtotal": "1200.00"},
        {"item_type": "labor", "item_name": "Main d'oeuvre peinture", "operation_type": "peinture",
         "subtotal": "600.00"},
    ]
    return {
        "vehicule": {"license_plate": PLATE},
        "dossier": {"mission_type": "normal", "incident_description": "MODE NORMAL",
                    "id_sinistre": SINISTRE, "is_reform": False},
        "chiffrages": [{
            "status": "approved", "scenario_type": "repair", "lignes_pieces": lines,
            "total_parts_cost": "5840.00", "total_labor_cost": "1800.00",
            "total_cost": "7640.00", "tax_amount": "360.00", "final_cost": "8000.00",
        }],
    }


def _plan():
    plan = build_mission_normal_plan(parse_wexia(_payload()))
    assert plan.is_writeable and [s.rubrique_id.value for s in plan.steps] == ["3", "7", "12", "16"]
    return plan


def _writer_plan(plan=None, *, form_fields=(), workflow=RepairWorkflow.MODE_NORMAL, steps=None):
    plan = plan or _plan()
    return WriterPlanData(
        repair_workflow=workflow,
        row_intents=tuple(
            PortalRowIntent(rubrique_id=s.rubrique_id, ht=s.ht, tva=s.tva, vetuste=s.vetuste)
            for s in (steps if steps is not None else plan.steps)
        ),
        form_field_intents=tuple(form_fields),
    )


def _expected_identity(plan=None):
    plan = plan or _plan()
    e = plan.expected_identity
    return ExpectedIdentity(registration=e.registration, insurer_reference=e.insurer_reference,
                            id_sinistre=e.id_sinistre)


# --------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------- #


def _render(amount: Decimal) -> str:
    whole, frac = f"{amount:.2f}".split(".")
    groups = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    return " ".join(groups) + "," + frac


class FakeRequest:
    def __init__(self, url, method, resource_type, *, navigation, frame, content_type=None, body=None):
        self.url, self.method, self.resource_type = url, method, resource_type
        self._navigation, self.frame, self.post_data = navigation, frame, body
        self.headers = {"content-type": content_type} if content_type else {}

    def is_navigation_request(self):
        return self._navigation


class FakeRoute:
    def __init__(self, request):
        self.request = request
        self.outcome = None

    async def continue_(self):
        self.outcome = "continue"

    async def abort(self, code=None):
        self.outcome = "abort"


class FakePage:
    def __init__(self, context):
        self.context = context
        self.main_frame = object()
        self.calls: list = []
        self.goto_urls: list = []
        self.handlers: dict = {}
        # portal state
        self.identity = {"registration": PLATE, "id_sinistre": SINISTRE}
        self.workflow = {"normal": True, "pec": False}
        self.candidates = [{"IdMission": 4242}]
        self.rows: list = []          # rendered saved rows
        self.saved: list = []         # (rubrique, ht, tva) decimals
        self.editing = None
        self.fields: dict = {}
        self.missing_calc: list = []
        self.totals_override = None
        # fault injection
        self.render_override: dict = {}
        self.drop_save = False
        self.save_requests = 1
        self.calc_request = False
        self.ajouter_request = False
        self.on_checkmark = None
        self.search_page_xhr = False

    # -- network simulation via the real installed handler --
    async def fire(self, url, method="GET", rtype="xhr", *, navigation=False, frame=None, ctype=None, body=None):
        request = FakeRequest(url, method, rtype, navigation=navigation,
                              frame=self.main_frame if frame is None else frame, content_type=ctype, body=body)
        route = FakeRoute(request)
        await self.context.route_handler(route)
        return route.outcome == "continue"

    async def goto(self, url):
        self.goto_urls.append(url)
        if not await self.fire(url, "GET", "document", navigation=True):
            raise RuntimeError("net::ERR_BLOCKED_BY_CLIENT")
        if url.endswith("/frontexpert") and self.search_page_xhr:
            await self.fire(ORIGIN + "/SinAuto_MCMA/expertise/notification/count", "POST", "xhr",
                            ctype="application/x-www-form-urlencoded", body="a=1")

    async def wait_for_timeout(self, ms):
        await asyncio.sleep(0)

    def on(self, event, cb):
        self.handlers.setdefault(event, []).append(cb)

    def employee_closes(self):
        for cb in self.handlers.get("close", []):
            cb()
        self.context.fire_close()

    async def evaluate(self, script, arg=None):
        if script is _FETCH_JSON_JS:
            url, payload = arg
            body = "&".join(f"{k}={v}" for k, v in payload.items())
            if not await self.fire(url, "POST", "fetch", ctype="application/x-www-form-urlencoded", body=body):
                raise RuntimeError("fetch blocked")
            return {"data": list(self.candidates)}
        if script is _OBSERVE_IDENTITY_JS:
            return dict(self.identity)
        if script is _DETECT_WORKFLOW_JS:
            return dict(self.workflow)
        if script is READ_RENDERED_ROWS_JS:
            return [dict(r) for r in self.rows]
        if script is EDITING_ROW_COUNT_JS:
            n = 1 if self.editing is not None else 0
            return {"ht": n, "rub": n}
        if script is READ_EDITING_ROW_JS:
            e = self.editing or {}
            return {"rubrique": e.get("rubrique"), "ht": e.get("ht"), "taxe": e.get("taxe")}
        if script is PROBE_CALCULATIONS_JS:
            return list(self.missing_calc)
        if script is READ_TOTALS_JS:
            if self.totals_override is not None:
                return dict(self.totals_override)
            tva = sum((t for _, _, t in self.saved), Decimal("0"))
            ht = sum((h for _, h, _ in self.saved), Decimal("0"))
            return {"total_tva": _render(tva), "total_ttc": _render(ht + tva)}
        if script is FIELD_TAG_JS:
            return "input"
        if script is READ_FIELD_JS:
            return self.fields.get(arg)
        if isinstance(script, str) and script.startswith("() => document.querySelectorAll('#"):
            return 1
        raise AssertionError(f"unexpected script: {str(script)[:60]}")

    def add_saved_row(self, rubrique, ht, tva, *, label=True):
        self.saved.append((rubrique, Decimal(ht), Decimal(tva)))
        cell = RUBRIQUE_CATALOG[rubrique] if label else rubrique
        self.rows.append({"index": len(self.rows), "rubrique_cell": cell,
                          "MontantHT": _render(Decimal(ht)), "Taxe": _render(Decimal(tva))})


class FakeDriver:
    def __init__(self, page):
        self.page = page

    async def ensure_vehicle_repairable(self):
        self.page.calls.append("veh")
        return True

    async def click_ajouter(self):
        self.page.calls.append("ajouter")
        if self.page.ajouter_request:
            await self.page.fire(ORIGIN + "/SinAuto_MCMA/expertise/gestionExpert/addRow", "POST",
                                 ctype="application/x-www-form-urlencoded", body="x=1")
        self.page.editing = {"rubrique": None, "ht": None, "taxe": None}

    async def safe_select_option(self, selector, value):
        self.page.calls.append(("select", selector, value))
        if selector == ID_RUBRIQUE_SELECTOR:
            self.page.editing["rubrique"] = value
        else:
            self.page.fields[selector] = value
        return True

    async def safe_fill_input(self, selector, value):
        self.page.calls.append(("fill", selector, value))
        if selector == MONTANT_HT_SELECTOR:
            self.page.editing["ht"] = value
        elif selector == TAXE_SELECTOR:
            self.page.editing["taxe"] = value
        else:
            self.page.fields[selector] = value
        return True

    async def click_row_checkmark(self):
        page = self.page
        page.calls.append("checkmark")
        if page.on_checkmark is not None:
            await page.on_checkmark(page)
        ok = True
        for _ in range(page.save_requests):
            ok = await page.fire(ORIGIN + SAVE_PATH, "POST", "xhr", ctype="application/x-www-form-urlencoded",
                                 body="IdRubrique=1&MontantHT=1&Taxe=0") and ok
        if ok and not page.drop_save and page.editing is not None:
            e = page.editing
            rubrique = e["rubrique"]
            ht = Decimal(e["ht"])
            tva = Decimal(e["taxe"]) if e["taxe"] else Decimal("0")
            page.saved.append((rubrique, ht, tva))
            rendered_ht = page.render_override.get(rubrique, _render(ht))
            page.rows.append({"index": len(page.rows), "rubrique_cell": RUBRIQUE_CATALOG[rubrique],
                              "MontantHT": rendered_ht, "Taxe": _render(tva)})
            page.editing = None

    async def trigger_native_calculations(self):
        self.page.calls.append("calc")
        if self.page.calc_request:
            await self.page.fire(ORIGIN + "/SinAuto_MCMA/expertise/gestionExpert/calculer", "POST",
                                 ctype="application/x-www-form-urlencoded", body="a=1")
        return {}


class FakeContext:
    def __init__(self, options):
        self.options = options
        self.route_handler = None
        self.ws_handler = None
        self.handlers: dict = {}
        self.closed = False
        self.page = FakePage(self)

    async def new_page(self):
        return self.page

    async def route(self, pattern, handler):
        self.route_handler = handler

    async def route_web_socket(self, pattern, handler):
        self.ws_handler = handler

    def on(self, event, cb):
        self.handlers.setdefault(event, []).append(cb)

    def fire_close(self):
        for cb in self.handlers.get("close", []):
            cb()

    async def close(self):
        if not self.closed:
            self.closed = True
            self.fire_close()


class FakeBrowser:
    def __init__(self, configure):
        self.contexts: list = []
        self.configure = configure

    async def new_context(self, **options):
        context = FakeContext(options)
        self.configure(context.page)
        self.contexts.append(context)
        return context


class Harness:
    def __init__(self, configure=lambda page: None):
        self.launches: list = []
        self.browser = FakeBrowser(configure)

    @asynccontextmanager
    async def launcher(self, *, headless):
        self.launches.append(headless)
        yield self.browser

    @property
    def page(self) -> FakePage:
        return self.browser.contexts[0].page

    @property
    def context(self) -> FakeContext:
        return self.browser.contexts[0]


class FakePermit:
    def __init__(self, account_id="acct-mcma-oujda"):
        self.account_id = account_id
        self.valid = True
        self.checks = 0

    async def assert_valid(self):
        self.checks += 1
        if not self.valid:
            raise RuntimeError("permit invalid")


def _run(harness, *, plan=None, writer_plan=None, permit=None, account="acct-mcma-oujda",
         on_ready=None, evidence=None, host=HOST, close_on_ready=True):
    plan = plan or _plan()
    writer_plan = writer_plan or _writer_plan(plan)
    permit = permit or FakePermit(account)
    ready_calls: list = []

    async def _on_ready():
        ready_calls.append(True)
        if on_ready is not None:
            await on_ready()
        if close_on_ready:
            harness.page.employee_closes()

    collected = evidence if evidence is not None else []

    async def go():
        return await run_mode_normal_golden_canary(
            {"cookies": [], "origins": []},
            expected_identity=_expected_identity(plan), writer_plan=writer_plan,
            identifiers=SearchIdentifiers(matricule=PLATE),
            writer_account=require_mcma_writer_account(account, entity="MCMA", active=True),
            permit=permit, on_ready_for_review=_on_ready, on_evidence=collected.append,
            host=host, launcher=harness.launcher, driver_factory=FakeDriver,
            abort_hold_seconds=0.01, readback_attempts=2, readback_interval_ms=0,
        )

    outcome = asyncio.run(go())
    return outcome, ready_calls, collected


def _row_mutations(page):
    return [c for c in page.calls if c != "calc"]


# --------------------------------------------------------------------- #
# Success: the redacted 8,000 MAD scenario
# --------------------------------------------------------------------- #


def test_redacted_8000_scenario_reaches_ready_for_human_review():
    harness = Harness()
    evidence: list = []
    outcome, ready, _ = _run(harness, evidence=evidence)

    assert outcome == "READY_FOR_HUMAN_REVIEW"
    assert ready == [True]
    assert harness.launches == [False]  # visible browser
    assert [(r, str(h), str(t)) for r, h, t in harness.page.saved] == [
        ("3", "5000.00", "0"), ("7", "1200.00", "240.00"), ("12", "600.00", "120.00"), ("16", "840.00", "0"),
    ]
    assert harness.page.goto_urls[0] == f"{ORIGIN}/SinAuto_MCMA/expertise/frontexpert"
    assert harness.page.goto_urls[1].startswith(f"{ORIGIN}/SinAuto_MCMA/expertise/gestionExpert/getSinistre/")
    options = harness.context.options
    assert options["accept_downloads"] is False and options["service_workers"] == "block"
    assert "proxy" not in options and "ignore_https_errors" not in options
    assert evidence[-1]["outcome"] == "READY_FOR_HUMAN_REVIEW" and evidence[-1]["rows_written"] == 4
    window = [r for r in evidence[-1]["records"] if r["reason"] == "ROW_WINDOW"]
    assert [r["row_index"] for r in window] == [0, 1, 2, 3]
    assert all(r["decision"] == "ALLOW" and r["path"] == SAVE_PATH for r in window)


def test_golden_row_sequence_is_used_exactly_and_zero_tax_is_not_typed():
    harness = Harness()
    _run(harness)
    expected = []
    for rubrique, ht, tva in (("3", "5000.00", None), ("7", "1200.00", "240.00"),
                              ("12", "600.00", "120.00"), ("16", "840.00", None)):
        expected += ["veh", "ajouter", ("select", ID_RUBRIQUE_SELECTOR, rubrique), ("fill", MONTANT_HT_SELECTOR, ht)]
        if tva is not None:
            expected.append(("fill", TAXE_SELECTOR, tva))
        expected.append("checkmark")
    assert _row_mutations(harness.page) == expected
    assert harness.page.calls[-1] == "calc"


def test_existing_exact_planned_row_is_not_rewritten():
    def configure(page):
        page.add_saved_row("3", "5000.00", "0")
    harness = Harness(configure)
    outcome, _, _ = _run(harness)
    assert outcome == "READY_FOR_HUMAN_REVIEW"
    assert ("select", ID_RUBRIQUE_SELECTOR, "3") not in harness.page.calls
    assert harness.page.calls.count("checkmark") == 3


def test_approved_header_fields_are_filled_and_read_back():
    plan = _plan()
    field = FormFieldIntent(FormFieldSelector.KILOMETRAGE, "85000",
                            (RepairWorkflow.MODE_NORMAL, RepairWorkflow.GARAGE_CONVENTIONNE))
    harness = Harness()
    outcome, _, _ = _run(harness, plan=plan, writer_plan=_writer_plan(plan, form_fields=(field,)))
    assert outcome == "READY_FOR_HUMAN_REVIEW"
    assert ("fill", "#Kilometrage", "85000") in harness.page.calls


# --------------------------------------------------------------------- #
# Fail closed after mutation -- never READY
# --------------------------------------------------------------------- #


def _aborted(harness, **kw):
    outcome, ready, evidence = _run(harness, close_on_ready=True, **kw)
    assert outcome == "WRITE_ABORTED"
    assert ready == []
    assert evidence[-1]["outcome"] == "WRITE_ABORTED"
    return evidence[-1]


def test_readback_amount_mismatch_aborts_and_stops_writing():
    harness = Harness(lambda page: page.render_override.update({"7": "1 300,00"}))
    ev = _aborted(harness)
    assert ev["reason"] == "READBACK_EXISTING_ROW_MISMATCH"
    assert harness.page.calls.count("checkmark") == 2  # rows 3 and 7 only
    assert "calc" not in harness.page.calls


def test_row_that_never_persists_aborts():
    harness = Harness(lambda page: setattr(page, "drop_save", True))
    assert _aborted(harness)["reason"] == "READBACK_ROW_NOT_PERSISTED"


@pytest.mark.parametrize("rows,reason", [
    ([("3", "5000.00", "0"), ("3", "5000.00", "0")], "DUPLICATE_RUBRIQUE_ROW"),
    ([("1", "100.00", "20.00")], "UNEXPECTED_EXISTING_ROW"),
    ([("7", "999.00", "240.00")], "EXISTING_ROW_MISMATCH"),
])
def test_unexpected_or_conflicting_existing_rows_abort_before_any_mutation(rows, reason):
    def configure(page):
        for r in rows:
            page.add_saved_row(*r)
    harness = Harness(configure)
    assert _aborted(harness)["reason"] == reason
    assert harness.page.calls == []


def test_row_save_window_request_cap_breach_aborts():
    harness = Harness(lambda page: setattr(page, "save_requests", 7))
    ev = _aborted(harness)
    assert ev["reason"] == "NETWORK_VIOLATION"
    assert any(r["reason"] == "WINDOW_CAP" for r in ev["records"])


def test_request_outside_the_row_window_aborts():
    harness = Harness(lambda page: setattr(page, "ajouter_request", True))
    ev = _aborted(harness)
    assert ev["reason"] == "NETWORK_VIOLATION"
    assert any(r["reason"] == "XHR_OUTSIDE_WINDOW" for r in ev["records"])
    assert "checkmark" not in harness.page.calls


def test_native_calculation_gets_no_network_window():
    harness = Harness(lambda page: setattr(page, "calc_request", True))
    ev = _aborted(harness)
    assert ev["reason"] == "NETWORK_VIOLATION"
    assert ev["rows_written"] == 4


def test_missing_native_calculation_function_aborts_without_triggering():
    harness = Harness(lambda page: setattr(page, "missing_calc", ["CalculerMontantTTC"]))
    assert _aborted(harness)["reason"] == "NATIVE_CALCULATION_MISSING"
    assert "calc" not in harness.page.calls


@pytest.mark.parametrize("totals,reason", [
    ({"total_tva": "400,00", "total_ttc": "8 000,00"}, "SUMMARY_TVA_MISMATCH"),
    ({"total_tva": "360,00", "total_ttc": "8 040,00"}, "SUMMARY_TTC_MISMATCH"),
    ({"total_tva": None, "total_ttc": "8 000,00"}, "SUMMARY_TVA_MISMATCH"),
])
def test_summary_that_does_not_reconcile_aborts(totals, reason):
    harness = Harness(lambda page: setattr(page, "totals_override", totals))
    assert _aborted(harness)["reason"] == reason


def test_browser_closed_mid_run_aborts():
    async def close_after_first(page):
        if page.calls.count("checkmark") == 2:
            page.employee_closes()
    harness = Harness(lambda page: setattr(page, "on_checkmark", close_after_first))
    assert _aborted(harness)["reason"] == "BROWSER_CLOSED"
    assert harness.page.calls.count("checkmark") == 2


def test_lease_loss_mid_run_aborts_before_the_next_mutation():
    permit = FakePermit()

    async def invalidate(page):
        if page.calls.count("checkmark") == 1:
            permit.valid = False
    harness = Harness(lambda page: setattr(page, "on_checkmark", invalidate))
    assert _aborted(harness, permit=permit)["reason"] == "LEASE_INVALID"
    assert harness.page.calls.count("checkmark") == 1


def test_cancellation_fails_closed_and_closes_the_browser():
    harness_box: dict = {}

    async def scenario():
        gate = asyncio.Event()

        async def block(page):
            gate.set()
            await asyncio.sleep(3600)

        harness = Harness(lambda page: setattr(page, "on_checkmark", block))
        harness_box["h"] = harness
        evidence: list = []
        plan = _plan()
        task = asyncio.ensure_future(run_mode_normal_golden_canary(
            {}, expected_identity=_expected_identity(plan), writer_plan=_writer_plan(plan),
            identifiers=SearchIdentifiers(matricule=PLATE),
            writer_account=require_mcma_writer_account("acct-mcma-oujda", entity="MCMA", active=True),
            permit=FakePermit(), on_ready_for_review=lambda: asyncio.sleep(0), on_evidence=evidence.append,
            launcher=harness.launcher, driver_factory=FakeDriver, abort_hold_seconds=0.01,
        ))
        await gate.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return evidence

    evidence = asyncio.run(scenario())
    assert evidence[-1]["reason"] == "CANCELLED" and evidence[-1]["outcome"] == "WRITE_ABORTED"
    assert harness_box["h"].context.closed


# --------------------------------------------------------------------- #
# Refused before any browser mutation
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("mutate,expected", [
    (lambda page: page.identity.update({"registration": "22222-B-2"}), "IDENTITY_FAILED"),
    (lambda page: page.identity.update({"id_sinistre": "900002"}), "IDENTITY_FAILED"),
    (lambda page: page.workflow.update({"normal": False, "pec": True}), "IDENTITY_FAILED"),
    (lambda page: page.candidates.append({"IdMission": 4243}), "IDENTITY_FAILED"),
    (lambda page: page.candidates.clear(), "IDENTITY_FAILED"),
    (lambda page: setattr(page, "search_page_xhr", True), "WRITE_ABORTED"),
])
def test_identity_workflow_and_search_failures_never_mutate(mutate, expected):
    harness = Harness(mutate)
    outcome, ready, _ = _run(harness)
    assert outcome == expected
    assert ready == []
    assert harness.page.calls == []


@pytest.mark.parametrize("case", ["pec", "unprofiled", "mamda", "permit_mismatch", "host", "lease"])
def test_preconditions_refuse_before_any_browser_is_launched(case):
    plan = _plan()
    kwargs: dict = {}
    if case == "pec":
        kwargs["writer_plan"] = _writer_plan(plan, workflow=RepairWorkflow.GARAGE_CONVENTIONNE)
    elif case == "unprofiled":
        from mcma.domain.values import RubriqueId
        first = plan.steps[0]
        kwargs["writer_plan"] = WriterPlanData(
            repair_workflow=RepairWorkflow.MODE_NORMAL,
            row_intents=(PortalRowIntent(RubriqueId("22"), first.ht, first.tva, first.vetuste),),
        )
    elif case == "mamda":
        kwargs["account"] = "acct-mamda-oujda"
    elif case == "permit_mismatch":
        kwargs["permit"] = FakePermit("acct-mcma-nador")
    elif case == "host":
        kwargs["host"] = "127.0.0.1:8080"
    elif case == "lease":
        permit = FakePermit()
        permit.valid = False
        kwargs["permit"] = permit
    harness = Harness()
    outcome, ready, evidence = _run(harness, plan=plan, **kwargs)
    assert outcome == "WRITE_ABORTED"
    assert ready == []
    assert harness.launches == []
    assert evidence[-1]["reason"].startswith("PRECONDITION_")


# --------------------------------------------------------------------- #
# Structural guarantees
# --------------------------------------------------------------------- #


def test_production_defaults_are_the_golden_driver_and_a_visible_browser():
    params = inspect.signature(run_mode_normal_golden_canary).parameters
    assert params["driver_factory"].default is ModeNormalLiveDriver
    assert params["launcher"].default is launch_browser
    assert params["host"].default == HOST


def _executable_strings(module) -> list:
    """Every string constant in the module EXCEPT docstrings -- i.e. every
    script, selector and literal the code can actually use."""
    import ast

    tree = ast.parse(inspect.getsource(module))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
    ]


def test_canary_code_has_no_final_action_charge_write_or_own_request():
    import mcma.portal.canary_network as network_module

    for module in (canary_module, network_module):
        for text in _executable_strings(module):
            for forbidden in ("fetch(", "XMLHttpRequest", "$.ajax", "MontantChargeMutuelle",
                              "MontantChargeSocietaire", "ignore_https_errors", "Valider", "Enregistrer",
                              "Cloture", "Clôture", "ajouterDocument", ".submit("):
                assert forbidden not in text, (module.__name__, forbidden)
    # The scan really does see the scripts it is meant to police.
    assert any("CalculerMontantTTC" in t for t in _executable_strings(canary_module))


def test_amount_parser_is_exact_and_fails_closed_on_ambiguity():
    assert parse_portal_amount("5 000,00") == Decimal("5000.00")
    assert parse_portal_amount("5.000,00") == Decimal("5000.00")
    assert parse_portal_amount("5,000.00") == Decimal("5000.00")
    assert parse_portal_amount("240") == Decimal("240")
    assert parse_portal_amount("240,00 DH") == Decimal("240.00")
    for ambiguous in ("5.000", "5,000", "", None, "abc", "1.2.3", "-5", "5000.001"):
        assert parse_portal_amount(ambiguous) is None


def test_table_classification_matches_ids_and_catalog_labels_only():
    plan = _writer_plan()
    rows = [
        {"rubrique_cell": "3", "MontantHT": "5000.00", "Taxe": "0.00"},
        {"rubrique_cell": "MAIN D'OEUVRE CARROSSERIE", "MontantHT": "1 200,00", "Taxe": "240,00"},
    ]
    assert set(classify_table(rows, plan)) == {"3", "7"}
    with pytest.raises(canary_module.CanaryAbort):
        classify_table([{"rubrique_cell": "carrosserie", "MontantHT": "1", "Taxe": "0"}], plan)
