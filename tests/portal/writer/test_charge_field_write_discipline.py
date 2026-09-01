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

# The fill scripts now live in the golden drivers -- the writer's own
# mock-shaped ones are gone. The rule is unchanged: nothing that WRITES
# may name a charge field.
from mcma.portal import mode_normal_live as _normal_driver_module  # noqa: E402
from mcma.portal import pec_live as _pec_driver_module  # noqa: E402

_FILL_SCRIPTS = (
    ("mode_normal_live.FILL_INPUT_JS", _normal_driver_module.FILL_INPUT_JS),
    ("mode_normal_live.FILL_INPUT_FALLBACK_JS", _normal_driver_module.FILL_INPUT_FALLBACK_JS),
    ("mode_normal_live.SELECT_OPTION_JS", _normal_driver_module.SELECT_OPTION_JS),
    ("mode_normal_live.TRIGGER_CALCULATIONS_JS", _normal_driver_module.TRIGGER_CALCULATIONS_JS),
    ("pec_live.FILL_ROW_JS", _pec_driver_module.FILL_ROW_JS),
    ("pec_live.TRIGGER_CALCULATIONS_JS", _pec_driver_module.TRIGGER_CALCULATIONS_JS),
)


def test_fill_scripts_never_reference_a_charge_field():
    """Including the calculation triggers. The golden Mode Normal source
    wrote #MontantChargeMutuelle and #MontantChargeSocietaire directly;
    that part was deliberately not ported, and this is what holds it
    out."""
    for name, script in _FILL_SCRIPTS:
        for charge_name in _CHARGE_FIELD_NAMES:
            assert charge_name not in script, f"{name} must never reference {charge_name}"


def test_read_scripts_legitimately_reference_the_charge_fields():
    """Reading the split the portal computed is the whole point; writing
    it is what is forbidden. Both workflows read their own ids."""
    assert "DevisMontantChargeMutuelle" in _pec_driver_module.READ_FINANCIAL_SUMMARY_JS
    assert "DevisMontantChargeSocietaire" in _pec_driver_module.READ_FINANCIAL_SUMMARY_JS
    assert "MontantChargeMutuelle" in _normal_driver_module.READ_FINANCIAL_SUMMARY_JS
    assert "MontantChargeSocietaire" in _normal_driver_module.READ_FINANCIAL_SUMMARY_JS


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
