"""The live-write readiness report, as assertions rather than prose.

docs/recovery/LIVE_WRITE_EVIDENCE_MATRIX.md records what is actually known
about writing to the real portal. This file makes the load-bearing parts
of it fail if they stop being true -- in particular the two readiness
flags, which must not drift to true because someone edited a document.

Nothing here enables a live write.
"""

import pytest

MODE_NORMAL_LIVE_WRITE_READY = False
GARAGE_CONVENTIONNE_LIVE_WRITE_READY = False


def _baseline(path):
    """Reads a file from the recovered baseline commit."""
    import subprocess

    result = subprocess.run(
        ["git", "show", f"0290fe9df24c9e2f2b054ee4f8b14b8267f07b12:{path}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip("the baseline commit is not present in this clone")
    return result.stdout


# --------------------------------------------------------------------- #
# Readiness
# --------------------------------------------------------------------- #


def test_neither_workflow_is_ready_for_live_writing():
    """The expected and correct outcome of the C.2 audit. Flipping either
    of these requires the missing contract evidence, not an edit."""
    assert MODE_NORMAL_LIVE_WRITE_READY is False
    assert GARAGE_CONVENTIONNE_LIVE_WRITE_READY is False


def test_the_writer_still_refuses_any_non_loopback_host():
    from mcma.portal.writer import _require_loopback_host

    for host in ("sinauto.mamda-mcma.ma", "example.com", "10.0.0.5:8080"):
        with pytest.raises(ValueError):
            _require_loopback_host(host)
    _require_loopback_host("127.0.0.1:8080")      # still permitted


def test_no_live_write_contract_exists():
    """The audit must not have quietly produced one."""
    from mcma.portal import sinauto_contracts

    assert not hasattr(sinauto_contracts, "write_contracts")
    assert not hasattr(sinauto_contracts, "row_write_contracts")

    from mcma.portal.sinauto_contracts import DEFAULT_SINAUTO_HOST, auth_contracts, notification_contracts

    every = auth_contracts() + notification_contracts(DEFAULT_SINAUTO_HOST, ["X"])
    assert {c.capability for c in every} <= {"auth", "read"}


def test_pilot_contracts_remain_mock_only():
    from mcma.portal.pilot_contracts import pilot_allowed_host

    with pytest.raises(ValueError):
        pilot_allowed_host("sinauto.mamda-mcma.ma")


# --------------------------------------------------------------------- #
# The headline finding
# --------------------------------------------------------------------- #


def test_mode_normal_row_persistence_has_no_recovered_evidence():
    """createRapportDefDet -- the endpoint the current writer awaits to
    persist a Mode Normal row -- appears NOWHERE in the baseline. The
    baseline clicked the checkmark and re-read the DOM; it never observed
    a network request for that operation. The whole contract is therefore
    MOCK_INFERRED, which is the largest single blocker to live Mode Normal
    writing."""
    for path in (
        "browser/mode_normal.py",
        "browser/mode_conventionne.py",
        "browser/form_filler.py",
        "browser/dom_helpers.py",
        "browser/safety_interceptor.py",
    ):
        assert "createRapportDefDet" not in _baseline(path), (
            f"{path} mentions createRapportDefDet -- if this now fails, real "
            "evidence has appeared and the matrix must be re-classified"
        )


def test_pec_row_persistence_has_substring_network_evidence_only():
    """updateDevisDet is the strongest write evidence that exists, and it
    is still only "a response whose URL contained this substring". Method,
    path, content type and body keys remain MOCK_INFERRED."""
    source = _baseline("browser/mode_conventionne.py")
    assert "expect_response" in source
    assert '"updateDevisDet" in r.url' in source
    # Matched on the URL substring alone -- never on the method.
    assert "r.request.method" not in source.split("expect_response")[1][:400]


def test_the_native_calculation_calls_are_defensive_not_evidence():
    """Every calculation function is called under typeof … === 'function'
    with the failure swallowed. That is evidence the author hoped they
    existed, not that they do."""
    source = _baseline("browser/dom_helpers.py")
    for name in ("CalculerMntArrete", "CalculerMontantDommage", "DevisCalculerMontantCharge"):
        assert f"typeof {name} === 'function'" in source


def test_the_prohibited_charge_split_overwrite_is_not_restored():
    """The baseline wrote #MontantChargeMutuelle directly. Those selectors
    are READ evidence only; BUSINESS_RULES.md B.3 forbids writing them."""
    from mcma.portal import writer

    source = writer.__file__ and open(writer.__file__, encoding="utf-8").read()
    for forbidden in ("MontantChargeMutuelle", "MontantChargeSocietaire"):
        # They may be READ back, but never filled.
        assert f'fill("#{forbidden}"' not in source
        assert f"fill('#{forbidden}'" not in source


# --------------------------------------------------------------------- #
# Final actions stay blocked at every evidence level
# --------------------------------------------------------------------- #


def test_every_final_action_remains_permanently_blocked():
    from mcma.portal.final_endpoints import PERMANENTLY_BLOCKED_ENDPOINTS, is_permanently_blocked

    for name in (
        "garageModifierValDevis", "validerDevis", "deleteDevisDet",
        "expertCloturerMission", "cloturerMission", "enregistrerMission",
        "expertEnregistrerMission", "ajouterDocument", "deleteDocument",
        "cloturerTraitement",
    ):
        assert name in PERMANENTLY_BLOCKED_ENDPOINTS
        assert is_permanently_blocked(f"/SinAuto_MCMA/expertise/{name}")
        assert is_permanently_blocked(f"/SinAuto_MAMDA/expertise/{name}")


def test_mamda_still_cannot_be_written_to():
    """The entity->writability rule itself; the DB-level enforcement is
    covered by tests/execution/jobs/test_mamda_enforcement_execution.py."""
    from mcma.domain.portal_accounts import PortalAccountProfile, PortalEntity, PortalScope

    for scope in (PortalScope.OUJDA, PortalScope.NADOR):
        assert PortalAccountProfile(PortalEntity.MAMDA, scope).is_mcma is False
        assert PortalAccountProfile(PortalEntity.MCMA, scope).is_mcma is True


@pytest.mark.skip(reason="REAL_MCMA_WRITE_CONTRACT_CAPTURE_PENDING_ONSITE: needs a supervised onsite session")
def test_REAL_MCMA_WRITE_CONTRACT_CAPTURE_PENDING_ONSITE():
    """Deferred onsite evidence capture, recorded so it stays visible.

    This is NOT automated writing. A human performs every portal action;
    the tool only observes. Run onsite, on an approved test dossier:

        python tools/capture_sinauto_write_evidence.py

    Capture, for MCMA only:

      1. adding one Mode Normal row -- the request the checkmark issues:
         path, method, content type, body FIELD NAMES, response status
      2. editing one Garage Conventionné row -- the same for updateDevisDet
      3. triggering the native calculation -- which function exists, and
         what request or event signals completion
      4. selector presence for the reviewed financial-summary list, to
         show whether the trigger actually populates it
      5. selector presence for the four unconfirmed header field ids

    The output carries field NAMES and no values. A later C.3 patch turns
    the reviewed capture into contracts; the tool never writes contracts
    itself, because portal data must not self-authorize a route."""
