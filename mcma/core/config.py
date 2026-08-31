"""
mcma.core.config — typed settings (single source; supersedes the duplicated
baseline constants, F28). Stub established at INC-03; later increments extend
it. Fail-closed defaults only; no secrets ever live here.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


@dataclass(frozen=True)
class Settings:
    """Typed runtime settings. All later settings (DB path, TLS, DPAPI vault,
    retention, subnet allowlist) are added here as typed fields with
    fail-closed defaults — never as bare stringly-typed flags."""

    # DATA_MODEL.md §9: outside any served directory (mcma.web/static are
    # served; "var" is not).
    db_path: Path = Path("var") / "mcma.sqlite3"

    # The API binds loopback until INC-18 introduces TLS-only LAN serving.
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # INC-18 (ADR-0008): TLS is required for LAN deployment. No default
    # cert/key path is ever guessed -- None means "not configured", and
    # mcma.app.serve fails closed (refuses to start) rather than serving
    # plaintext when either is missing. subnet_allowlist is defense-in-
    # depth ONLY (empty by default) and never disables authentication.
    tls_cert_path: Optional[Path] = None
    tls_key_path: Optional[Path] = None
    subnet_allowlist: Tuple[str, ...] = ()

    # -- runner composition (mcma.app.main) --------------------------------
    # instance_id identifies THIS process in account_leases.owner_instance_id
    # (INC-11): a lease row names the instance holding it, so an operator
    # reading the table can tell which process to look at.
    instance_id: str = "mcma-pilot-1"
    mutex_name: str = "mcma-single-instance"

    # Encrypted session vault directory (DATA_MODEL.md §9: outside any
    # served directory, same rule as db_path).
    vault_dir: Path = Path("var") / "vault"

    # The ONE portal host every browser context is bound to. Loopback here
    # means the mock portal; mcma.portal.writer._require_loopback_host
    # structurally refuses anything else for a WRITER, so this cannot be
    # pointed at the live portal by editing a setting -- see
    # dev_mode below and RELEASE_GATES.md G5.
    allowed_host: str = "127.0.0.1:8080"

    # The host used for LOGGING IN and for READING notifications, which is
    # a different question from where form filling is allowed to go.
    # Signing a human in and reading an alert list cannot alter a claim,
    # so those legitimately reach the real portal today; writing a row is
    # what G5/INC-23 gates, and that path is bound to allowed_host above
    # and independently refuses a non-loopback host.
    #
    # Kept as a literal rather than importing the constant from
    # mcma.portal.sinauto_contracts: mcma.core is the bottom layer and
    # may not import upward. sinauto_allowed_host() validates it.
    portal_host: str = "sinauto.mamda-mcma.ma"

    # How often the runner drains QUEUED/PLANNED jobs. Not a correctness
    # parameter: nothing depends on a job being picked up within any
    # particular time, and every state transition is durable regardless.
    poll_interval_seconds: float = 2.0

    # Show the automated browser. False (headful) is production: the human
    # handoff requires the employee to see and close the window themselves.
    headless_browser: bool = False

    # DEV MODE means one thing only: form filling targets the loopback
    # mock rather than the real portal. It used to ALSO decide how job
    # inputs and portal sessions were stored, which meant the normal
    # employee application -- which runs in this composition -- persisted
    # both with test-only backends. Storage is now chosen by the two
    # explicit settings below, so "I am pointed at the mock" can never
    # again silently mean "PII may be stored unprotected".
    dev_mode: bool = False

    # UNSAFE STORAGE, named so that reading it is enough to know.
    # TestOnlyPlaintextEncryptor stores dossier JSON -- claimant names,
    # registrations, amounts -- verbatim, and TestOnlyInMemoryCryptoBackend
    # is a prefix rather than encryption, so portal session cookies would
    # sit on disk essentially in the clear. Both default False and are
    # opted into by tests and mocks alone.
    allow_test_plaintext_job_inputs: bool = False
    allow_test_only_session_vault: bool = False

    # Single-office local install: one machine, one team, bound to
    # loopback. The employee already holds four portal passwords; a fifth
    # one for this tool adds a login without adding a boundary. Enabling
    # this skips the bootstrap-token and sign-in steps for LOOPBACK
    # requests only -- every permission and account-access check still
    # runs against a real user row. Off by default: a LAN deployment must
    # opt in deliberately, and would not.
    local_single_user_mode: bool = False

    # How long startup waits for the shared browser before failing. The
    # application does not serve traffic until this succeeds, so the
    # employee never sees a dashboard whose login buttons cannot work.
    browser_startup_timeout_seconds: float = 60.0

    # Notification polling. Previously this was gated on a non-empty
    # category list that nothing ever set, so a perfectly healthy
    # application never made a single notification request -- running and
    # polling were not the same thing.
    #
    # No reviewed fixed list of alert codes exists anywhere in this
    # repository (the categories table ships empty) and the baseline read
    # them from the portal's own notification surface, so an empty list
    # now means DISCOVER, and a configured list is an override for an
    # office that wants to restrict what is polled.
    notifications_enabled: bool = True
    notification_category_codes: Tuple[str, ...] = ()

    # How often notifications are refreshed. Far longer than the job poll
    # interval: notifications change on a human timescale, and each pass
    # takes an account's lease briefly.
    notification_poll_interval_seconds: float = 300.0


class UnsafeDevModeConfiguration(Exception):
    """dev_mode was requested against something other than the loopback
    mock portal. Raised at startup, before anything opens."""


def _is_loopback_host(allowed_host: str) -> bool:
    from ipaddress import ip_address
    from urllib.parse import urlsplit

    try:
        hostname = urlsplit(f"http://{allowed_host}").hostname
        return hostname is not None and ip_address(hostname).is_loopback
    except ValueError:
        return False


def require_dev_mode_is_safe(settings: "Settings") -> None:
    """Refuses to start when unprotected storage is combined with a real
    write target.

    The rule now keys off the storage setting rather than dev_mode,
    because those became separate things: dev_mode alone no longer means
    anything is stored unprotected. What must never happen is
    plaintext job inputs -- which are CONTAINS_PII -- alongside a
    non-loopback write target, i.e. real dossiers stored in the clear.

    Checked here, before the database is opened or a browser is launched.
    mcma.portal.writer refuses a live host too, but only once a job is
    already underway and its PII has already been written to disk.
    Failing here means it never is."""
    if settings.allow_test_plaintext_job_inputs and not _is_loopback_host(settings.allowed_host):
        raise UnsafeDevModeConfiguration(
            "allow_test_plaintext_job_inputs stores dossier JSON verbatim and is "
            f"only permitted against the loopback mock portal; allowed_host={settings.allowed_host!r} "
            "is not loopback. Real dossier PII must never be stored through it."
        )


def load_settings() -> Settings:
    """Returns the typed settings. Deterministic; reads no environment and no
    files at this increment."""
    return Settings()
