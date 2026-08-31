"""
tools/private_dossier_validation.py -- owner-authorized, generic,
LOCAL-ONLY validation of a directory of real Wexia dossier JSON files
against the typed boundary + deterministic planning pipeline.

Not part of the `mcma` import-linter root package (a standalone operator
script, like tools/onboarding_tool.py) -- it may import mcma.* directly.

THIS SCRIPT CONTAINS NO DOSSIER-SPECIFIC CONSTANT. It accepts an input
directory and never assumes a particular filename, claim reference,
registration, or any other real value. It is designed to be run manually,
once, by the machine's owner/operator -- it is never invoked from
automated tests (tests must never touch input_dossier/, per campaign
policy), and it never modifies or deletes anything under the input
directory.

Everything this script may report is an AGGREGATE, REDACTED count:
- number of files discovered / parsed successfully / failed to parse
- deterministic plans produced / needing review, split by workflow
- unsupported JSON key PATHS (never their values)
- sanitized validation-error reason counts (field path + error type only
  -- never the rejected value, never a raw exception message)
- whether any unsupported key path NAME suggests an office/city routing
  field (checked by NAME only, never by value)
- a determinism check (does building the same plan twice from the same
  parsed input produce the same plan_hash)

It never prints a filename, a raw JSON value, a claim reference, a
registration, an address, a phone number, a monetary value, or any
exception message that could carry a fragment of the real document.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from mcma.domain.enums import RepairWorkflow
from mcma.mapping.wexia import WexiaInput, parse_wexia
from mcma.planning.plan import PlanBuildError, build_garage_conventionne_plan, build_mission_normal_plan

# Office/city-routing NAME denylist (checked against unsupported KEY
# PATH NAMES only -- never against any value) -- section E of the
# correction batch: never infer account routing from dossier content,
# and this script must not silently assume such a field exists either.
_ROUTING_NAME_HINTS = (
    "oujda", "nador", "office", "bureau", "agence", "agency", "ville",
    "city", "region", "site", "branch", "succursale",
)

_KNOWN_TOP_LEVEL_KEYS = {"dossier", "vehicule", "chiffrages", "observations_expert", "assureur"}


def _redacted_error(exc: Exception) -> str:
    """Never returns str(exc) -- only the exception's CLASS NAME, which
    can never carry document content."""
    return type(exc).__name__


def _validation_error_reasons(exc: ValidationError) -> list:
    """Pydantic's own ValidationError.errors() carries an 'input' key
    with the RAW rejected value (and sometimes a value-bearing 'msg') --
    both are deliberately DROPPED here. Only ('loc' path, 'type') survive,
    exactly the campaign's 'safe field paths and fixed reason codes'
    requirement."""
    reasons = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error.get("loc", ()))
        reasons.append((loc, error.get("type", "unknown")))
    return reasons


def _collect_key_paths(obj: Any, prefix: str = "") -> set:
    """Every key path present in the raw parsed JSON, however deep --
    values are never inspected or returned, only the path structure."""
    paths = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.add(path)
            paths |= _collect_key_paths(value, path)
    elif isinstance(obj, list):
        for item in obj:
            paths |= _collect_key_paths(item, prefix)
    return paths


def _known_key_paths() -> set:
    """Every field path the typed WexiaInput boundary actually consumes
    -- derived once, structurally, from the pydantic model fields
    themselves (never a dossier-specific hardcoded list)."""
    known: set = set()

    def _walk(model_cls, prefix: str):
        for name, field in model_cls.model_fields.items():
            path = f"{prefix}.{name}" if prefix else name
            known.add(path)
            annotation = field.annotation
            # Unwrap Optional[...]/List[...] to find a nested pydantic model.
            args = getattr(annotation, "__args__", ())
            candidates = (annotation,) + args
            for candidate in candidates:
                if hasattr(candidate, "model_fields"):
                    _walk(candidate, path)

    _walk(WexiaInput, "")
    return known


def _try_build_a_plan(typed_input):
    """Attempts Mode Normal then Garage Conventionne (mirrors
    _detect_mode_fail_closed's own explicit-signal-only contract --
    exactly one succeeds, or neither, on any single real dossier). Never
    guesses; a dossier this fails on is counted, not force-fit."""
    last_reason = None
    for builder, workflow in (
        (build_mission_normal_plan, RepairWorkflow.MODE_NORMAL),
        (build_garage_conventionne_plan, RepairWorkflow.GARAGE_CONVENTIONNE),
    ):
        try:
            return builder(typed_input), workflow, None
        except PlanBuildError as exc:
            last_reason = _redacted_error(exc)
            continue
    return None, None, last_reason


def validate_directory(input_dir: Path) -> dict:
    files = sorted(input_dir.rglob("*.json"))  # sorted() only for stable iteration order, never printed

    counts = Counter()
    plan_build_reasons = Counter()
    validation_error_reasons = Counter()
    workflow_counts = Counter()
    needs_review_reasons = Counter()
    unsupported_key_paths = Counter()
    determinism_mismatches = 0
    routing_hint_key_paths: set = set()

    known_paths = _known_key_paths()

    for path in files:
        counts["files_discovered"] += 1
        try:
            raw_bytes = path.read_bytes()
        except OSError as exc:
            counts["unreadable"] += 1
            continue

        try:
            raw = json.loads(raw_bytes)
        except json.JSONDecodeError:
            # Deliberately NOT str(exc) -- JSONDecodeError's message can
            # embed a fragment of the document text itself.
            counts["parse_failed"] += 1
            continue

        if not isinstance(raw, dict):
            counts["parse_failed"] += 1
            continue

        for key_path in _collect_key_paths(raw):
            top_level = key_path.split(".", 1)[0]
            if top_level not in _KNOWN_TOP_LEVEL_KEYS:
                continue
            if key_path not in known_paths:
                unsupported_key_paths[key_path] += 1
                last_segment = key_path.rsplit(".", 1)[-1].lower()
                if any(hint in last_segment for hint in _ROUTING_NAME_HINTS):
                    routing_hint_key_paths.add(key_path)

        try:
            typed_input = parse_wexia(raw)
        except ValidationError as exc:
            counts["typed_boundary_rejected"] += 1
            for loc, error_type in _validation_error_reasons(exc):
                validation_error_reasons[(loc, error_type)] += 1
            continue
        except Exception as exc:  # fail closed on anything else too, never crash the batch
            counts["typed_boundary_rejected"] += 1
            validation_error_reasons[("<non-validation-error>", _redacted_error(exc))] += 1
            continue

        counts["parsed_successfully"] += 1

        plan, workflow, reason = _try_build_a_plan(typed_input)
        if plan is None:
            counts["plan_build_failed"] += 1
            if reason:
                plan_build_reasons[reason] += 1
            continue

        counts["plans_produced"] += 1
        workflow_counts[workflow.value] += 1
        if plan.needs_review:
            counts["plans_needing_review"] += 1
            for review in plan.needs_review:
                needs_review_reasons[review.reason.value] += 1
        else:
            counts["plans_deterministic_and_writeable_shape"] += 1

        # Determinism: rebuild from the SAME parsed input, compare hashes.
        try:
            second_plan, _, _ = _try_build_a_plan(typed_input)
            if second_plan is not None and second_plan.provenance.plan_hash != plan.provenance.plan_hash:
                determinism_mismatches += 1
        except Exception:
            determinism_mismatches += 1

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_directory_file_count": len(files),
        "counts": dict(counts),
        "workflow_counts": dict(workflow_counts),
        "plan_build_failure_reasons": dict(plan_build_reasons),
        "needs_review_reason_counts": dict(needs_review_reasons),
        "validation_error_reason_counts": {f"{loc} ({t})": n for (loc, t), n in validation_error_reasons.items()},
        "unsupported_key_path_counts": dict(unsupported_key_paths),
        "determinism_mismatches": determinism_mismatches,
        "possible_account_routing_key_paths": sorted(routing_hint_key_paths),
        "note": (
            "possible_account_routing_key_paths lists ONLY unsupported "
            "key path NAMES that superficially resemble an office/city "
            "concept -- never a value. An empty list means no such "
            "field name was found; it is NOT proof no routing signal "
            "exists under a differently-named key, and this script must "
            "never be used to infer routing on its own."
        ),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path, help="Directory containing local dossier JSON files")
    parser.add_argument("--output", type=Path, required=True, help="Path to write the redacted aggregate JSON report")
    args = parser.parse_args()

    if not args.input_dir.is_dir():
        print(f"error: not a directory: {args.input_dir}", file=sys.stderr)
        return 2

    report = validate_directory(args.input_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote aggregate report to {args.output} ({report['counts'].get('files_discovered', 0)} files discovered)")
    return 0


if __name__ == "__main__":  # pragma: no cover - manual operator entry point
    raise SystemExit(main())
