from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from mcma.adapters.browser import BrowserConfig, McmaBrowserAdapter
from mcma.application.service import DossierFillService, RunConfig, print_plan
from mcma.domain.models import RubricMode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare an MCMA mission from a Wexia JSON dossier without final validation or GED"
    )
    parser.add_argument("--json", required=True, help="Path to the Wexia dossier JSON")
    parser.add_argument("--auth-state", default="mcma_auth_state.json", help="Playwright storage-state file")
    parser.add_argument(
        "--rubric-mode",
        choices=[mode.value for mode in RubricMode],
        default=RubricMode.PREVIEW.value,
        help="preview blocks rubrique writes; draft permits only rubrique row create/update",
    )
    parser.add_argument(
        "--confirm-draft-writes",
        action="store_true",
        help="required with --rubric-mode draft because editable-table checkmarks write draft rows",
    )
    parser.add_argument("--plan-only", action="store_true", help="validate/map JSON without opening MCMA")
    parser.add_argument("--headless", action="store_true", help="run without a visible browser (not recommended for testing)")
    parser.add_argument("--slow-mo", type=int, default=150, help="browser action delay in milliseconds")
    return parser


async def _run(args: argparse.Namespace) -> int:
    rubric_mode = RubricMode(args.rubric_mode)
    if rubric_mode is RubricMode.DRAFT and not args.confirm_draft_writes:
        print(
            "ERROR: draft rubrique mode sends create/update row requests. "
            "Add --confirm-draft-writes after reviewing the plan.",
            file=sys.stderr,
        )
        return 2

    service = DossierFillService(session_factory=McmaBrowserAdapter)
    plan = service.prepare(args.json)
    print_plan(plan)
    if args.plan_only:
        return 0

    config = RunConfig(
        browser=BrowserConfig(
            auth_state=Path(args.auth_state),
            headless=args.headless,
            slow_mo_ms=max(args.slow_mo, 0),
        ),
        rubric_mode=rubric_mode,
    )
    summary = await service.execute(plan, config)
    print(
        f"Completed: fields={len(summary.filled_fields)}, "
        f"drafted_rubrics={len(summary.drafted_rubrics)}, "
        f"blocked_requests={len(summary.blocked_requests)}"
    )
    if summary.skipped_fields:
        print("Skipped fields:")
        for field, reason in summary.skipped_fields.items():
            print(f"  - {field}: {reason}")
    return 0


def main() -> None:
    args = build_parser().parse_args()
    try:
        raise SystemExit(asyncio.run(_run(args)))
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
