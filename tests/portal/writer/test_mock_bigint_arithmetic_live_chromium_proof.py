"""
INC-09B amendment #3 -- exact BigInt/HALF_UP arithmetic in the mock's own
embedded client-side JS (parseMoneyToCents/centsToMoneyString/
halfUpDivideBigInt). Tested via a real headless Chromium evaluating the
actual browser JS directly (there is no Node/JS test runner in this
project's dependency set) -- exercises: an exact .5 boundary, a repeating
fraction, a value beyond Number.MAX_SAFE_INTEGER, a zero denominator, a
malformed input, excess decimal precision, and canonical two-decimal
output.

Round-3 correction (item A.1): a single-argument callback destructuring
its argument as `([s]) => ...` while being passed a bare Python string
(not wrapped in a list) makes Playwright hand it a plain JS string, and
array-destructuring a STRING takes only its first character. Every
single-scalar callback below now takes the scalar directly (`(s) => ...`,
no destructuring) instead; multi-argument callbacks that are genuinely
passed a Python list (`[n, d]`) are unaffected and unchanged.
"""

import pytest

from writer_live_chromium_test_support import ALLOWED_HOST, live_mock_server  # noqa: F401
from writer_test_support import run_async

pytestmark = [pytest.mark.egress_proof, pytest.mark.requires_egress_isolation]


async def _evaluate_on_mission_page(script, arg=None):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(f"http://{ALLOWED_HOST}/SinAuto_MCMA/expertise/gestionexpert/index")
            return await page.evaluate(script, arg)
        finally:
            await browser.close()


def test_half_up_divide_exact_half_boundary(live_mock_server):
    # 5n/2n -> quotient=2, remainder=1, 2*1=2 >= 2 -> rounds up to 3.
    result = run_async(_evaluate_on_mission_page("([n, d]) => halfUpDivideBigInt(BigInt(n), BigInt(d)).toString()", [5, 2]))
    assert result == "3"


def test_half_up_divide_repeating_fraction(live_mock_server):
    # 10n/3n -> quotient=3, remainder=1, 2*1=2 < 3 -> stays 3 (not a tie).
    result = run_async(_evaluate_on_mission_page("([n, d]) => halfUpDivideBigInt(BigInt(n), BigInt(d)).toString()", [10, 3]))
    assert result == "3"


def test_half_up_divide_beyond_number_max_safe_integer(live_mock_server):
    # 2^53 = 9007199254740992, well beyond Number.MAX_SAFE_INTEGER-safe
    # float arithmetic if it were done with ordinary numeric division.
    huge_numerator = "9007199254740993000"
    result = run_async(
        _evaluate_on_mission_page(
            "([n, d]) => halfUpDivideBigInt(BigInt(n), BigInt(d)).toString()", [huge_numerator, "1000"]
        )
    )
    assert result == "9007199254740993"


def test_half_up_divide_zero_denominator_raises(live_mock_server):
    result = run_async(
        _evaluate_on_mission_page(
            "([n, d]) => { try { halfUpDivideBigInt(BigInt(n), BigInt(d)); return 'no-error'; } "
            "catch (e) { return 'error:' + e.message; } }",
            [10, 0],
        )
    )
    assert result.startswith("error:")


def test_parse_money_to_cents_rejects_malformed_input(live_mock_server):
    result = run_async(
        _evaluate_on_mission_page(
            "(s) => { try { parseMoneyToCents(s); return 'no-error'; } "
            "catch (e) { return 'error:' + e.message; } }",
            "12.3.4",
        )
    )
    assert result.startswith("error:")


def test_parse_money_to_cents_rejects_excess_decimal_precision(live_mock_server):
    result = run_async(
        _evaluate_on_mission_page(
            "(s) => { try { parseMoneyToCents(s); return 'no-error'; } "
            "catch (e) { return 'error:' + e.message; } }",
            "12.345",
        )
    )
    assert result.startswith("error:")


def test_cents_to_money_string_canonical_two_decimal_output(live_mock_server):
    result = run_async(_evaluate_on_mission_page("(c) => centsToMoneyString(BigInt(c))", "500"))
    assert result == "5.00"
    result_neg = run_async(_evaluate_on_mission_page("(c) => centsToMoneyString(BigInt(c))", "-5"))
    assert result_neg == "-0.05"


def test_parse_then_format_round_trips_exactly(live_mock_server):
    result = run_async(
        _evaluate_on_mission_page(
            "(s) => centsToMoneyString(parseMoneyToCents(s))", "1234.50"
        )
    )
    assert result == "1234.50"
