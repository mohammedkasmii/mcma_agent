"""
INC-09B -- every writer.py exception's message must contain no identity,
registration, claim, or monetary value -- only field/reason names (the
same discipline already established for mcma.portal.identity.
IdentityMismatch in 09A).
"""

import inspect

import mcma.portal.writer as writer_module

_FORBIDDEN_SNIPPETS = ("34602-B-7", "534660", "10.00", "612001", "699001")


def _all_writeaborted_subclasses():
    for name, obj in vars(writer_module).items():
        if isinstance(obj, type) and issubclass(obj, writer_module.WriteAborted):
            yield name, obj


def test_no_exception_class_source_embeds_an_example_pii_value():
    for name, cls in _all_writeaborted_subclasses():
        source = inspect.getsource(cls)
        for snippet in _FORBIDDEN_SNIPPETS:
            assert snippet not in source, f"{name} source must not embed an example PII value {snippet!r}"


def test_identity_mismatch_message_contains_only_field_name():
    from mcma.domain.values import IdSinistre, RegistrationPlate
    from mcma.portal.identity import ExpectedIdentity, IdentityMismatch, ObservedIdentity, verify_identity

    expected = ExpectedIdentity(registration=RegistrationPlate("34602-B-7"), id_sinistre=IdSinistre("534660"))
    observed = ObservedIdentity(registration=RegistrationPlate("00000-A-00"), insurer_reference=None, id_sinistre=None)
    try:
        verify_identity(expected, observed)
    except IdentityMismatch as exc:
        message = str(exc)
        assert "34602-B-7" not in message
        assert "00000-A-00" not in message
        assert "registration" in message
    else:
        raise AssertionError("expected IdentityMismatch")


def test_writer_plan_data_default_repr_is_not_embedded_in_any_write_aborted_raise_site():
    """WriterPlanData/PortalRowIntent's default dataclass repr would show
    Money/RubriqueId values -- writer.py's source must never interpolate
    self._writer_plan (or an intent) into a raised message."""
    source = inspect.getsource(writer_module)
    assert "{self._writer_plan" not in source
    assert "{intent!r}" not in source
    assert "{intent}" not in source
