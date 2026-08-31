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

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

PORTAL_HOST = "sinauto.mamda-mcma.ma"
# MCMA only. MAMDA writes are prohibited, so MAMDA traffic can never be
# write-contract evidence and is not collected at all.
MCMA_BASE = "/SinAuto_MCMA"

OUTPUT_DIR = REPO_ROOT / "var" / "evidence"

# Selector presence only -- booleans, never values. Drawn from the
# evidence matrix's unconfirmed and read-back lists.
PROBE_SELECTORS = (
    # Mode Normal row lifecycle
    "#VehRepareI", "#IdRubrique", "#MontantHT", "#Taxe", "#tableRapportDet",
    # Mode Normal financial summary
    "#MontantReparation", "#MontantTVA", "#MontantTTC", "#TauxVetuste",
    "#MontantVetuste", "#MontantFranchise", "#MontantRemise",
    "#MontantChargeMutuelle", "#MontantChargeSocietaire", "#MontantArrete",
    "#BaseIndemnite",
    # PEC
    "#DevisDetTable", "#DevisDetTableVal", "#blocDevisValide",
    "#MontantHTValide", "#TaxeValide", "#MontantTTCValide",
    "#TauxVetusteValide", "#MontantVetusteValide",
    "#DevisTvaRecupI", "#DevisMontantTVA", "#DevisMontantTTC",
    "#DevisMontantVetusteTotal", "#DevisMontantFranchise",
    "#DevisMontantRemise", "#DevisPartResponsabilite",
    "#DevisMontantChargeMutuelle", "#DevisMontantChargeSocietaire",
    # Header fields -- four of these are UNCONFIRMED and this settles it
    "#Kilometrage", "#ValeurVenale", "#ValeurVenaleEstime",
    "#NbreJourImmobilisation", "#PartResponsabilite", "#ObservationMission",
)

# Existence only, for the calculation triggers the baseline called
# defensively. A fixed list -- globals are never enumerated.
PROBE_FUNCTIONS = (
    "CalculerMntArrete", "CalculerMontantDommage", "DevisCalculerMontantCharge",
)

# Never sent, even by a human's misclick, even during evidence capture.
BLOCKED = (
    "garageModifierValDevis", "validerDevis", "deleteDevisDet",
    "expertCloturerMission", "cloturerMission", "enregistrerMission",
    "expertEnregistrerMission", "ajouterDocument", "deleteDocument",
    "cloturerTraitement",
)

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
    names = sorted({name for name in candidates if _FIELD_NAME.match(name)})
    if not names:
        # Nothing that looks like a field name. Say so, and say nothing
        # else -- never fall back to the raw text.
        return ["<unparseable>"]
    return names


def is_in_scope(url: str) -> bool:
    parts = urlsplit(url)
    return parts.hostname == PORTAL_HOST and parts.path.startswith(MCMA_BASE + "/")


def is_blocked(path: str) -> bool:
    return any(name in path for name in BLOCKED)


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
            "query_field_names": sorted({k for k, _ in parse_qsl(urlsplit(url).query)}),
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

    def to_document(self, selectors: dict, functions: dict) -> dict:
        return {
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


async def _run() -> None:  # pragma: no cover - operator-driven session
    from playwright.async_api import async_playwright

    from mcma.portal.sinauto_contracts import portal_base_for  # noqa: F401  (path sanity)

    capture = Capture()

    print()
    print("=" * 70)
    print("  CAPTURE DE CONTRAT — OBSERVATION SEULE")
    print("=" * 70)
    print("  Ce script ne remplit rien et ne clique sur rien.")
    print("  Vous faites toutes les actions vous-même.")
    print()
    print("  1. Connectez-vous (mot de passe + OTP)")
    print("  2. Ouvrez le dossier de test approuvé")
    print("  3. Ajoutez UNE ligne Mode Normal (Ajouter, remplir, coche)")
    print("  4. Modifiez UNE ligne Garage Conventionné (crayon, coche)")
    print("  5. Déclenchez le calcul si demandé")
    print()
    print("  Les actions finales (Valider, Clôture, Enregistrer, GED)")
    print("  sont bloquées par ce script et ne partiront jamais.")
    print()
    print("  Fermez le navigateur quand vous avez terminé.")
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
            path = urlsplit(url).path
            if is_blocked(path):
                # Aborted truthfully. A fake 200 would tell the portal's
                # own JavaScript that a final action succeeded.
                capture.record_blocked(request.method, url)
                print(f"[BLOQUÉ] {request.method} {normalize_path(path)}")
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

        closed = {"value": False}
        page.on("close", lambda _p: closed.update(value=True))
        while not closed["value"]:
            await page.wait_for_timeout(1000)

        selectors, functions = {}, {}
        try:
            selectors = await page.evaluate(
                "(list) => Object.fromEntries(list.map(s => [s, document.querySelector(s) !== null]))",
                list(PROBE_SELECTORS),
            )
            functions = await page.evaluate(
                "(list) => Object.fromEntries(list.map(n => [n, typeof window[n] === 'function']))",
                list(PROBE_FUNCTIONS),
            )
        except Exception:
            print("[!] La page était déjà fermée : sondes DOM non collectées.")

        await browser.close()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = OUTPUT_DIR / f"write-contract-capture-{stamp}.json"
    out.write_text(json.dumps(capture.to_document(selectors, functions), indent=2), encoding="utf-8")

    print()
    print(f"[*] {len(capture.events)} évènements enregistrés (noms de champs seulement).")
    if capture.blocked:
        print(f"[*] {len(capture.blocked)} action(s) finale(s) bloquée(s).")
    print(f"[*] Fichier : {out}")
    print("[*] Relisez-le avant de le partager. Il ne doit contenir aucune valeur.")


def main() -> None:  # pragma: no cover - operator entry point
    import asyncio

    asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover
    main()
