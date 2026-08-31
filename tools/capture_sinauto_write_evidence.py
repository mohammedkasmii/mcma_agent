"""
tools/capture_sinauto_write_evidence.py -- observe, never act.

Several facts in docs/recovery/LIVE_WRITE_EVIDENCE_MATRIX.md cannot be
recovered from this repository's history at all. Most importantly, the
Mode Normal row-persistence request has NO recovered evidence: the
baseline clicked the checkmark and re-read the DOM without ever watching
the network. Those facts have to be observed once, onsite, by a human
doing the work while this watches.

THIS IS NOT AN AGENT. It fills nothing, clicks nothing and submits
nothing. It opens a browser, and the employee does every single action
themselves -- login, OTP, opening the dossier, adding or editing a row,
triggering a calculation. The script's only job is to write down the
SHAPE of what happened.

WHAT IT RECORDS, and nothing else:

    method, normalized path template, content type,
    query field NAMES, body field NAMES,
    response status, response content type, sequence number

WHAT IT NEVER RECORDS: any value. Not a username, password or OTP; not a
claim reference, registration, client name or amount; not cookies,
Authorization headers, request bodies, response bodies or page HTML.
Values are discarded at the point of parsing rather than collected and
filtered later, because a filter is something you can forget to apply.

Path identifiers are normalized before storage -- .../idSinistre/699001/...
becomes .../idSinistre/{id}/... -- so the file cannot say which dossier
was open.

It NEVER edits Python source or RouteContracts. Portal data must not be
able to authorize a route. A human reads the capture; a later patch turns
reviewed evidence into contracts.

    python tools/capture_sinauto_write_evidence.py

Not part of the `mcma` import-linter package: like the onboarding tool,
this is a standalone operator script.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# The permanent final-action list is production's, not a copy. A second
# tuple here would drift the moment an endpoint is added to one and not
# the other, and the copy that lags is the one that lets a final action
# through.
from mcma.portal.canonical import canonicalize_request  # noqa: E402
from mcma.portal.final_endpoints import (  # noqa: E402
    PERMANENTLY_BLOCKED_ENDPOINTS,
    is_permanently_blocked,
)

BLOCKED = PERMANENTLY_BLOCKED_ENDPOINTS

PORTAL_HOST = "sinauto.mamda-mcma.ma"
# MCMA only. MAMDA writes are prohibited, so MAMDA traffic can never be
# write-contract evidence and is not collected at all.
MCMA_BASE = "/SinAuto_MCMA"

OUTPUT_DIR = REPO_ROOT / "var" / "evidence"

# Selector presence only -- booleans, never values.
#
# Split BY WORKFLOW. A single union across two dossiers would answer the
# wrong question: what is needed is whether #MontantHTValide exists on a
# PEC page, not whether it existed on one of the two pages someone
# happened to open. Each run observes ONE approved dossier.

_HEADER_SELECTORS = (
    "#Kilometrage", "#ValeurVenale", "#ValeurVenaleEstime",
    "#NbreJourImmobilisation", "#PartResponsabilite", "#ObservationMission",
)

_MODE_NORMAL_SELECTORS = (
    # Row lifecycle
    "#VehRepareI", "#IdRubrique", "#MontantHT", "#Taxe", "#tableRapportDet",
    # Financial summary -- READ evidence only. #MontantChargeMutuelle and
    # #MontantChargeSocietaire are probed for PRESENCE; writing them is
    # the prohibited charge-split overwrite (BUSINESS_RULES.md B.3).
    "#MontantReparation", "#MontantTVA", "#MontantTTC", "#TauxVetuste",
    "#MontantVetuste", "#MontantFranchise", "#PartResponsabilite",
    "#MontantRemise", "#MontantChargeMutuelle", "#MontantChargeSocietaire",
    "#MontantArrete", "#BaseIndemnite",
) + _HEADER_SELECTORS

_GARAGE_CONVENTIONNE_SELECTORS = (
    "#DevisDetTable", "#DevisDetTableVal", "#blocDevisValide",
    "#MontantHTValide", "#TaxeValide", "#MontantTTCValide",
    "#TauxVetusteValide", "#MontantVetusteValide",
    "#DevisTvaRecupI", "#DevisMontantTVA", "#DevisMontantTTC",
    "#DevisMontantVetusteTotal", "#DevisMontantFranchise",
    "#DevisMontantRemise", "#DevisPartResponsabilite",
    "#DevisMontantChargeMutuelle", "#DevisMontantChargeSocietaire",
    "#MontantArrete", "#BaseIndemnite",
) + _HEADER_SELECTORS

# Existence only, for the triggers the baseline called defensively. A
# fixed list -- globals are never enumerated.
PROBE_FUNCTIONS = (
    "CalculerMntArrete", "CalculerMontantDommage", "DevisCalculerMontantCharge",
)

WORKFLOWS = {
    "mode-normal": _MODE_NORMAL_SELECTORS,
    "garage-conventionne": _GARAGE_CONVENTIONNE_SELECTORS,
}

_NUMERIC_SEGMENT = re.compile(r"^\d+$")

# A field name looks like a field name. Anything else is dropped rather
# than recorded, because parse_qsl happily turns an unparseable body into
# a single enormous "name" -- which would carry the whole body, values and
# all, into the file under the guise of a key.
_FIELD_NAME = re.compile(r"^[A-Za-z0-9_.\[\]-]{1,64}$")


def normalize_path(path: str) -> str:
    """Replaces identifying segments with placeholders.

    .../getSinistre/idSinistre/699001/rubrique/x -> .../idSinistre/{id}/rubrique/x

    A bare numeric segment is always an identifier here, and a segment
    following a known id-carrying key is replaced whatever it looks like.
    Over-normalizing loses nothing: the template is what is wanted, and
    the identifier is exactly what must not be written down."""
    keyed = {"idsinistre", "idmission", "iddevisdet", "idrapportdet", "id"}
    segments = path.split("/")
    out = []
    for index, segment in enumerate(segments):
        if not segment:
            out.append(segment)
            continue
        previous = segments[index - 1].lower() if index else ""
        if previous in keyed or _NUMERIC_SEGMENT.match(segment):
            out.append("{id}")
        else:
            out.append(segment)
    return "/".join(out)


def safe_field_names(candidates) -> list[str]:
    """Keeps only names that look like names, and drops everything else.

    Applied to query keys as well as body keys: parse_qsl will happily
    return a whole malformed fragment as a single key, and a key is
    persisted while a value is not -- so an unfiltered key is a way for
    raw material to reach the file through the one field that gets
    written down."""
    return sorted({name for name in candidates if _FIELD_NAME.match(name)})


def field_names(content_type: str | None, body: str | None) -> list[str]:
    """Parses a body for its KEYS and drops the values immediately. The
    values are never bound to a name that outlives this function."""
    if not body:
        return []
    ctype = (content_type or "").lower()
    try:
        if "json" in ctype:
            parsed = json.loads(body)
            candidates = list(parsed.keys()) if isinstance(parsed, dict) else []
        else:
            # Default to form encoding, which is what the portal uses.
            candidates = [name for name, _value in parse_qsl(body, keep_blank_values=True)]
    except Exception:
        candidates = []
    # A form field must have arrived as an actual name=value pair. A bare
    # fragment with no "=" is not a field, whatever it looks like.
    if "json" not in (content_type or "").lower():
        candidates = [name for name in candidates if f"{name}=" in (body or "")]
    names = safe_field_names(candidates)
    if not names:
        # Nothing that looks like a field name. Say so, and say nothing
        # else -- never fall back to the raw text.
        return ["<unparseable>"]
    return names


def is_in_scope(url: str) -> bool:
    parts = urlsplit(url)
    return parts.hostname == PORTAL_HOST and parts.path.startswith(MCMA_BASE + "/")


def canonical_path_or_none(url: str) -> str | None:
    """The path as production canonicalizes it, or None if the path is
    suspicious -- encoded separators, traversal segments, duplicate
    slashes.

    Only the PATH rules are wanted here, so method/content-type/body are
    passed as a plain GET: canonicalize_request also rejects bodies with
    duplicate field names, and applying that to a live portal would abort
    ordinary page traffic that has nothing to do with final actions."""
    canonical = canonicalize_request(
        raw_url=url, raw_method="GET", raw_content_type=None, raw_body=None
    )
    return canonical.path if canonical is not None else None


def is_blocked(url_or_path: str) -> bool:
    """Fail safe. A path we cannot canonicalize is treated as blocked
    rather than allowed: an encoded or traversal-laden path is exactly how
    a final action would slip past a substring check, and refusing an
    ambiguous request costs a retry while allowing one could close a
    claim."""
    candidate = url_or_path
    if "://" in url_or_path:
        canonical = canonical_path_or_none(url_or_path)
        if canonical is None:
            return True
        candidate = canonical
    elif urlsplit(f"https://{PORTAL_HOST}{url_or_path}").path != url_or_path:
        return True
    else:
        canonical = canonical_path_or_none(f"https://{PORTAL_HOST}{url_or_path}")
        if canonical is None:
            return True
        candidate = canonical
    return is_permanently_blocked(candidate)


class Capture:
    def __init__(self):
        self.events: list[dict] = []
        self.blocked: list[dict] = []
        self.sequence = 0

    def record_request(self, method: str, url: str, content_type, body) -> None:
        self.sequence += 1
        self.events.append({
            "seq": self.sequence,
            "kind": "request",
            "method": method,
            "path_template": normalize_path(urlsplit(url).path),
            "content_type": (content_type or "").split(";")[0] or None,
            "query_field_names": safe_field_names(
                k for k, _ in parse_qsl(urlsplit(url).query, keep_blank_values=True)
            ),
            "body_field_names": field_names(content_type, body),
        })

    def record_response(self, url: str, status: int, content_type) -> None:
        self.sequence += 1
        self.events.append({
            "seq": self.sequence,
            "kind": "response",
            "path_template": normalize_path(urlsplit(url).path),
            "status": status,
            "content_type": (content_type or "").split(";")[0] or None,
        })

    def record_blocked(self, method: str, url: str) -> None:
        self.blocked.append({
            "method": method,
            "path_template": normalize_path(urlsplit(url).path),
        })

    def to_document(self, workflow: str, selectors: dict, functions: dict) -> dict:
        return {
            "workflow": workflow,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "host": PORTAL_HOST,
            "base": MCMA_BASE,
            "note": (
                "Field NAMES only. No values, cookies, headers, bodies or page "
                "HTML are recorded. Path identifiers are normalized."
            ),
            "events": self.events,
            "blocked_attempts": self.blocked,
            "selector_present": selectors,
            "function_present": functions,
        }


INSTRUCTIONS = {
    "mode-normal": (
        "1. Connectez-vous (mot de passe + OTP)",
        "2. Ouvrez un dossier de test MODE NORMAL approuvé",
        "3. Ajoutez UNE ligne représentative (Ajouter, remplir, coche)",
        "4. Déclenchez le calcul comme vous le faites normalement",
        "5. LAISSEZ LE NAVIGATEUR OUVERT et revenez ici",
    ),
    "garage-conventionne": (
        "1. Connectez-vous (mot de passe + OTP)",
        "2. Ouvrez un dossier de test GARAGE CONVENTIONNÉ approuvé",
        "3. Modifiez UNE ligne validée représentative (crayon, coche)",
        "4. Déclenchez le calcul comme vous le faites normalement",
        "5. LAISSEZ LE NAVIGATEUR OUVERT et revenez ici",
    ),
}


async def probe_dom(page, workflow: str):
    """Boolean presence for the workflow's fixed lists. Runs while the
    page is still OPEN -- the previous version probed after the close
    event, when page.evaluate can no longer work, so it collected network
    shapes and silently lost every piece of DOM evidence, which is most of
    what the audit says is missing."""
    selectors = await page.evaluate(
        "(list) => Object.fromEntries(list.map(s => [s, document.querySelector(s) !== null]))",
        list(WORKFLOWS[workflow]),
    )
    functions = await page.evaluate(
        "(list) => Object.fromEntries(list.map(n => [n, typeof window[n] === 'function']))",
        list(PROBE_FUNCTIONS),
    )
    return selectors, functions


async def _run(workflow: str) -> None:  # pragma: no cover - operator-driven session
    from playwright.async_api import async_playwright

    capture = Capture()

    print()
    print("=" * 70)
    print(f"  CAPTURE DE CONTRAT — {workflow.upper()} — OBSERVATION SEULE")
    print("=" * 70)
    print("  CET OUTIL NE CLIQUE NI NE REMPLIT RIEN.")
    print("  Vous faites toutes les actions vous-même.")
    print()
    for line in INSTRUCTIONS[workflow]:
        print(f"  {line}")
    print()
    print("  Les actions finales (Valider, Clôture, Enregistrer, GED)")
    print("  sont bloquées et ne partiront jamais.")
    print("=" * 70)
    print()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        context = await browser.new_context()

        async def _route(route):
            request = route.request
            url = request.url
            if not is_in_scope(url):
                await route.continue_()      # not ours; not recorded either
                return
            if is_blocked(url):
                # Aborted truthfully. A fake 200 would tell the portal's
                # own JavaScript that a final action succeeded.
                capture.record_blocked(request.method, url)
                print(f"[BLOQUÉ] {request.method} {normalize_path(urlsplit(url).path)}")
                await route.abort("blockedbyclient")
                return
            capture.record_request(
                request.method, url,
                request.headers.get("content-type"),
                request.post_data,
            )
            await route.continue_()

        await context.route("**/*", _route)

        def _on_response(response):
            if is_in_scope(response.url):
                capture.record_response(
                    response.url, response.status,
                    response.headers.get("content-type"),
                )

        context.on("response", _on_response)

        page = await context.new_page()
        await page.goto(f"https://{PORTAL_HOST}{MCMA_BASE}/")

        # The page stays open for this. Blocking on input() would freeze
        # the event loop that is servicing the browser, so it runs on a
        # thread.
        await asyncio.get_running_loop().run_in_executor(
            None,
            input,
            "\n>>> Appuyez sur Entrée lorsque le dossier est prêt pour la capture DOM... ",
        )

        selectors, functions = {}, {}
        try:
            selectors, functions = await probe_dom(page, workflow)
            print("[*] Capture DOM terminée. Vous pouvez fermer le navigateur.")
        except Exception:
            print("[!] Capture DOM impossible (page fermée ?). Réessayez sans fermer.")

        await browser.close()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = OUTPUT_DIR / f"write-contract-{workflow}-{stamp}.json"
    out.write_text(
        json.dumps(capture.to_document(workflow, selectors, functions), indent=2),
        encoding="utf-8",
    )

    print()
    print(f"[*] {len(capture.events)} évènements enregistrés (noms de champs seulement).")
    print(f"[*] {sum(1 for v in selectors.values() if v)}/{len(selectors)} sélecteurs présents.")
    if capture.blocked:
        print(f"[*] {len(capture.blocked)} action(s) finale(s) bloquée(s).")
    print(f"[*] Fichier : {out}")
    print("[*] Relisez-le avant de le partager. Il ne doit contenir aucune valeur.")


def main() -> None:  # pragma: no cover - operator entry point
    import argparse

    parser = argparse.ArgumentParser(description="Observe SinAuto write contracts. Never acts.")
    parser.add_argument(
        "--workflow", required=True, choices=sorted(WORKFLOWS),
        help="which approved test dossier this run observes",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.workflow))


if __name__ == "__main__":  # pragma: no cover
    main()
