"""
INC-09B -- static proof that the writer's WRITE/FILL-classified JS
constants never reference either charge field, while explicitly allowing
(and expecting) them in the READ-classified script -- distinguishing
reads from writes by constant NAME, not a blanket source-wide string ban.
The complementary real-Chromium proof (actual outgoing request bodies)
lives in the PEC/Mode Normal lifecycle proofs, which read back committed
rows via fetch and never see either charge field in a write payload.
"""

import mcma.portal.writer as writer_module

_CHARGE_FIELD_NAMES = ("MontantChargeMutuelle", "MontantChargeSocietaire", "ChargeMutuelle", "ChargeSocietaire")

_FILL_JS_CONSTANTS = ("_FILL_NORMAL_ROW_JS", "_FILL_PEC_ROW_JS")


def test_fill_scripts_never_reference_a_charge_field():
    for name in _FILL_JS_CONSTANTS:
        script = getattr(writer_module, name)
        for charge_name in _CHARGE_FIELD_NAMES:
            assert charge_name not in script, f"{name} must never reference {charge_name}"


def test_read_financial_summary_script_legitimately_references_the_confirmed_charge_fields():
    script = writer_module._READ_FINANCIAL_SUMMARY_JS
    assert "DevisMontantChargeMutuelle" in script
    assert "DevisMontantChargeSocietaire" in script


def test_row_write_methods_never_construct_a_dict_containing_a_charge_field_key():
    import ast
    import inspect
    import textwrap

    for method_name in ("add_normal_row", "edit_conventionne_row"):
        source = textwrap.dedent(inspect.getsource(getattr(writer_module.VerifiedMissionWriter, method_name)))
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in _CHARGE_FIELD_NAMES, (
                    f"{method_name} must never reference the literal {node.value!r}"
                )
