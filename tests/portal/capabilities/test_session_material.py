"""
INC-08 amendment #1 -- SessionMaterial never leaks secrets via repr/str/
exception text, is not JSON-serializable, has no file-writing method, and is
single-use for its one explicit handoff operation.
"""

import json

import pytest

from mcma.portal.capabilities import SessionMaterial

SECRET_STORAGE_STATE = {
    "cookies": [{"name": "session_id", "value": "SUPER_SECRET_TOKEN_VALUE"}],
    "origins": [
        {
            "origin": "http://127.0.0.1:8080",
            "localStorage": [{"name": "auth", "value": "ANOTHER_SECRET"}],
        }
    ],
}


def test_repr_and_str_never_contain_secret_material():
    material = SessionMaterial("acct-1", SECRET_STORAGE_STATE)
    assert "SUPER_SECRET_TOKEN_VALUE" not in repr(material)
    assert "ANOTHER_SECRET" not in repr(material)
    assert "SUPER_SECRET_TOKEN_VALUE" not in str(material)
    assert "ANOTHER_SECRET" not in str(material)
    assert "acct-1" in repr(material)


def test_json_dumps_raises_not_a_serialization_path():
    material = SessionMaterial("acct-1", SECRET_STORAGE_STATE)
    with pytest.raises(TypeError):
        json.dumps(material)


def test_no_file_writing_or_dict_conversion_method_exists():
    material = SessionMaterial("acct-1", SECRET_STORAGE_STATE)
    public_methods = {
        name for name in dir(material) if not name.startswith("_") and callable(getattr(material, name))
    }
    forbidden = {"save", "write", "to_file", "dump", "persist", "to_dict", "keys", "items"}
    assert not (public_methods & forbidden)


def test_storage_state_is_not_a_public_attribute():
    material = SessionMaterial("acct-1", SECRET_STORAGE_STATE)
    assert not hasattr(material, "storage_state")


def test_consume_for_handoff_returns_material_once_then_raises_without_leaking():
    material = SessionMaterial("acct-1", SECRET_STORAGE_STATE)
    handed_off = material.consume_for_handoff()
    assert handed_off == SECRET_STORAGE_STATE
    assert material.consumed is True

    with pytest.raises(RuntimeError) as exc_info:
        material.consume_for_handoff()
    assert "SUPER_SECRET_TOKEN_VALUE" not in str(exc_info.value)
    assert "ANOTHER_SECRET" not in str(exc_info.value)
