"""Server-side validation of an uploaded Playwright storage_state, applied
BEFORE anything is stored (notification onboarding). Fail closed."""

import json

import pytest

from mcma.portal.storage_state import (
    MAX_COOKIES, MAX_PLAINTEXT_BYTES, StorageStateRejected, strict_loads, validate_storage_state,
)

HOST = "sinauto.mamda-mcma.ma"


def validate(state, host=HOST):
    return validate_storage_state(state, portal_host=host)


def good():
    return {
        "cookies": [{"name": "sid", "value": "v", "domain": "sinauto.mamda-mcma.ma", "path": "/", "expires": 1900000000.5,
                     "httpOnly": True, "secure": True, "sameSite": "Lax"}],
        "origins": [{"origin": "https://sinauto.mamda-mcma.ma", "localStorage": [{"name": "k", "value": "v"}]}],
    }


def test_good_state_roundtrips():
    state = good()
    assert validate(state) == state


def test_empty_state_is_valid():
    assert validate({"cookies": [], "origins": []}) == {"cookies": [], "origins": []}


def test_both_top_level_keys_are_required():
    with pytest.raises(StorageStateRejected):
        validate({"origins": []})
    with pytest.raises(StorageStateRejected):
        validate({"cookies": []})


@pytest.mark.parametrize("mutate", [
    lambda s: s.update(extra=1),
    lambda s: s["cookies"][0].update(extra=1),
    lambda s: s["origins"][0].update(extra=1),
    lambda s: s["origins"][0]["localStorage"][0].update(extra=1),
    lambda s: s["cookies"][0].update(name=5),
    lambda s: s["cookies"][0].update(name=""),
    lambda s: s["cookies"][0].update(value="x" * 9000),
    lambda s: s["cookies"][0].update(httpOnly="yes"),
    lambda s: s["cookies"][0].update(secure=1),
    lambda s: s["cookies"][0].update(sameSite="Weird"),
    lambda s: s["cookies"][0].update(expires=True),
    lambda s: s["cookies"][0].update(expires=float("inf")),
    lambda s: s["cookies"][0].update(expires=float("nan")),
    lambda s: s["cookies"][0].update(expires="soon"),
    lambda s: s["cookies"][0].pop("domain"),
    lambda s: s.update(cookies={"a": 1}),
    lambda s: s.update(cookies=[good()["cookies"][0]] * (MAX_COOKIES + 1)),
    lambda s: s["origins"][0].update(origin="not a url"),
    lambda s: s["origins"][0].update(localStorage="x"),
    lambda s: s["origins"].extend(good()["origins"] * 60),
])
def test_bad_shapes_rejected(mutate):
    state = good()
    mutate(state)
    with pytest.raises(StorageStateRejected):
        validate(state)


def test_non_dict_rejected():
    for bad in (None, [], "x", 3):
        with pytest.raises(StorageStateRejected):
            validate(bad)


def test_total_size_bound():
    state = good()
    state["origins"][0]["localStorage"] = [{"name": f"k{i}", "value": "v" * 8000} for i in range(200)]
    assert len(json.dumps(state)) > MAX_PLAINTEXT_BYTES
    with pytest.raises(StorageStateRejected):
        validate(state)


def test_rejection_message_carries_no_input():
    state = good()
    state["cookies"][0]["value"] = "SECRET-MARKER" * 1000
    with pytest.raises(StorageStateRejected) as err:
        validate(state)
    assert "SECRET-MARKER" not in str(err.value) and "SECRET-MARKER" not in repr(err.value)


@pytest.mark.parametrize("raw", [b"NaN", b'{"a": Infinity}', b'{"a": -Infinity}', b"{", b"\xff\xfe", b'{"a":1,"a":2}',
                                 b"[" * 5000 + b"]" * 5000, b"", b'{"a": 1e999}'],
                         ids=["nan", "inf", "-inf", "truncated", "bad-utf8", "dup-key", "deep", "empty", "1e999"])
def test_strict_loads_rejects(raw):
    with pytest.raises(StorageStateRejected):
        strict_loads(raw)


def test_strict_loads_accepts_plain_json():
    assert strict_loads(b'{"a": [1, 2.5, "x", null, true]}') == {"a": [1, 2.5, "x", None, True]}


def with_domain(domain, origin=None):
    state = good()
    state["cookies"][0]["domain"] = domain
    if origin is not None:
        state["origins"][0]["origin"] = origin
    return state


@pytest.mark.parametrize("domain", [
    "evil.com", ".evil.com", "mamda-mcma.ma.evil.com", "sinauto.mamda-mcma.ma.evil.com", "evilmamda-mcma.ma",
    "xsinauto.mamda-mcma.ma", "other.mamda-mcma.ma", ".other.mamda-mcma.ma", "ma", ".ma", "", "sinauto.mamda-mcma.ma:443",
])
def test_hostile_cookie_domains_rejected(domain):
    with pytest.raises(StorageStateRejected):
        validate(with_domain(domain))


@pytest.mark.parametrize("origin", [
    "https://evil.com", "https://sinauto.mamda-mcma.ma.evil.com", "https://mamda-mcma.ma", "https://other.mamda-mcma.ma",
    "https://user@sinauto.mamda-mcma.ma", "https://user:pw@sinauto.mamda-mcma.ma", "https://evil.com@sinauto.mamda-mcma.ma",
    "https://sinauto.mamda-mcma.ma:8443", "https://sinauto.mamda-mcma.ma:443", "https://sinauto.mamda-mcma.ma:bad",
    "http://sinauto.mamda-mcma.ma", "https://sinauto.mamda-mcma.ma/path", "https://sinauto.mamda-mcma.ma/",
    "https://sinauto.mamda-mcma.ma?x=1", "https://sinauto.mamda-mcma.ma#f", "ftp://sinauto.mamda-mcma.ma",
])
def test_hostile_origins_rejected(origin):
    with pytest.raises(StorageStateRejected):
        validate(with_domain(HOST, origin))


@pytest.mark.parametrize("domain", ["sinauto.mamda-mcma.ma", ".sinauto.mamda-mcma.ma", "SINAUTO.mamda-mcma.ma",
                                    "mamda-mcma.ma", ".mamda-mcma.ma"])
def test_exact_host_and_reviewed_parent_cookie_domains_accepted(domain):
    validate(with_domain(domain))


def test_parent_domain_is_not_accepted_for_another_configured_host():
    state = with_domain("mamda-mcma.ma", "https://portal.other.example")
    with pytest.raises(StorageStateRejected):
        validate(state, host="portal.other.example")
    validate(with_domain("portal.other.example", "https://portal.other.example"), host="portal.other.example")


def test_loopback_test_portal_is_narrow_and_does_not_widen_production():
    state = with_domain("127.0.0.1", "http://127.0.0.1:8765")
    validate(state, host="127.0.0.1")
    with pytest.raises(StorageStateRejected):
        validate(state)                                    # production host refuses loopback material
    with pytest.raises(StorageStateRejected):
        validate(with_domain("localhost", "http://127.0.0.1:8765"), host="127.0.0.1")
    with pytest.raises(StorageStateRejected):
        validate(with_domain("127.0.0.1", "http://evil.com"), host="127.0.0.1")


def test_a_host_in_the_request_cannot_change_the_policy():
    state = good()
    state["portal_host"] = "evil.com"
    with pytest.raises(StorageStateRejected):
        validate(state)
